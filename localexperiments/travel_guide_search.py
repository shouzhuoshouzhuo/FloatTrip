#!/usr/bin/env python3
"""
FloatTrip travel guide search prototype.

Goal:
1. Expand a user's travel need into search queries.
2. Search broad web travel guides.
3. Fetch candidate pages.
4. Extract places, routes, food mentions, and tips into structured data.

This prototype uses only Python standard library. It includes:
- DuckDuckGo HTML search as a no-key local prototype.
- SearchApi.io Baidu provider hook for later production-style search.

Example:
  python3 tools/travel_guide_search.py 南京 --days 3 --preferences 历史文化,美食,轻松
  python3 tools/travel_guide_search.py 南京 --days 3 --json
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
from collections import Counter
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripGuideSearch/0.1"
)
DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseekv4flash"
LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"

PLACE_SUFFIXES = (
    "古镇",
    "古街",
    "步行街",
    "商业街",
    "夜市",
    "公园",
    "景区",
    "风景区",
    "广场",
    "大学",
    "寺",
    "庙",
    "陵",
    "湖",
    "山",
    "街",
    "巷",
    "园",
    "府",
)

DIRECT_PLACE_NAMES = (
    "南京博物院",
    "南京博物馆",
    "总统府",
    "夫子庙",
    "秦淮河",
    "老门东",
    "中山陵",
    "明孝陵",
    "玄武湖",
    "鸡鸣寺",
    "明城墙",
    "南京城墙",
    "红山森林动物园",
    "红山动物园",
    "侵华日军南京大屠杀遇难同胞纪念馆",
    "大报恩寺",
    "牛首山",
    "栖霞山",
    "雨花台",
    "新街口",
    "颐和路",
    "先锋书店",
    "美龄宫",
    "音乐台",
    "灵谷寺",
    "阅江楼",
    "莫愁湖",
    "瞻园",
    "朝天宫",
    "南京大学",
    "钟山风景区",
)

TIP_KEYWORDS = (
    "预约",
    "排队",
    "闭馆",
    "门票",
    "免费",
    "地铁",
    "打车",
    "晚上",
    "夜景",
    "避坑",
    "建议",
    "提前",
    "开放时间",
)

FOOD_KEYWORDS = (
    "鸭血粉丝汤",
    "盐水鸭",
    "小笼包",
    "锅贴",
    "牛肉锅贴",
    "皮肚面",
    "梅花糕",
    "桂花糖芋苗",
    "赤豆元宵",
    "汤包",
    "糕团",
    "茶颜",
    "咖啡",
    "餐厅",
    "小吃",
    "美食",
)

FOOD_SHOP_SUFFIXES = (
    "餐厅",
    "饭店",
    "面馆",
    "汤包店",
    "锅贴店",
    "鸭血粉丝店",
    "咖啡",
    "茶社",
)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str


@dataclass(frozen=True)
class TravelFacts:
    source_url: str
    source_title: str
    mentioned_places: list[str]
    food_mentions: list[str]
    route_candidates: list[list[str]]
    tips: list[str]


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[SearchResult]:
        ...


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


class DuckDuckGoHtmlProvider:
    name = "duckduckgo_html"

    def search(self, query: str, limit: int) -> list[SearchResult]:
        params = urllib.parse.urlencode({"q": query})
        url = f"https://html.duckduckgo.com/html/?{params}"
        raw_html = http_get(url, timeout=20)
        return parse_duckduckgo_results(raw_html, limit)


class SearchApiBaiduProvider:
    """
    Optional production-style provider.

    Set SEARCHAPI_API_KEY to enable:
      https://www.searchapi.io/baidu
    """

    name = "searchapi_baidu"

    def __init__(self) -> None:
        self.api_key = os.getenv("SEARCHAPI_API_KEY")

    def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self.api_key or self.api_key.startswith(("sk-", "sk_")):
            return []
        params = urllib.parse.urlencode(
            {
                "engine": "baidu",
                "q": query,
                "api_key": self.api_key,
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
                    title=clean_html(item.get("title", "")),
                    url=url,
                    snippet=clean_html(item.get("snippet", "")),
                    source=self.name,
                )
            )
        return results


def http_get(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
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
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"请求失败：{redact_url(url)}；原因：{last_error}")


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for secret_key in ("api_key", "key", "access_token", "token"):
        if secret_key in query:
            query[secret_key] = ["<redacted>"]
    redacted_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=redacted_query))


def clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return normalize_text(html.unescape(value))


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


def parse_duckduckgo_results(raw_html: str, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="(?P<url>.*?)".*?>(?P<title>.*?)</a>.*?'
        r'<a class="result__snippet".*?>(?P<snippet>.*?)</a>',
        raw_html,
        flags=re.S,
    )
    for raw_url, raw_title, raw_snippet in blocks[:limit]:
        url = html.unescape(raw_url)
        if "uddg=" in url:
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query)
            url = query.get("uddg", [url])[0]
        results.append(
            SearchResult(
                title=clean_html(raw_title),
                url=url,
                snippet=clean_html(raw_snippet),
                source="duckduckgo_html",
            )
        )
    return results


def build_queries(destination: str, days: int, preferences: list[str]) -> list[str]:
    day_text = chinese_days(days)
    pref_text = " ".join(preferences)
    base_queries = [
        f"{destination} {day_text} 攻略",
        f"{destination} {days}天{max(days - 1, 1)}晚 自由行 路线",
        f"{destination} {day_text} 行程安排 景点",
        f"{destination} {day_text} 美食 攻略",
        f"小红书 {destination} {day_text} 攻略",
        f"{destination} 旅行 避坑 预约 门票",
    ]
    if pref_text:
        base_queries.insert(2, f"{destination} {day_text} {pref_text} 攻略")
    return base_queries


def chinese_days(days: int) -> str:
    mapping = {1: "一日游", 2: "两日游", 3: "三日游", 4: "四日游", 5: "五日游", 6: "六日游", 7: "七日游"}
    return mapping.get(days, f"{days}日游")


def search_guides(
    destination: str,
    days: int,
    preferences: list[str],
    per_query_limit: int,
) -> list[SearchResult]:
    providers: list[SearchProvider] = [SearchApiBaiduProvider(), DuckDuckGoHtmlProvider()]
    seen: set[str] = set()
    collected: list[SearchResult] = []
    for query in build_queries(destination, days, preferences):
        for provider in providers:
            try:
                results = provider.search(query, per_query_limit)
            except Exception as exc:
                print(f"[warn] {provider.name} 搜索失败：{exc}", file=sys.stderr)
                continue
            for result in results:
                normalized_url = result.url.split("#", 1)[0]
                if normalized_url in seen:
                    continue
                seen.add(normalized_url)
                collected.append(result)
        time.sleep(0.6)
    return collected


def fetch_page_text(url: str, max_chars: int) -> str:
    raw = http_get(url, timeout=18)
    extractor = TextExtractor()
    extractor.feed(raw)
    return extractor.text()[:max_chars]


def extract_travel_facts(result: SearchResult, page_text: str, destination: str) -> TravelFacts:
    merged_text = normalize_text(f"{result.title}。{result.snippet}。{page_text}")
    places = extract_places(merged_text, destination)
    return TravelFacts(
        source_url=result.url,
        source_title=result.title,
        mentioned_places=places,
        food_mentions=extract_food_mentions(merged_text),
        route_candidates=extract_routes(merged_text, places),
        tips=extract_tips(merged_text),
    )


def extract_travel_facts_with_deepseek(
    result: SearchResult,
    page_text: str,
    destination: str,
    days: int,
    preferences: list[str],
    model: str,
) -> TravelFacts:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")

    prompt = f"""
