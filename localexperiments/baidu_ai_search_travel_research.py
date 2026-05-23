#!/usr/bin/env python3
"""
FloatTrip Baidu AI Search travel research collector.

Use Baidu Qianfan AppBuilder AI Search to collect Chinese travel information
and turn web references into the same candidate_pool shape used by the other
FloatTrip research scripts.

Examples:
  python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --json
  python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --names
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripBaiduAISearch/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"
SCRIPT_DIR = Path(__file__).resolve().parent
BAIDU_AI_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"
DEFAULT_BAIDU_AI_SEARCH_MODEL = "ernie-4.5-turbo-32k"
DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from place_candidate_pool import Source, build_queries, normalize_text, parse_preferences


@dataclass(frozen=True)
class BaiduSearchResult:
    title: str
    url: str
    content: str
    date: str
    website: str
    query: str


@dataclass(frozen=True)
class CandidatePlace:
    name: str
    mention_count: int
    score: int
    sources: list[Source]


def load_local_env() -> None:
    if not LOCAL_ENV_FILE.exists():
        return
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_baidu_key() -> str:
    api_key = os.getenv("BAIDU_APPBUILDER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 BAIDU_APPBUILDER_API_KEY。请在环境变量或 .env.local 中配置百度 AppBuilder API Key 后重试。")
    return api_key


def require_deepseek_key() -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY。百度候选池现在需要 LLM 结构化，请在环境变量或 .env.local 中配置后重试。")
    return api_key


def post_json(url: str, payload: dict[str, Any], api_key: str, timeout: int = 60, retries: int = 1) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "X-Appbuilder-Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            last_error = RuntimeError(f"HTTP {exc.code}: {safe_read_http_error(exc)}")
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"百度 AI 搜索请求失败：{last_error}")


def safe_read_http_error(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc)
    return body[:1200] if body else str(exc)


def baidu_ai_search(
    query: str,
    api_key: str,
    top_k: int,
    enable_deep_search: bool,
    model: str,
    timeout: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": query}],
        "model": model,
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": top_k}],
        "search_mode": "required",
        "stream": False,
        "enable_deep_search": enable_deep_search,
        "enable_followup_queries": False,
        "enable_reasoning": False,
        "response_format": "text",
    }
    return post_json(BAIDU_AI_SEARCH_URL, payload, api_key, timeout=timeout)


def collect_baidu_results(
    destination: str,
    days: int,
    preferences: list[str],
    top_k: int,
    enable_deep_search: bool,
    model: str,
    max_workers: int,
    timeout: int,
) -> tuple[list[BaiduSearchResult], list[dict[str, Any]]]:
    api_key = require_baidu_key()
    seen_urls: set[str] = set()
    collected: list[BaiduSearchResult] = []
    raw_responses: list[dict[str, Any]] = []
    queries = build_queries(destination, days, preferences)
    workers = max(1, min(max_workers, len(queries)))

    print(f"[info] 并行百度搜索：{len(queries)} 个 query，workers={workers}", file=sys.stderr, flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_query = {
            executor.submit(baidu_ai_search, query, api_key, top_k, enable_deep_search, model, timeout): query
            for query in queries
        }
        responses: list[tuple[int, str, dict[str, Any]]] = []
        query_order = {query: index for index, query in enumerate(queries)}
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            try:
                response = future.result()
            except Exception as exc:
                print(f"[warn] 百度 AI 搜索失败：query={query!r}；{exc}", file=sys.stderr, flush=True)
                continue
            references = extract_web_references(response)
            print(f"[info] 百度搜索完成：query={query!r}，网页引用 {len(references)} 条", file=sys.stderr, flush=True)
            responses.append((query_order[query], query, response))

    for _index, query, response in sorted(responses, key=lambda item: item[0]):
        raw_responses.append(summarize_baidu_response(query, response))
        for item in extract_web_references(response):
            url = str(item.get("url") or item.get("link") or "").strip()
            if not url:
                continue
            normalized_url = url.split("#", 1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            collected.append(
                BaiduSearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=url,
                    content=str(item.get("content") or item.get("summary") or item.get("snippet") or "").strip(),
                    date=str(item.get("date", "")).strip(),
                    website=str(item.get("website") or item.get("site_name") or "").strip(),
                    query=query,
                )
            )
    return collected, raw_responses


def summarize_baidu_response(query: str, response: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": query,
        "id": response.get("id"),
        "created": response.get("created"),
        "usage": response.get("usage"),
        "answer": extract_answer_text(response),
    }


def extract_answer_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    return str(message.get("content", "")).strip()


def extract_web_references(response: dict[str, Any]) -> list[dict[str, Any]]:
    references = find_reference_lists(response)
    web_items: list[dict[str, Any]] = []
    for item in references:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or item.get("resource_type") or "web").lower()
        if item_type and item_type != "web":
            continue
        if item.get("url") or item.get("link"):
            web_items.append(item)
    return web_items


def find_reference_lists(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"references", "search_results", "web_search_results", "resources"} and isinstance(child, list):
                found.extend(item for item in child if isinstance(item, dict))
            else:
                found.extend(find_reference_lists(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_reference_lists(child))
    return found


def build_candidate_pool(results: list[BaiduSearchResult], destination: str) -> list[CandidatePlace]:
    raise RuntimeError("百度候选池已切换为 LLM 结构化，请调用 build_candidate_pool_with_llm")


def build_candidate_pool_with_llm(
    destination: str,
    days: int,
    preferences: list[str],
    results: list[BaiduSearchResult],
    model: str,
) -> list[CandidatePlace]:
    if not results:
        return []
    raw_candidates = call_deepseek_for_candidate_pool(destination, days, preferences, results, model)
    return normalize_llm_candidate_pool(raw_candidates, results)


def call_deepseek_for_candidate_pool(
    destination: str,
    days: int,
    preferences: list[str],
    results: list[BaiduSearchResult],
    model: str,
) -> list[dict[str, Any]]:
    api_key = require_deepseek_key()
    model = normalize_deepseek_model(model)
    prompt = build_candidate_pool_prompt(destination, days, preferences, results)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是 FloatTrip 的旅行景点候选池结构化抽取器。你只输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        DEEPSEEK_CHAT_COMPLETIONS_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            completion = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"DeepSeek 请求失败：HTTP {exc.code}: {safe_read_http_error(exc)}") from exc
    content = completion["choices"][0]["message"]["content"]
    parsed = parse_json_object(content)
    candidate_pool = parsed.get("candidate_pool", [])
    if not isinstance(candidate_pool, list):
        raise RuntimeError("LLM 返回 JSON 缺少 candidate_pool 数组")
    return [item for item in candidate_pool if isinstance(item, dict)]


def normalize_deepseek_model(model: str) -> str:
    legacy_aliases = {
        "deepseekv4flash": "deepseek-v4-flash",
        "deepseekv4pro": "deepseek-v4-pro",
    }
    return legacy_aliases.get(model.strip(), model.strip())


def build_candidate_pool_prompt(
    destination: str,
    days: int,
    preferences: list[str],
    results: list[BaiduSearchResult],
) -> str:
    compact_results = [
        {
            "source_id": index,
            "title": result.title,
            "url": result.url,
            "website": result.website,
            "date": result.date,
            "content": result.content[:1600],
        }
        for index, result in enumerate(results, start=1)
    ]
    return f"""
