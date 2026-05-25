#!/usr/bin/env python3
"""Search Tavily, fetch result pages, and write markdown content."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import TextIO

import httpx
from bs4 import BeautifulSoup, Tag
from markdownify import markdownify
from typing_extensions import Literal


LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"
DEFAULT_OUTPUT = Path(__file__).with_name("tavily_search_results.md")
TAVILY_MAX_RESULTS = 20
MIN_CONTENT_CHARS = 200
DEFAULT_SEARCH_TIMEOUT = 20.0
DEFAULT_FETCH_TIMEOUT = 10.0
PRIORITY_SEARCH_DOMAINS = ("bendibao.com", "you.ctrip.com")
REMOVED_TAGS = {
    "aside",
    "button",
    "canvas",
    "footer",
    "form",
    "header",
    "iframe",
    "img",
    "input",
    "nav",
    "noscript",
    "picture",
    "script",
    "style",
    "svg",
    "template",
    "video",
}
NOISE_ATTR_PATTERN = re.compile(
    r"(?:^|[-_\s])("
    r"ad|ads|advert|banner|breadcrumb|comment|cookie|download|footer|header|"
    r"menu|modal|nav|pagination|popup|promo|recommend|related|share|sidebar|"
    r"social|toolbar"
    r")(?:$|[-_\s])",
    re.IGNORECASE,
)
CONTENT_SELECTOR = ",".join(
    (
        "article",
        "main",
        "[role='main']",
        "[class*='article']",
        "[id*='article']",
        "[class*='content']",
        "[id*='content']",
        "[class*='detail']",
        "[id*='detail']",
        "[class*='post']",
        "[id*='post']",
    )
)
BOILERPLATE_LINE_PATTERN = re.compile(
    r"^(?:"
    r"(?:#{1,6}\s*)?(?:更多推[荐薦]|相关推荐|相關推薦|相关推荐|"
    r"聯繫我們|联系我们|關於|关于|其他服務|其他服务|"
    r"常州周邊目的地|常州周边目的地|精選優惠|精选优惠)"
    r"|Android版|iPhone版|iPad版|查看更多|Copyright\b"
    r"|手机访问.*|精彩推荐|特别推荐|大家都爱看"
    r"|温馨提示[:：].*|閱讀原文|阅读原文"
    r"|曾在此Moment中提及|於這篇Moment中提及"
    r"|全部專業指南|全部专业指南"
    r")$",
    re.IGNORECASE,
)
URL_ONLY_LINE_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
PROMOTIONAL_LINE_PATTERN = re.compile(
    r"^(?:登入即享會員優惠|登录即享会员优惠|我希望收到最新的優惠資訊[！!]?|"
    r"我希望收到最新的优惠资讯[！!]?)$"
)


def load_local_env() -> None:
    """Load project-local environment variables without overriding the shell."""
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


load_local_env()


def get_tavily_client():
    try:
        from tavily import TavilyClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing Tavily SDK. Install it with: python3 -m pip install tavily-python"
        ) from exc

    return TavilyClient()


def fetch_webpage_content(
    url: str,
    timeout: float = 10.0,
    trust_env: bool = False,
) -> str:
    """Fetch and convert webpage content to markdown.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds
        trust_env: Whether HTTPX should read proxy and certificate environment variables

    Returns:
        Webpage content as markdown
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        )
    }

    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=timeout,
            trust_env=trust_env,
            follow_redirects=True,
        )
        response.raise_for_status()
        return html_to_clean_markdown(response.text)
    except Exception:
        return ""