你是 FloatTrip 的旅行攻略信息抽取器。
请从网页内容里抽取可用于生成 {destination} {days} 天游的结构化信息。

用户偏好：{", ".join(preferences) if preferences else "无"}

只返回 JSON，不要解释。JSON 字段必须是：
{{
  "mentioned_places": ["地点名"],
  "food_mentions": ["美食或餐厅"],
  "route_candidates": [["地点1", "地点2", "地点3"]],
  "tips": ["预约、闭馆、门票、交通、避坑等短提示"]
}}

要求：
- 地点名要短而干净，例如“南京博物院”“总统府”“夫子庙秦淮河”。
- 不要把“周一闭馆”“开放时间”“预约入口”当成地点或美食。
- 路线候选要按游玩顺序排列。
- 如果信息不足，返回空数组。

网页标题：
{result.title}

网页摘要：
{result.snippet}

网页正文：
{page_text[:10000]}
""".strip()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出严格 JSON。"},
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

    with urllib.request.urlopen(request, timeout=60) as response:
        response_body = response.read().decode("utf-8")
    completion = json.loads(response_body)
    content = completion["choices"][0]["message"]["content"]
    extracted = parse_json_object(content)

    return TravelFacts(
        source_url=result.url,
        source_title=result.title,
        mentioned_places=clean_string_list(extracted.get("mentioned_places", []), limit=30),
        food_mentions=clean_string_list(extracted.get("food_mentions", []), limit=20),
        route_candidates=clean_route_candidates(extracted.get("route_candidates", [])),
        tips=clean_string_list(extracted.get("tips", []), limit=15),
    )


def parse_json_object(content: str) -> dict[str, object]:
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


def clean_string_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = normalize_text(item).strip("，。；、：:()（）[]【】 ")
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result[:limit]


def clean_route_candidates(value: object) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    routes: list[list[str]] = []
    for route in value:
        if not isinstance(route, list):
            continue
        cleaned_route = clean_string_list(route, limit=10)
        if len(cleaned_route) >= 2:
            routes.append(cleaned_route)
    return routes[:10]


def extract_places(text: str, destination: str) -> list[str]:
    candidates: list[str] = []
    candidates.extend(name for name in DIRECT_PLACE_NAMES if name in text)

    for suffix in PLACE_SUFFIXES:
        pattern = rf"([\u4e00-\u9fa5A-Za-z0-9·]{2,18}{re.escape(suffix)})"
        candidates.extend(re.findall(pattern, text))

    cleaned: list[str] = []
    stop_words = {
        "南京旅游攻略",
        "南京三日游",
        "南京自由行",
        "小红书",
        "上一篇",
        "下一篇",
        "开放时间",
        "重要提示",
        "预约入口",
    }
    for item in candidates:
        item = item.strip("，。；、：:()（）[]【】 ")
        item = re.sub(rf"^{re.escape(destination)}市?", "", item)
        if len(item) < 2 or item in stop_words or any(word in item for word in stop_words):
            continue
        cleaned.append(item)

    counts = Counter(cleaned)
    return [name for name, _count in counts.most_common(20)]


def extract_food_mentions(text: str) -> list[str]:
    mentions = [keyword for keyword in FOOD_KEYWORDS if keyword in text]
    for suffix in FOOD_SHOP_SUFFIXES:
        shop_pattern = rf"([\u4e00-\u9fa5A-Za-z0-9·]{{2,16}}{re.escape(suffix)})"
        mentions.extend(re.findall(shop_pattern, text))

    blocked_words = {"闭馆", "纪念馆", "博物馆", "美术馆", "科技馆", "总店", "入馆", "书店"}
    counts = Counter(
        item.strip()
        for item in mentions
        if len(item.strip()) >= 2 and not any(word in item for word in blocked_words)
    )
    return [name for name, _count in counts.most_common(15)]


def extract_routes(text: str, known_places: list[str]) -> list[list[str]]:
    routes: list[list[str]] = []
    route_separators = r"(?:->|→|—|-|－|~|～|到|再到|然后|下午|晚上|上午)"

    for sentence in split_sentences(text):
        if not any(token in sentence for token in ("路线", "行程", "Day", "D1", "第一天", "上午", "下午", "晚上", "→", "->")):
            continue
        matched = [place for place in known_places if place in sentence]
        if len(matched) >= 2:
            ordered = sort_by_sentence_position(sentence, matched)
            routes.append(ordered[:8])
            continue
        parts = [part.strip() for part in re.split(route_separators, sentence)]
        place_like = [part for part in parts if any(suffix in part for suffix in PLACE_SUFFIXES)]
        if len(place_like) >= 2:
            routes.append(place_like[:8])

    deduped: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for route in routes:
        key = tuple(route)
        if key not in seen:
            seen.add(key)
            deduped.append(route)
    return deduped[:8]


def split_sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[。！？\n\r]+", text) if item.strip()]


def sort_by_sentence_position(sentence: str, places: list[str]) -> list[str]:
    return sorted(set(places), key=lambda place: sentence.find(place))


def extract_tips(text: str) -> list[str]:
    tips: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) > 120:
            continue
        if any(keyword in sentence for keyword in TIP_KEYWORDS):
            tips.append(sentence)
    return list(dict.fromkeys(tips))[:12]


def aggregate(facts: list[TravelFacts]) -> dict[str, object]:
    place_counter: Counter[str] = Counter()
    food_counter: Counter[str] = Counter()
    tip_counter: Counter[str] = Counter()
    routes: list[list[str]] = []

    for fact in facts:
        place_counter.update(fact.mentioned_places)
        food_counter.update(fact.food_mentions)
        tip_counter.update(fact.tips)
        routes.extend(fact.route_candidates)

    return {
        "top_places": [
            {"name": name, "mentions": count}
            for name, count in place_counter.most_common(20)
        ],
        "top_foods": [
            {"name": name, "mentions": count}
            for name, count in food_counter.most_common(15)
        ],
        "route_candidates": routes[:10],
        "tips": [tip for tip, _count in tip_counter.most_common(12)],
    }


def print_human_report(
    destination: str,
    days: int,
    results: list[SearchResult],
    facts: list[TravelFacts],
    summary: dict[str, object],
) -> None:
    print(f"\nFloatTrip 攻略搜索原型：{destination} {chinese_days(days)}")
    print(f"搜索结果：{len(results)} 条，成功抽取：{len(facts)} 篇\n")

    print("## 高频地点")
    for item in summary["top_places"][:12]:  # type: ignore[index]
        print(f"- {item['name']}｜出现 {item['mentions']} 次")  # type: ignore[index]

    print("\n## 高频美食/餐饮")
    for item in summary["top_foods"][:10]:  # type: ignore[index]
        print(f"- {item['name']}｜出现 {item['mentions']} 次")  # type: ignore[index]

    print("\n## 路线候选")
    for index, route in enumerate(summary["route_candidates"][:5], start=1):  # type: ignore[index]
        print(f"{index}. {' -> '.join(route)}")

    print("\n## 攻略提示")
    for tip in summary["tips"][:8]:  # type: ignore[index]
        print(f"- {tip}")

    print("\n## 来源")
    for result in results[:8]:
        print(f"- {result.title}｜{result.url}")


def parse_preferences(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> int:
    load_local_env()

    parser = argparse.ArgumentParser(description="搜索并抽取目的地旅行攻略信息。")
    parser.add_argument("destination", help="目的地，例如：南京")
    parser.add_argument("--days", type=int, default=3, help="旅行天数，默认 3")
    parser.add_argument("--preferences", default="", help="偏好，逗号分隔，例如：历史文化,美食,轻松")
    parser.add_argument("--per-query-limit", type=int, default=4, help="每个搜索词最多取几条结果")
    parser.add_argument("--max-pages", type=int, default=8, help="最多抓取几篇攻略正文")
    parser.add_argument("--max-page-chars", type=int, default=12000, help="每篇正文最多抽取字符数")
    parser.add_argument("--llm", action="store_true", help="使用 DeepSeek 做攻略信息抽取")
    parser.add_argument(
        "--deepseek-model",
        default=os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        help=f"DeepSeek 模型名，默认 {DEFAULT_DEEPSEEK_MODEL}",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    preferences = parse_preferences(args.preferences)
    try:
        results = search_guides(args.destination, args.days, preferences, args.per_query_limit)
        facts: list[TravelFacts] = []
        for result in results[: args.max_pages]:
            try:
                page_text = fetch_page_text(result.url, args.max_page_chars)
                if args.llm:
                    try:
                        facts.append(
                            extract_travel_facts_with_deepseek(
                                result,
                                page_text,
                                args.destination,
                                args.days,
                                preferences,
                                args.deepseek_model,
                            )
                        )
                    except Exception as exc:
                        print(f"[warn] DeepSeek 抽取失败，改用规则抽取：{exc}", file=sys.stderr)
                        facts.append(extract_travel_facts(result, page_text, args.destination))
                else:
                    facts.append(extract_travel_facts(result, page_text, args.destination))
            except Exception as exc:
                print(f"[warn] 抓取失败：{result.url}；{exc}", file=sys.stderr)
            time.sleep(0.7)

        summary = aggregate(facts)
    except Exception as exc:
        print(f"攻略搜索失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "destination": args.destination,
                    "days": args.days,
                    "preferences": preferences,
                    "search_results": [asdict(result) for result in results],
                    "facts": [asdict(fact) for fact in facts],
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_human_report(args.destination, args.days, results, facts, summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
