"""Web research and lightweight candidate extraction for trip planning."""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) FloatTripBackend/0.1"
)
SEARCHAPI_URL = "https://www.searchapi.io/api/v1/search"
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
LOCAL_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"
MIN_PAGE_TEXT_CHARS = 120
DEFAULT_MAX_SEARCH_RESULTS = 8
DEFAULT_MAX_CANDIDATES = 28

PLACE_SUFFIXES = (
    "风景区",
    "博物院",
    "博物馆",
    "纪念馆",
    "美术馆",
    "科技馆",
    "古城",
    "古镇",
    "古街",
    "老街",
    "步行街",
    "商业街",
    "主题乐园",
    "动物园",
    "植物园",
    "海洋馆",
    "水族馆",
    "公园",
    "景区",
    "广场",
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

STOP_WORDS = {
    "旅游攻略",
    "自由行",
    "一日游",
    "两日游",
    "三日游",
    "四日游",
    "五日游",
    "开放时间",
    "预约入口",
    "门票价格",
    "交通攻略",
    "景点推荐",
    "线路推荐",
    "上一篇",
    "下一篇",
}


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str


@dataclass(frozen=True)
class ResearchDocument:
    title: str
    url: str
    source: str
    text: str


@dataclass(frozen=True)
class ResearchBundle:
    query_plan: list[str]
    search_results: list[SearchResult]
    documents: list[ResearchDocument]
    warnings: list[str]


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[SearchResult]:
        """Search web pages for one query."""


class TextExtractor(HTMLParser):
    """Small readable-text extractor that keeps backend dependencies lean."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3", "article", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = normalize_text(data)
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


class SearchApiBaiduProvider:
    name = "searchapi_baidu"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("SEARCHAPI_API_KEY", "")

    def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self.api_key or self.api_key.startswith(("sk-", "sk_")):
            return []
        params = urllib.parse.urlencode(
            {"engine": "baidu", "q": query, "api_key": self.api_key, "num": limit}
        )
        data = json.loads(http_get(f"{SEARCHAPI_URL}?{params}", timeout=18))
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


class DuckDuckGoHtmlProvider:
    name = "duckduckgo_html"

    def search(self, query: str, limit: int) -> list[SearchResult]:
        params = urllib.parse.urlencode({"q": query})
        return parse_duckduckgo_results(http_get(f"{DUCKDUCKGO_URL}?{params}", timeout=18), limit)


def collect_research(
    destination: str,
    days: int,
    preferences: list[str],
    *,
    per_query_limit: int = 3,
    max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    max_page_chars: int = 12_000,
) -> ResearchBundle:
    """Search guide pages and fetch readable page text."""
    load_local_env()
    query_plan = build_queries(destination, days, preferences)
    providers: list[SearchProvider] = [SearchApiBaiduProvider(), DuckDuckGoHtmlProvider()]
    warnings: list[str] = []
    search_results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for query in query_plan:
        for provider in providers:
            try:
                results = provider.search(query, per_query_limit)
            except Exception as exc:
                warnings.append(f"{provider.name} 搜索失败：{exc}")
                continue
            for result in results:
                normalized_url = result.url.split("#", 1)[0]
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                search_results.append(result)
                if len(search_results) >= max_results:
                    break
            if len(search_results) >= max_results:
                break
        if len(search_results) >= max_results:
            break
        time.sleep(0.2)

    documents: list[ResearchDocument] = []
    for result in search_results:
        try:
            page_text = fetch_page_text(result.url, max_chars=max_page_chars)
        except Exception as exc:
            warnings.append(f"抓取失败：{result.url}；{exc}")
            continue
        merged_text = normalize_text(f"{result.title}。{result.snippet}。{page_text}")
        if len(merged_text) < MIN_PAGE_TEXT_CHARS:
            warnings.append(f"跳过内容过短页面：{result.url}")
            continue
        documents.append(
            ResearchDocument(
                title=result.title,
                url=result.url,
                source=result.source,
                text=merged_text,
            )
        )

    return ResearchBundle(
        query_plan=query_plan,
        search_results=search_results,
        documents=documents,
        warnings=warnings,
    )


def extract_candidate_pool(
    bundle: ResearchBundle,
    destination: str,
    preferences: list[str],
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> list[dict[str, object]]:
    """Create a ranked attraction pool from researched guide documents."""
    occurrence_counter: Counter[str] = Counter()
    source_map: dict[str, list[dict[str, str]]] = {}
    preference_set = {normalize_text(item) for item in preferences if normalize_text(item)}

    for document in bundle.documents:
        names = extract_place_names(document.text, destination)
        occurrence_counter.update(names)
        for name in set(names):
            source_map.setdefault(name, []).append(
                {"title": document.title, "url": document.url, "source": document.source}
            )

    candidates: list[dict[str, object]] = []
    for name, mention_count in occurrence_counter.most_common(max_candidates * 2):
        preference_score = score_preference_match(name, bundle.documents, preference_set)
        candidates.append(
            {
                "name": name,
                "mention_count": mention_count,
                "preference_score": preference_score,
                "score": mention_count * 10 + preference_score,
                "sources": source_map.get(name, [])[:4],
            }
        )

    return candidates[:max_candidates]


def extract_place_names(text: str, destination: str) -> list[str]:
    names: list[str] = []
    for suffix in PLACE_SUFFIXES:
        pattern = rf"([\u4e00-\u9fa5A-Za-z0-9·]{{2,18}}{re.escape(suffix)})"
        names.extend(re.findall(pattern, text))

    cleaned: list[str] = []
    for name in names:
        normalized = clean_place_name(name, destination)
        if normalized:
            cleaned.append(normalized)
    return cleaned


def clean_place_name(name: str, destination: str) -> str:
    value = normalize_text(name).strip("，。；、：:()（）[]【】 ")
    value = re.sub(rf"^{re.escape(destination)}市?", "", value)
    if len(value) < 2 or len(value) > 18:
        return ""
    if any(word in value for word in STOP_WORDS):
        return ""
    if re.search(r"(酒店|民宿|机场|车站|地铁站|餐厅|饭店|小吃|美食|门票|预约|时间)", value):
        return ""
    return value


def score_preference_match(
    name: str,
    documents: list[ResearchDocument],
    preference_set: set[str],
) -> int:
    if not preference_set:
        return 0
    contexts = [
        document.text[max(0, document.text.find(name) - 80) : document.text.find(name) + 120]
        for document in documents
        if name in document.text
    ]
    context = " ".join(contexts)
    return min(10, sum(2 for preference in preference_set if preference and preference in context))


def build_queries(destination: str, days: int, preferences: list[str]) -> list[str]:
    day_text = chinese_days(days)
    pref_text = " ".join(preferences)
    queries = [
        f"{destination} {day_text} 攻略 景点",
        f"{destination} {days}天{max(days - 1, 1)}晚 自由行 路线",
        f"{destination} {day_text} 行程安排",
        f"{destination} 旅行 避坑 预约 门票",
    ]
    if pref_text:
        queries.insert(1, f"{destination} {day_text} {pref_text} 攻略")
    return queries


def chinese_days(days: int) -> str:
    mapping = {1: "一日游", 2: "两日游", 3: "三日游", 4: "四日游", 5: "五日游", 6: "六日游", 7: "七日游"}
    return mapping.get(days, f"{days}日游")


def fetch_page_text(url: str, *, max_chars: int) -> str:
    extractor = TextExtractor()
    extractor.feed(http_get(url, timeout=18))
    return extractor.text()[:max_chars]


def http_get(url: str, timeout: int = 18) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:
            last_error = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"请求失败：{redact_url(url)}；原因：{last_error}")


def parse_duckduckgo_results(raw_html: str, limit: int) -> list[SearchResult]:
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="(?P<url>.*?)".*?>(?P<title>.*?)</a>.*?'
        r'<a class="result__snippet".*?>(?P<snippet>.*?)</a>',
        raw_html,
        flags=re.S,
    )
    results: list[SearchResult] = []
    for raw_url, raw_title, raw_snippet in blocks[:limit]:
        url = html.unescape(raw_url)
        if "uddg=" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
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


def clean_html(value: str) -> str:
    return normalize_text(html.unescape(re.sub(r"<[^>]+>", "", value)))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for secret_key in ("api_key", "key", "access_token", "token"):
        if secret_key in query:
            query[secret_key] = ["<redacted>"]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


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
