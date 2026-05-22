#!/usr/bin/env python3
"""
FloatTrip Baidu web search raw output inspector.

Call Baidu AppBuilder's non-chat web search endpoint and print the raw JSON
response, so we can inspect the original references before any processing.

Examples:
  python3 tools/baidu_web_search_raw.py "北京有哪些旅游景区" --json
  python3 tools/baidu_web_search_raw.py 常州 --days 3 --travel-queries --top-k 10 --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import HTTPError


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripBaiduWebSearchRaw/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"
SCRIPT_DIR = Path(__file__).resolve().parent
BAIDU_WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from place_candidate_pool import build_queries, parse_preferences
from search_corpus import (
    SearchCorpus,
    SearchDocument,
    dedupe_documents,
    normalize_text,
    search_corpus_to_dict,
)


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


def safe_read_http_error(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc)
    return body[:1200] if body else str(exc)


def post_json(url: str, payload: dict[str, Any], api_key: str, timeout: int, retries: int) -> dict[str, Any]:
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
    raise RuntimeError(f"百度非 AI 搜索请求失败：{last_error}")


def baidu_web_search(query: str, api_key: str, top_k: int, edition: str, timeout: int, retries: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": query}],
        "edition": edition,
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": top_k}],
    }
    return post_json(BAIDU_WEB_SEARCH_URL, payload, api_key, timeout=timeout, retries=retries)


def build_query_list(args: argparse.Namespace) -> list[str]:
    if args.travel_queries:
        preferences = parse_preferences(args.preferences)
        return build_queries(args.query, args.days, preferences)
    return [args.query]


def collect_raw_results(args: argparse.Namespace) -> dict[str, Any] | list[dict[str, Any]]:
    api_key = require_baidu_key()
    queries = build_query_list(args)
    if len(queries) == 1:
        return baidu_web_search(queries[0], api_key, args.top_k, args.edition, args.timeout, args.retries)

    output: list[dict[str, Any]] = []
    for query in queries:
        try:
            response = baidu_web_search(query, api_key, args.top_k, args.edition, args.timeout, args.retries)
            output.append({"query": query, "response": response})
        except Exception as exc:
            output.append({"query": query, "error": str(exc)})
    return output


def collect_search_corpus(args: argparse.Namespace) -> SearchCorpus:
    api_key = require_baidu_key()
    preferences = parse_preferences(args.preferences) if args.travel_queries else []
    queries = build_query_list(args)
    documents: list[SearchDocument] = []
    raw_responses: list[dict[str, Any]] = []
    provider = "baidu_web_search"

    for query in queries:
        try:
            response = baidu_web_search(query, api_key, args.top_k, args.edition, args.timeout, args.retries)
        except Exception as exc:
            raw_responses.append({"query": query, "error": str(exc)})
            continue

        raw_responses.append({"query": query, "request_id": response.get("request_id")})
        references = response.get("references", [])
        if not isinstance(references, list):
            continue
        for index, item in enumerate(references, start=1):
            if not isinstance(item, dict):
                continue
            document = baidu_reference_to_document(item, provider, query, index)
            if document:
                documents.append(document)

    return SearchCorpus(
        destination=args.query if args.travel_queries else "",
        days=args.days if args.travel_queries else 0,
        preferences=preferences,
        queries=queries,
        providers=[provider],
        documents=dedupe_documents(documents),
        raw_responses=raw_responses,
    )


def baidu_reference_to_document(
    item: dict[str, Any],
    provider: str,
    query: str,
    rank: int,
) -> SearchDocument | None:
    url = str(item.get("url") or item.get("link") or "").strip()
    if not url:
        return None
    content = normalize_text(item.get("content") or item.get("summary") or "")
    snippet = normalize_text(item.get("snippet") or content[:300])
    scores: dict[str, float] = {}
    for key in ("rerank_score", "authority_score"):
        try:
            if item.get(key) is not None:
                scores[key] = float(item[key])
        except (TypeError, ValueError):
            continue
    return SearchDocument(
        document_id=f"{provider}:{rank}:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}",
        provider=provider,
        query=query,
        title=normalize_text(item.get("title")),
        url=url,
        site_name=normalize_text(item.get("website") or item.get("site_name")),
        published_at=normalize_text(item.get("date") or item.get("published_at")),
        content=content or snippet,
        snippet=snippet,
        rank=rank,
        scores=scores,
        raw=item,
    )


def main() -> int:
    load_local_env()

    parser = argparse.ArgumentParser(description="调用百度 AppBuilder 非 AI 网页搜索接口，并输出原始 JSON。")
    parser.add_argument("query", help="搜索 query；使用 --travel-queries 时填目的地，例如：常州")
    parser.add_argument("--days", type=int, default=3, help="旅行天数，仅 --travel-queries 时使用，默认 3")
    parser.add_argument("--preferences", default="", help="旅行偏好，仅 --travel-queries 时使用，逗号分隔，例如：亲子,博物馆")
    parser.add_argument("--travel-queries", action="store_true", help="把 query 当作目的地，使用 FloatTrip 旅行搜索词批量查询")
    parser.add_argument("--top-k", type=int, default=10, help="网页搜索返回条数，最大 50，默认 10")
    parser.add_argument("--edition", choices=["standard", "lite"], default="standard", help="搜索版本，默认 standard")
    parser.add_argument("--timeout", type=int, default=30, help="单次请求超时秒数，默认 30")
    parser.add_argument("--retries", type=int, default=1, help="失败重试次数，默认 1")
    parser.add_argument("--json", action="store_true", help="输出 pretty JSON；当前脚本默认也输出 JSON，保留该参数便于命令语义清晰")
    parser.add_argument("--corpus-json", action="store_true", help="输出统一 SearchCorpus JSON，供 LLM 候选池模块使用")
    args = parser.parse_args()

    try:
        output = search_corpus_to_dict(collect_search_corpus(args)) if args.corpus_json else collect_raw_results(args)
    except Exception as exc:
        print(f"百度非 AI 搜索失败：{exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
