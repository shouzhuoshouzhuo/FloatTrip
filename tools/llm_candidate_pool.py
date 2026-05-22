#!/usr/bin/env python3
"""
FloatTrip LLM candidate pool builder.

Read a provider-neutral SearchCorpus JSON file and ask an LLM to extract a
candidate attraction pool. Search collection and LLM extraction stay decoupled.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripLlmCandidatePool/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"
SCRIPT_DIR = Path(__file__).resolve().parent
DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from place_candidate_pool import Source, normalize_text
from search_corpus import load_search_corpus


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


def require_deepseek_key() -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY。请在环境变量或 .env.local 中配置后重试。")
    return api_key


def normalize_deepseek_model(model: str) -> str:
    legacy_aliases = {
        "deepseekv4flash": "deepseek-v4-flash",
        "deepseekv4pro": "deepseek-v4-pro",
    }
    return legacy_aliases.get(model.strip(), model.strip())


def safe_read_http_error(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc)
    return body[:1200] if body else str(exc)


def call_deepseek(prompt: str, model: str, timeout: int) -> dict[str, Any]:
    api_key = require_deepseek_key()
    payload = {
        "model": normalize_deepseek_model(model),
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"DeepSeek 请求失败：HTTP {exc.code}: {safe_read_http_error(exc)}") from exc


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


def build_candidate_pool_prompt(corpus: dict[str, Any], content_chars: int) -> str:
    documents = []
    for index, document in enumerate(corpus.get("documents", []), start=1):
        if not isinstance(document, dict):
            continue
        content = normalize_text(str(document.get("content") or document.get("snippet") or ""))
        documents.append(
            {
                "source_id": index,
                "document_id": document.get("document_id"),
                "provider": document.get("provider"),
                "query": document.get("query"),
                "title": document.get("title"),
                "url": document.get("url"),
                "site_name": document.get("site_name"),
                "published_at": document.get("published_at"),
                "content": content[:content_chars],
            }
        )

    destination = str(corpus.get("destination") or "")
    days = int(corpus.get("days") or 0)
    preferences = corpus.get("preferences", [])
    preference_text = ", ".join(str(item) for item in preferences) if isinstance(preferences, list) and preferences else "无"
    return f"""
请从搜索语料中为 FloatTrip 生成 {destination or "目的地"} {days or ""} 天游的候选景点池。

用户偏好：{preference_text}

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
- 同一景点别名要合并为一个标准名，例如“恐龙园”和“中华恐龙园”合并为“中华恐龙园”。
- 同一来源里同一景点只计 1 次；mention_count 是提到该景点的不同来源数量。
- score 第一版等于 mention_count。
- sources 只放实际提到该景点的来源，最多 5 条。
- sources.snippet 要短，优先引用能证明该景点存在的内容。
- 按 score 降序输出；如果没有可靠景点，返回空数组。

