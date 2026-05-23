#!/usr/bin/env python3
"""
FloatTrip place candidate pool builder.

Search Baidu via SearchAPI, extract attraction-like place names from search
results, and rank candidates by cross-source mention count.

Examples:
  python3 tools/place_candidate_pool.py 南京 --days 3 --preferences 历史文化,美食 --json
  python3 tools/place_candidate_pool.py 成都 --days 4
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripPlaceCandidatePool/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"

PLACE_SUFFIXES = (
    "博物院",
    "博物馆",
    "纪念馆",
    "美术馆",
    "科技馆",
    "动物园",
    "植物园",
    "游乐园",
    "主题乐园",
    "古镇",
    "古城",
    "古街",
    "步行街",
    "商业街",
    "夜市",
    "公园",
    "湿地",
    "景区",
    "风景区",
    "度假区",
    "广场",
    "大学",
    "寺",
    "庙",
    "宫",
    "观",
    "陵",
    "湖",
    "山",
    "岛",
    "湾",
    "滩",
    "街",
    "巷",
    "园",
    "府",
)

BLOCKED_EXACT_NAMES = {
    "旅游攻略",
    "自由行",
    "必去景点",
    "热门景点",
    "开放时间",
    "预约入口",
    "路线",
    "攻略",
    "首页",
    "上一篇",
    "下一篇",
}

BLOCKED_PARTS = (
    "攻略",
    "路线",
    "行程",
    "开放时间",
    "预约入口",
    "门票预约",
    "点击",
    "详情",
    "电话",
    "地址",
    "地图",
    "酒店",
    "民宿",
    "机票",
    "高铁",
    "自驾",
)


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


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


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return normalize_text(html.unescape(value))


def http_get(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"请求失败：{redact_url(url)}；原因：{last_error}")


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for secret_key in ("api_key", "key", "access_token", "token"):
        if secret_key in query:
            query[secret_key] = ["<redacted>"]
    redacted_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=redacted_query))


def chinese_days(days: int) -> str:
    mapping = {1: "一日游", 2: "两日游", 3: "三日游", 4: "四日游", 5: "五日游", 6: "六日游", 7: "七日游"}
    return mapping.get(days, f"{days}日游")


def parse_preferences(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_queries(destination: str, days: int, preferences: list[str]) -> list[str]:
    day_text = chinese_days(days)
    queries = [
        f"{destination} {day_text} 攻略 景点",
        f"{destination} {day_text} 自由行 路线",
        f"{destination} 必去景点 攻略",
        f"{destination} 旅行 避坑 门票 预约",
    ]
    for preference in preferences:
        queries.append(f"{destination} {preference} 攻略 景点")
    return queries


def require_searchapi_key() -> str:
    api_key = os.getenv("SEARCHAPI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 SEARCHAPI_API_KEY。请在环境变量或 .env.local 中配置后重试。")
    return api_key


def search_baidu(query: str, limit: int, api_key: str) -> list[SearchResult]:
    params = urllib.parse.urlencode(
        {
            "engine": "baidu",
            "q": query,
            "api_key": api_key,
            "num": limit,
        }
    )
    data = json.loads(http_get(f"https://www.searchapi.io/api/v1/search?{params}", timeout=20))
    results: list[SearchResult] = []
    for item in data.get("organic_results", [])[:limit]:
        url = item.get("link") or item.get("url")
        if not url:
            continue
        results.append(
            SearchResult(
                title=clean_html(str(item.get("title", ""))),
                url=str(url),
                snippet=clean_html(str(item.get("snippet", ""))),
            )
        )
    return results


def search_guides(destination: str, days: int, preferences: list[str], per_query_limit: int) -> list[SearchResult]:
    api_key = require_searchapi_key()
    seen_urls: set[str] = set()
    collected: list[SearchResult] = []
    for query in build_queries(destination, days, preferences):
        try:
            results = search_baidu(query, per_query_limit, api_key)
        except Exception as exc:
            print(f"[warn] Baidu 搜索失败：query={query!r}；{exc}", file=sys.stderr)
            continue

        for result in results:
            normalized_url = result.url.split("#", 1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            collected.append(result)
        time.sleep(0.4)
    return collected


def extract_places_from_result(result: SearchResult, destination: str) -> list[str]:
    text = normalize_text(f"{result.title}。{result.snippet}")
    candidates: list[str] = []

    for suffix in PLACE_SUFFIXES:
        pattern = rf"([\u4e00-\u9fa5A-Za-z0-9·]{{2,22}}{re.escape(suffix)})"
        candidates.extend(re.findall(pattern, text))

    cleaned: list[str] = []
    for item in candidates:
        name = clean_place_name(item, destination)
        if name:
            cleaned.append(name)

    # One source contributes at most one mention per place.
    return list(dict.fromkeys(cleaned))


def clean_place_name(raw_name: str, destination: str) -> str:
    name = normalize_text(raw_name)
    name = name.strip("，。；、：:()（）[]【】<>《》“”\"' ")
    name = re.sub(r"^(中国|江苏|浙江|四川|广东|北京|上海|重庆|天津|云南|福建|广西|陕西|河南|山东|山西|湖北|湖南)", "", name)
    name = re.split(r"(?:和|与|及|以及|还有|、)", name)[-1]
    name = re.sub(r"^(上午|中午|下午|晚上|夜游|推荐|建议|可以|适合)?(去|逛|游|游玩|打卡|参观|看看)", "", name)
    name = name.strip("，。；、：:()（）[]【】<>《》“”\"' ")

    if len(name) < 2 or len(name) > 24:
        return ""
    if name in BLOCKED_EXACT_NAMES:
        return ""
    if any(part in name for part in BLOCKED_PARTS):
        return ""
    if re.fullmatch(r"\d+天\d*晚?", name):
        return ""
    return name


def build_candidate_pool(results: list[SearchResult], destination: str) -> list[CandidatePlace]:
    counts: Counter[str] = Counter()
    source_map: dict[str, list[Source]] = defaultdict(list)
    seen_source_place: set[tuple[str, str]] = set()

    for result in results:
        source = Source(title=result.title, url=result.url, snippet=result.snippet)
        source_key = result.url.split("#", 1)[0]
        for place in extract_places_from_result(result, destination):
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


def build_output(destination: str, days: int, preferences: list[str], results: list[SearchResult]) -> dict[str, object]:
    return {
        "destination": destination,
        "days": days,
        "preferences": preferences,
        "candidate_pool": [asdict(candidate) for candidate in build_candidate_pool(results, destination)],
    }


def print_human_report(output: dict[str, object]) -> None:
    destination = output["destination"]
    days = output["days"]
    candidates = output["candidate_pool"]
    print(f"\nFloatTrip 候选景点池：{destination} {chinese_days(int(days))}")
    print(f"候选景点：{len(candidates)} 个\n")
    for item in candidates[:20]:  # type: ignore[index]
        print(f"- {item['name']}｜score={item['score']}｜出现 {item['mention_count']} 次")  # type: ignore[index]


def main() -> int:
    load_local_env()

    parser = argparse.ArgumentParser(description="搜索并生成 FloatTrip 候选景点池。")
    parser.add_argument("destination", help="目的地，例如：南京")
    parser.add_argument("--days", type=int, default=3, help="旅行天数，默认 3")
    parser.add_argument("--preferences", default="", help="偏好，逗号分隔，例如：历史文化,美食")
    parser.add_argument("--per-query-limit", type=int, default=10, help="每个搜索词最多取几条结果")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    preferences = parse_preferences(args.preferences)
    try:
        results = search_guides(args.destination, args.days, preferences, args.per_query_limit)
        output = build_output(args.destination, args.days, preferences, results)
    except Exception as exc:
        print(f"候选景点池生成失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_human_report(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