请从百度搜索结果中为 FloatTrip 生成 {destination} {days} 天游的候选景点池。

用户偏好：{", ".join(preferences) if preferences else "无"}

只返回 JSON，不要解释。JSON 格式必须是：
{{
  "candidate_pool": [
    {{
      "name": "景点标准中文名",
      "mention_count": 3,
      "score": 3,
      "sources": [
        {{
          "title": "来源标题",
          "url": "来源URL",
          "snippet": "能证明该景点被提到的短摘要"
        }}
      ]
    }}
  ]
}}

硬性规则：
- 只保留真实可游玩的景点、景区、博物馆、公园、历史街区、古镇、寺庙、主题乐园、自然风景区。
- 不要输出酒店、餐厅、美食、政府机构、地址、交通站点、普通商圈、攻略词、路线词、活动短语、门票/预约/开放时间。
- 不要输出“10个4A景区”“下午场入园”“专业博物馆”“常州市新北区某地址”这类非景点。
- 繁体转简体，例如“天寧寺”输出“天宁寺”。
- 同一景点别名要合并为一个标准名，例如“恐龙园”和“中华恐龙园”合并为“中华恐龙园”。
- 同一来源里同一景点只计 1 次；mention_count 是提到该景点的不同来源数量。
- score 第一版等于 mention_count。
- sources 只放实际提到该景点的来源，最多 5 条。
- 按 score 降序输出；如果没有可靠景点，返回空数组。

