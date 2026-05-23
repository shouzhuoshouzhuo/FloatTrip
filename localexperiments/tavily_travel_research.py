#!/usr/bin/env python3
"""
FloatTrip Tavily travel research collector.

Use Tavily Search API to collect travel guide information and turn search
snippets into the same candidate_pool shape used by place_candidate_pool.py.

Examples:
  python3 tools/tavily_travel_research.py 南京 --days 3 --preferences 历史文化,美食 --json
  python3 tools/tavily_travel_research.py 成都 --days 4 --max-results 8 --include-answer --json
  python3 tools/tavily_travel_research.py 南京 --days 3 --names
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripTavilyResearch/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"
SCRIPT_DIR = Path(__file__).resolve().parent
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from place_candidate_pool import Source, build_queries, extract_places_from_result, parse_preferences


@dataclass(frozen=True)
class TavilySearchResult:
    title: str
    url: str
    content: str
    score: float
    query: str


@dataclass(frozen=True)
class CandidatePlace:
    name: str
    mention_count: int
    score: int
    sources: list[Source]


class CandidateExtractionResult:
    def __init__(self, title: str, url: str, snippet: str) -> None:
        self.title = title
        self.url = url
        self.snippet = snippet


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


def require_tavily_key() -> str:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 TAVILY_API_KEY。请在环境变量或 .env.local 中配置 Tavily API Key 后重试。")
    return api_key


def post_json(url: str, payload: dict[str, Any], api_key: str, timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Tavily 请求失败：{last_error}")


def tavily_search(
    query: str,
    api_key: str,
    max_results: int,
    search_depth: str,
    include_answer: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "topic": "general",
        "country": "china",
        "include_answer": include_answer,
        "include_raw_content": False,
        "include_images": False,
        "include_favicon": False,
        "include_usage": True,
    }
    return post_json(TAVILY_SEARCH_URL, payload, api_key)


def collect_tavily_results(
    destination: str,
    days: int,
    preferences: list[str],
    max_results: int,
    search_depth: str,
    include_answer: bool,
) -> tuple[list[TavilySearchResult], list[dict[str, Any]]]:
    api_key = require_tavily_key()
    seen_urls: set[str] = set()
    collected: list[TavilySearchResult] = []
    raw_responses: list[dict[str, Any]] = []

    for query in build_queries(destination, days, preferences):
        try:
            response = tavily_search(query, api_key, max_results, search_depth, include_answer)
        except Exception as exc:
            print(f"[warn] Tavily 搜索失败：query={query!r}；{exc}", file=sys.stderr)
            continue

        raw_responses.append(summarize_tavily_response(query, response))
        for item in response.get("results", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            normalized_url = url.split("#", 1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            collected.append(
                TavilySearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=url,
                    content=str(item.get("content", "")).strip(),
                    score=float(item.get("score", 0) or 0),
                    query=query,
                )
            )
        time.sleep(0.4)
    return collected, raw_responses


def summarize_tavily_response(query: str, response: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": query,
        "answer": response.get("answer"),
        "response_time": response.get("response_time"),
        "usage": response.get("usage"),
        "request_id": response.get("request_id"),
    }


def build_candidate_pool(results: list[TavilySearchResult], destination: str) -> list[CandidatePlace]:
    counts: Counter[str] = Counter()
    source_map: dict[str, list[Source]] = defaultdict(list)
    seen_source_place: set[tuple[str, str]] = set()

    for result in results:
        source = Source(title=result.title, url=result.url, snippet=result.content)
        source_key = result.url.split("#", 1)[0]
        extraction_result = CandidateExtractionResult(result.title, result.url, result.content)
        for place in extract_places_from_result(extraction_result, destination):
            key = (source_key, place)
            if key in seen_source_place:
                continue
            seen_source_place.add(key)
            counts[place] += 1
            source_map[place].append(source)

    candidates = [
        CandidatePlace(
            name=name,
            mention_count=count,
            score=count,
            sources=source_map[name],
        )
        for name, count in counts.items()
    ]
    return sorted(candidates, key=lambda item: (-item.score, item.name))


def build_output(
    destination: str,
    days: int,
    preferences: list[str],
    results: list[TavilySearchResult],
    raw_responses: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "destination": destination,
        "days": days,
        "preferences": preferences,
        "provider": "tavily",
        "search_results": [asdict(result) for result in results],
        "search_responses": raw_responses,
        "candidate_pool": [asdict(candidate) for candidate in build_candidate_pool(results, destination)],
    }


def print_human_report(output: dict[str, Any]) -> None:
    print(f"\nFloatTrip Tavily 信息搜集：{output['destination']} {output['days']} 天游")
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

    parser = argparse.ArgumentParser(description="使用 Tavily API 搜集旅行攻略信息并生成候选景点池。")
    parser.add_argument("destination", help="目的地，例如：南京")
    parser.add_argument("--days", type=int, default=3, help="旅行天数，默认 3")
    parser.add_argument("--preferences", default="", help="偏好，逗号分隔，例如：历史文化,美食")
    parser.add_argument("--max-results", type=int, default=5, help="每个搜索词最多取几条 Tavily 结果，默认 5")
    parser.add_argument(
        "--search-depth",
        choices=("basic", "advanced", "fast", "ultra-fast"),
        default="basic",
        help="Tavily 搜索深度，默认 basic",
    )
    parser.add_argument("--include-answer", action="store_true", help="让 Tavily 返回查询摘要 answer")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--names-json", action="store_true", help="只输出 Tavily 候选景点名称 JSON 数组")
    parser.add_argument("--names", action="store_true", help="只按降序逐行输出 Tavily 候选景点名称")
    args = parser.parse_args()

    preferences = parse_preferences(args.preferences)
    try:
        results, raw_responses = collect_tavily_results(
            args.destination,
            args.days,
            preferences,
            args.max_results,
            args.search_depth,
            args.include_answer,
        )
        output = build_output(args.destination, args.days, preferences, results, raw_responses)
    except Exception as exc:
        print(f"Tavily 信息搜集失败：{exc}", file=sys.stderr)
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