def html_to_clean_markdown(html: str) -> str:
    """Extract readable page text and convert it to cleaned markdown."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(REMOVED_TAGS):
        tag.decompose()
    for tag in soup.find_all(is_noise_container):
        tag.decompose()

    content_root = choose_content_root(soup)
    if content_root is None:
        return ""

    prune_link_list_containers(content_root)
    for link in content_root.find_all("a"):
        link.unwrap()

    markdown = markdownify(str(content_root), heading_style="ATX")
    markdown = clean_markdown(markdown)
    if not has_meaningful_content(markdown):
        return ""
    return markdown


def is_noise_container(tag: Tag) -> bool:
    """Find common page-chrome and promotion containers by HTML attributes."""
    if not isinstance(tag, Tag):
        return False
    values = [tag.get("id", "")]
    classes = tag.get("class", [])
    values.extend(classes if isinstance(classes, list) else [classes])
    role = tag.get("role", "")
    aria_label = tag.get("aria-label", "")
    values.extend((role, aria_label))
    return any(NOISE_ATTR_PATTERN.search(str(value)) for value in values if value)


def choose_content_root(soup: BeautifulSoup) -> Tag | None:
    """Prefer text-heavy semantic or article-like containers over full pages."""
    candidates = [
        candidate
        for candidate in soup.select(CONTENT_SELECTOR)
        if isinstance(candidate, Tag)
    ]
    candidates.sort(key=content_score, reverse=True)
    if candidates and content_score(candidates[0]) >= MIN_CONTENT_CHARS:
        return candidates[0]

    body = soup.body
    if body and content_score(body) >= MIN_CONTENT_CHARS:
        return body
    return None


def content_score(tag: Tag) -> int:
    """Score candidate nodes by readable text volume and link density."""
    text = normalized_text(tag.get_text(" ", strip=True))
    link_text = " ".join(
        normalized_text(link.get_text(" ", strip=True)) for link in tag.find_all("a")
    )
    return len(text) - len(link_text) // 2


def prune_link_list_containers(content_root: Tag) -> None:
    """Remove navigation blocks made mostly of short link labels."""
    for tag in content_root.find_all(("div", "ol", "section", "ul")):
        links = tag.find_all("a")
        if len(links) < 3:
            continue
        text = normalized_text(tag.get_text(" ", strip=True))
        link_text = normalized_text(" ".join(link.get_text(" ", strip=True) for link in links))
        if text and len(text) <= 400 and len(link_text) / len(text) >= 0.7:
            tag.decompose()


def clean_markdown(markdown: str) -> str:
    """Remove markdown residue that should not reach the travel corpus."""
    markdown = re.sub(r"!\[[^\]]*]\([^)]*\)", "", markdown)
    markdown = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", markdown)
    markdown = re.sub(r"\n[ \t]+\n", "\n\n", markdown)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    lines = [URL_PATTERN.sub("", line) for line in markdown.splitlines()]
    lines = [line for line in lines if not PROMOTIONAL_LINE_PATTERN.match(normalized_text(line))]
    lines = [line for line in lines if not URL_ONLY_LINE_PATTERN.match(line.strip())]
    lines = trim_boilerplate_tail(lines)
    return "\n".join(lines).strip()


def trim_boilerplate_tail(lines: list[str]) -> list[str]:
    """Cut recommendation and footer sections that follow page content."""
    kept_lines = []
    kept_chars = 0
    for line in lines:
        normalized = normalized_text(line).strip("* ")
        if BOILERPLATE_LINE_PATTERN.match(normalized):
            break
        kept_lines.append(line)
        kept_chars += len(normalized)
    return kept_lines


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def has_meaningful_content(markdown: str) -> bool:
    text = re.sub(r"[#*_>`~\-\[\]()]", "", markdown)
    return len(normalized_text(text)) >= MIN_CONTENT_CHARS


def tavily_search(
    query: str,
    max_results: int = 1,
    topic: Literal["general", "news", "finance"] = "general",
    search_timeout: float = DEFAULT_SEARCH_TIMEOUT,
    fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
    progress_stream: TextIO | None = None,
) -> str:
    """Search the web for information on a given query.

    Uses Tavily to discover relevant URLs, then fetches and returns full webpage content as markdown.

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return (default: 1)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

    Returns:
        Formatted search results with full webpage content
    """
    if not 1 <= max_results <= TAVILY_MAX_RESULTS:
        raise ValueError(
            f"max_results must be between 1 and {TAVILY_MAX_RESULTS}."
        )

    # Ask Tavily for spare candidates so blocked pages can be skipped.
    report_progress(progress_stream, f"Searching Tavily for {query!r}...")
    client = get_tavily_client()
    priority_search_results = client.search(
        query,
        max_results=TAVILY_MAX_RESULTS,
        topic=topic,
        timeout=search_timeout,
        include_domains=list(PRIORITY_SEARCH_DOMAINS),
    )
    broad_search_results = client.search(
        query,
        max_results=TAVILY_MAX_RESULTS,
        topic=topic,
        timeout=search_timeout,
    )
    candidates = merge_candidates(
        priority_search_results.get("results", []),
        broad_search_results.get("results", []),
    )
    report_progress(
        progress_stream,
        f"Tavily returned {len(candidates)} candidate(s); fetching page content...",
    )

    result_texts = []
    for index, result in enumerate(candidates, start=1):
        url = result["url"]
        title = result["title"]
        report_progress(
            progress_stream,
            f"Fetching candidate {index}/{len(candidates)}: {title}",
        )
        content = fetch_webpage_content(url, timeout=fetch_timeout)

        if not has_meaningful_content(content):
            report_progress(
                progress_stream,
                f"Skipping candidate {index}/{len(candidates)}: no usable content.",
            )
            continue

        result_text = f"""## {title}
**URL:** {url}

{content}

---
"""
        result_texts.append(result_text)
        report_progress(
            progress_stream,
            f"Accepted candidate {index}/{len(candidates)} "
            f"({len(result_texts)}/{max_results}).",
        )

        if len(result_texts) == max_results:
            break

    return f"""🔍 Found {len(result_texts)} result(s) for '{query}':

{chr(10).join(result_texts)}"""


def merge_candidates(*result_groups: list[dict]) -> list[dict]:
    """Keep earlier Tavily candidate groups ahead of fallback results."""
    candidates = []
    seen_urls = set()
    for result_group in result_groups:
        for result in result_group:
            url = result["url"]
            if url in seen_urls:
                continue
            candidates.append(result)
            seen_urls.add(url)
    return candidates


def report_progress(progress_stream: TextIO | None, message: str) -> None:
    if progress_stream is not None:
        print(f"[fetch-webpage] {message}", file=progress_stream, flush=True)


def write_markdown(output_file: Path, content: str) -> None:
    output_file.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Tavily, fetch result pages, and write markdown output."
    )
    parser.add_argument("query", help="Search query to execute.")
    parser.add_argument("--max-results", type=int, default=1, help="Default: 1.")
    parser.add_argument(
        "--topic",
        choices=("general", "news", "finance"),
        default="general",
        help="Tavily topic filter. Default: general.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Markdown output path. Default: {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--search-timeout",
        type=float,
        default=DEFAULT_SEARCH_TIMEOUT,
        help=f"Tavily search timeout in seconds. Default: {DEFAULT_SEARCH_TIMEOUT:g}.",
    )
    parser.add_argument(
        "--fetch-timeout",
        type=float,
        default=DEFAULT_FETCH_TIMEOUT,
        help=f"Per-result webpage fetch timeout in seconds. Default: {DEFAULT_FETCH_TIMEOUT:g}.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    content = tavily_search(
        args.query,
        max_results=args.max_results,
        topic=args.topic,
        search_timeout=args.search_timeout,
        fetch_timeout=args.fetch_timeout,
        progress_stream=sys.stderr,
    )
    write_markdown(args.output, content)
    print(f"Markdown results written to {args.output.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    main()