百度搜索结果：
{json.dumps(compact_results, ensure_ascii=False, indent=2)}
""".strip()


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise RuntimeError("LLM 返回的不是 JSON object")
    return data


def normalize_llm_candidate_pool(
    raw_candidates: list[dict[str, Any]],
    results: list[BaiduSearchResult],
) -> list[CandidatePlace]:
    source_by_url = {result.url: result for result in results}
    candidates: list[CandidatePlace] = []
    seen_names: set[str] = set()
    for item in raw_candidates:
        name = normalize_text(str(item.get("name", ""))).strip("，。；、：:()（）[]【】 ")
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        sources = normalize_llm_sources(item.get("sources", []), source_by_url)
        mention_count = int(item.get("mention_count") or len(sources) or 1)
        score = int(item.get("score") or mention_count)
        candidates.append(
            CandidatePlace(
                name=name,
                mention_count=mention_count,
                score=score,
                sources=sources,
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.name))


def normalize_llm_sources(value: Any, source_by_url: dict[str, BaiduSearchResult]) -> list[Source]:
    if not isinstance(value, list):
        return []
    sources: list[Source] = []
    seen_urls: set[str] = set()
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        original = source_by_url.get(url)
        title = normalize_text(str(item.get("title") or (original.title if original else "")))
        snippet = normalize_text(str(item.get("snippet") or (original.content[:160] if original else "")))
        sources.append(Source(title=title, url=url, snippet=snippet))
    return sources


def build_output(
    destination: str,
    days: int,
    preferences: list[str],
    results: list[BaiduSearchResult],
    raw_responses: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    return {
        "destination": destination,
        "days": days,
        "preferences": preferences,
        "provider": "baidu_ai_search",
        "candidate_builder": "deepseek_llm",
        "search_results": [asdict(result) for result in results],
        "search_responses": raw_responses,
        "candidate_pool": [
            asdict(candidate)
            for candidate in build_candidate_pool_with_llm(destination, days, preferences, results, model)
        ],
    }


def print_human_report(output: dict[str, Any]) -> None:
    print(f"\nFloatTrip 百度 AI 搜索信息搜集：{output['destination']} {output['days']} 天游")
    print(f"搜索结果：{len(output['search_results'])} 条")
    print(f"候选景点：{len(output['candidate_pool'])} 个\n")
    for item in output["candidate_pool"][:20]:
        print(f"- {item['name']}｜score={item['score']}｜出现 {item['mention_count']} 次")


def extract_candidate_names(output: dict[str, Any]) -> list[str]:
    candidates = output.get("candidate_pool", [])
    if not isinstance(candidates, list):
        return []
    return [str(candidate.get("name", "")) for candidate in candidates if isinstance(candidate, dict) and candidate.get("name")]


def print_candidate_names(output: dict[str, Any]) -> None:
    for name in extract_candidate_names(output):
        print(name)


def main() -> int:
    load_local_env()

    parser = argparse.ArgumentParser(description="使用百度 AI 搜索搜集旅行攻略信息并生成候选景点池。")
    parser.add_argument("destination", help="目的地，例如：常州")
    parser.add_argument("--days", type=int, default=3, help="旅行天数，默认 3")
    parser.add_argument("--preferences", default="", help="偏好，逗号分隔，例如：亲子,博物馆")
    parser.add_argument("--top-k", type=int, default=10, help="每个搜索词最多取几条百度网页引用，默认 10")
    parser.add_argument("--deep-search", action="store_true", help="开启百度深度搜索，成本和耗时更高")
    parser.add_argument("--max-workers", type=int, default=4, help="并行百度搜索 worker 数，默认 4")
    parser.add_argument("--baidu-timeout", type=int, default=60, help="单个百度搜索请求超时秒数，默认 60")
    parser.add_argument(
        "--baidu-model",
        default=os.getenv("BAIDU_AI_SEARCH_MODEL", DEFAULT_BAIDU_AI_SEARCH_MODEL),
        help=f"百度 AI 搜索总结模型，默认 {DEFAULT_BAIDU_AI_SEARCH_MODEL}",
    )
    parser.add_argument(
        "--deepseek-model",
        default=os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        help=f"DeepSeek 模型名，默认 {DEFAULT_DEEPSEEK_MODEL}",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--names-json", action="store_true", help="只输出百度候选景点名称 JSON 数组")
    parser.add_argument("--names", action="store_true", help="只按降序逐行输出百度候选景点名称")
    args = parser.parse_args()

    preferences = parse_preferences(args.preferences)
    try:
        results, raw_responses = collect_baidu_results(
            args.destination,
            args.days,
            preferences,
            args.top_k,
            args.deep_search,
            args.baidu_model,
            args.max_workers,
            args.baidu_timeout,
        )
        output = build_output(args.destination, args.days, preferences, results, raw_responses, args.deepseek_model)
    except Exception as exc:
        print(f"百度 AI 搜索信息搜集失败：{exc}", file=sys.stderr)
        return 1

    if args.names:
        print_candidate_names(output)
    elif args.names_json:
        print(json.dumps(extract_candidate_names(output), ensure_ascii=False, indent=2))
    elif args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_human_report(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