搜索语料：
{json.dumps(documents, ensure_ascii=False, indent=2)}
""".strip()


def extract_llm_candidate_pool(completion: dict[str, Any]) -> list[dict[str, Any]]:
    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM 返回缺少 choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("LLM choices[0] 不是 JSON object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("LLM choices[0].message 不是 JSON object")
    content = str(message.get("content", "")).strip()
    parsed = parse_json_object(content)
    candidate_pool = parsed.get("candidate_pool", [])
    if not isinstance(candidate_pool, list):
        raise RuntimeError("LLM 返回 JSON 缺少 candidate_pool 数组")
    return [item for item in candidate_pool if isinstance(item, dict)]


def normalize_llm_candidate_pool(raw_candidates: list[dict[str, Any]], corpus: dict[str, Any]) -> list[CandidatePlace]:
    source_by_url = {
        str(document.get("url", "")).strip(): document
        for document in corpus.get("documents", [])
        if isinstance(document, dict) and document.get("url")
    }
    candidates: list[CandidatePlace] = []
    seen_names: set[str] = set()
    for item in raw_candidates:
        name = normalize_text(str(item.get("name", ""))).strip("，。；、：:()（）[]【】 ")
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        sources = normalize_sources(item.get("sources", []), source_by_url)
        mention_count = to_positive_int(item.get("mention_count"), len(sources) or 1)
        score = to_positive_int(item.get("score"), mention_count)
        candidates.append(CandidatePlace(name=name, mention_count=mention_count, score=score, sources=sources))
    return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.name))


def normalize_sources(value: Any, source_by_url: dict[str, dict[str, Any]]) -> list[Source]:
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
        original = source_by_url.get(url, {})
        title = normalize_text(str(item.get("title") or original.get("title") or ""))
        fallback_snippet = str(original.get("snippet") or original.get("content") or "")[:180]
        snippet = normalize_text(str(item.get("snippet") or fallback_snippet))
        sources.append(Source(title=title, url=url, snippet=snippet))
    return sources


def to_positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def build_output(corpus: dict[str, Any], model: str, candidates: list[CandidatePlace]) -> dict[str, Any]:
    return {
        "schema_version": "candidate_pool.v1",
        "destination": corpus.get("destination"),
        "days": corpus.get("days"),
        "preferences": corpus.get("preferences", []),
        "source_schema_version": corpus.get("schema_version"),
        "provider": "llm_candidate_pool",
        "candidate_builder": "deepseek_llm",
        "model": normalize_deepseek_model(model),
        "source_document_count": len(corpus.get("documents", [])),
        "candidate_pool": [asdict(candidate) for candidate in candidates],
    }


def extract_candidate_names(output: dict[str, Any]) -> list[str]:
    candidates = output.get("candidate_pool", [])
    if not isinstance(candidates, list):
        return []
    return [str(candidate.get("name", "")) for candidate in candidates if isinstance(candidate, dict) and candidate.get("name")]


def print_human_report(output: dict[str, Any]) -> None:
    print(f"\nFloatTrip LLM 候选景点池：{output.get('destination') or '未指定目的地'}")
    print(f"搜索文档：{output['source_document_count']} 条")
    print(f"候选景点：{len(output['candidate_pool'])} 个\n")
    for item in output["candidate_pool"][:20]:
        print(f"- {item['name']}｜score={item['score']}｜出现 {item['mention_count']} 次")


def main() -> int:
    load_local_env()

    parser = argparse.ArgumentParser(description="读取 SearchCorpus JSON，并用 LLM 生成候选景点池。")
    parser.add_argument("search_corpus_json", help="SearchCorpus JSON 文件路径")
    parser.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL), help=f"DeepSeek 模型，默认 {DEFAULT_DEEPSEEK_MODEL}")
    parser.add_argument("--content-chars", type=int, default=1800, help="每篇搜索文档送入 LLM 的最大字符数，默认 1800")
    parser.add_argument("--timeout", type=int, default=90, help="LLM 请求超时秒数，默认 90")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--names-json", action="store_true", help="只输出候选景点名称 JSON 数组")
    parser.add_argument("--names", action="store_true", help="只按降序逐行输出候选景点名称")
    args = parser.parse_args()

    try:
        corpus = load_search_corpus(args.search_corpus_json)
        prompt = build_candidate_pool_prompt(corpus, args.content_chars)
        completion = call_deepseek(prompt, args.model, args.timeout)
        raw_candidates = extract_llm_candidate_pool(completion)
        output = build_output(corpus, args.model, normalize_llm_candidate_pool(raw_candidates, corpus))
    except Exception as exc:
        print(f"LLM 候选景点池生成失败：{exc}", file=sys.stderr)
        return 1

    if args.names:
        for name in extract_candidate_names(output):
            print(name)
    elif args.names_json:
        print(json.dumps(extract_candidate_names(output), ensure_ascii=False, indent=2))
    elif args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_human_report(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
