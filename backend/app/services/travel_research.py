"""网页搜索、markdown 提纯和 DeepSeek 热门候选景点池 Agent 服务。"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, Field


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) FloatTripBackend/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_SEARCH_RESULTS = 8
DEFAULT_MAX_CANDIDATES = 28
DEFAULT_MAX_MARKDOWN_CHARS = 60_000
DEFAULT_MAX_SEARCH_ITERATIONS = 3
TAVILY_MAX_RESULTS = 20
MIN_MARKDOWN_CHARS = 200
DEFAULT_SEARCH_TIMEOUT = 20.0
DEFAULT_FETCH_TIMEOUT = 10.0
PRIORITY_SEARCH_DOMAINS = ("bendibao.com", "you.ctrip.com")
HTTP_PROXY_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")

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
    r"(?:#{1,6}\s*)?(?:更多推[荐薦]|相关推荐|相關推薦|"
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
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
URL_ONLY_LINE_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)
PROMOTIONAL_LINE_PATTERN = re.compile(
    r"^(?:登入即享會員優惠|登录即享会员优惠|我希望收到最新的優惠資訊[！!]?|"
    r"我希望收到最新的优惠资讯[！!]?)$"
)


@dataclass(frozen=True)
class SearchResult:
    """单条 Tavily 搜索结果。"""

    title: str
    url: str
    snippet: str
    source: str


@dataclass(frozen=True)
class ResearchDocument:
    """已清噪并转成 markdown 的攻略网页。"""

    title: str
    url: str
    source: str
    text: str


@dataclass(frozen=True)
class ResearchBundle:
    """一次搜索调研得到的查询、搜索结果、markdown 文档和警告。"""

    query_plan: list[str]
    search_results: list[SearchResult]
    documents: list[ResearchDocument]
    warnings: list[str]


@dataclass(frozen=True)
class CandidatePoolGenerationResult:
    """候选景点池 Agent 的完整输出。"""

    research_bundle: ResearchBundle
    candidates: list[dict[str, object]]


class SearchQueryPlan(BaseModel):
    """DeepSeek 为候选景点池调研生成的多搜索词计划。"""

    queries: list[str] = Field(
        description="用于搜索目的地热门景点、必去景点、攻略路线和偏好玩法的多条中文搜索词"
    )


class AttractionCandidate(BaseModel):
    """DeepSeek 从 markdown 中识别出的候选景点。"""

    name: str = Field(description="合并别名后的标准景点中文名")
    preference_score: int = Field(
        ge=0,
        le=10,
        description="该景点与用户偏好的符合分，0 表示不符合，10 表示非常符合",
    )


class RankedAttractionCandidate(AttractionCandidate):
    """补充代码统计名称总出现次数后的候选景点。"""

    mention_count: int = Field(ge=1, description="景点名称在 markdown 攻略中的总出现次数")


class CandidatePool(BaseModel):
    """DeepSeek 结构化输出的候选景点池。"""

    candidate_pool: list[AttractionCandidate] = Field(description="候选景点池")


class RankedCandidatePool(BaseModel):
    """排序后的候选景点池。"""

    candidate_pool: list[RankedAttractionCandidate] = Field(description="排序后的候选景点池")


class CandidatePoolState(TypedDict, total=False):
    """LangGraph 热门候选景点池 Agent 状态。"""

    destination: str
    days: int
    query_plan: list[str]
    pending_search_queries: list[str]
    searched_queries: list[str]
    search_iterations: int
    research_bundle: ResearchBundle
    markdown_guides: str
    markdown_documents: list[str]
    preferences: list[str]
    max_candidates: int
    candidate_pool: CandidatePool
    ranked_candidate_pool: RankedCandidatePool


def collect_research(
    destination: str,
    days: int,
    preferences: list[str],
    *,
    per_query_limit: int = 3,
    max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    max_page_chars: int = 12_000,
) -> ResearchBundle:
    """功能：用 Tavily 搜索攻略网页，并将可用页面提纯为 markdown。

    参数：
        destination：目的地名称。
        days：旅行天数，用于生成搜索词。
        preferences：用户偏好，用于生成搜索词。
        per_query_limit：每个搜索词最多接受的页面数量。
        max_results：整体最多接受的搜索结果数量。
        max_page_chars：每篇 markdown 最多保留字符数。
    返回值：
        返回搜索词、搜索结果、markdown 攻略文档和抓取警告。
    """
    load_local_env()
    if not 1 <= max_results <= TAVILY_MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {TAVILY_MAX_RESULTS}.")

    query_plan = build_queries(destination, days, preferences)
    return collect_research_for_queries(
        query_plan,
        per_query_limit=per_query_limit,
        max_results=max_results,
        max_page_chars=max_page_chars,
    )


def collect_research_for_queries(
    query_plan: list[str],
    *,
    per_query_limit: int = 3,
    max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    max_page_chars: int = 12_000,
) -> ResearchBundle:
    """功能：按给定多 query 调用 Tavily 搜索攻略网页，并提纯为 markdown。

    参数：
        query_plan：候选景点池 Agent 生成并归一化后的搜索词列表。
        per_query_limit：每个搜索词最多接受的页面数量。
        max_results：整体最多接受的搜索结果数量。
        max_page_chars：每篇 markdown 最多保留字符数。
    返回值：
        返回搜索词、搜索结果、markdown 攻略文档和抓取警告。
    """
    load_local_env()
    if not 1 <= max_results <= TAVILY_MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {TAVILY_MAX_RESULTS}.")

    if not query_plan:
        raise RuntimeError("候选景点池 Agent 没有生成可用搜索词")

    warnings: list[str] = []
    search_results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for query in query_plan:
        results = tavily_search_results(query, max_results=TAVILY_MAX_RESULTS)
        accepted_for_query = 0
        for result in results:
            normalized_url = result.url.split("#", 1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            search_results.append(result)
            accepted_for_query += 1
            if len(search_results) >= max_results or accepted_for_query >= per_query_limit:
                break
        if len(search_results) >= max_results:
            break
        time.sleep(0.2)

    documents: list[ResearchDocument] = []
    for result in search_results:
        try:
            markdown = fetch_webpage_markdown(result.url, timeout=DEFAULT_FETCH_TIMEOUT)
        except Exception as exc:
            warnings.append(f"抓取失败：{result.url}；{exc}")
            continue
        if not has_meaningful_content(markdown):
            warnings.append(f"跳过内容过短页面：{result.url}")
            continue
        merged_markdown = f"## {result.title}\n\n**URL:** {result.url}\n\n{markdown}".strip()
        documents.append(
            ResearchDocument(
                title=result.title,
                url=result.url,
                source=result.source,
                text=merged_markdown[:max_page_chars],
            )
        )

    if not documents:
        raise RuntimeError("Tavily 搜索后没有抓取到可用 markdown 攻略内容")

    return ResearchBundle(
        query_plan=query_plan,
        search_results=search_results,
        documents=documents,
        warnings=warnings,
    )


def search_markdown_research_tool(
    query_plan: list[str],
    *,
    existing_bundle: ResearchBundle | None = None,
    per_query_limit: int = 3,
    max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    max_page_chars: int = 12_000,
) -> ResearchBundle:
    """功能：供候选池 Agent 调用的真实搜索工具，统一完成搜索、抓取、清噪和结果合并。

    参数：
        query_plan：本轮要执行的搜索词列表。
        existing_bundle：已有调研结果；传入时会按 URL 合并去重。
        per_query_limit：每个搜索词最多接受的页面数量。
        max_results：合并后整体最多接受的搜索结果数量。
        max_page_chars：每篇 markdown 最多保留字符数。
    返回值：
        返回合并后的搜索词、搜索结果、markdown 文档和警告。
    """
    previous = existing_bundle or ResearchBundle(
        query_plan=[],
        search_results=[],
        documents=[],
        warnings=[],
    )
    remaining_results = max_results - len(previous.search_results)
    if remaining_results <= 0 or not query_plan:
        return previous

    try:
        new_bundle = collect_research_for_queries(
            query_plan,
            per_query_limit=per_query_limit,
            max_results=remaining_results,
            max_page_chars=max_page_chars,
        )
    except RuntimeError as exc:
        if previous.documents:
            return ResearchBundle(
                query_plan=dedupe_preserve_order([*previous.query_plan, *query_plan]),
                search_results=previous.search_results,
                documents=previous.documents,
                warnings=[*previous.warnings, f"补充搜索未获得可用 markdown：{exc}"],
            )
        raise
    return merge_research_bundles(previous, new_bundle, max_results=max_results)


def merge_research_bundles(
    base_bundle: ResearchBundle,
    new_bundle: ResearchBundle,
    *,
    max_results: int,
) -> ResearchBundle:
    """功能：合并多轮搜索调研结果，并按 URL 对搜索结果和文档去重。

    参数：
        base_bundle：上一轮累计调研结果。
        new_bundle：本轮搜索工具返回的调研结果。
        max_results：合并后最多保留的搜索结果数量。
    返回值：
        返回合并后的 ResearchBundle。
    """
    query_plan = dedupe_preserve_order([*base_bundle.query_plan, *new_bundle.query_plan])
    search_results: list[SearchResult] = []
    seen_result_urls: set[str] = set()
    for result in [*base_bundle.search_results, *new_bundle.search_results]:
        normalized_url = result.url.split("#", 1)[0]
        if normalized_url in seen_result_urls:
            continue
        search_results.append(result)
        seen_result_urls.add(normalized_url)
        if len(search_results) >= max_results:
            break

    documents: list[ResearchDocument] = []
    seen_document_urls: set[str] = set()
    for document in [*base_bundle.documents, *new_bundle.documents]:
        normalized_url = document.url.split("#", 1)[0]
        if normalized_url in seen_document_urls:
            continue
        documents.append(document)
        seen_document_urls.add(normalized_url)

    return ResearchBundle(
        query_plan=query_plan,
        search_results=search_results,
        documents=documents,
        warnings=[*base_bundle.warnings, *new_bundle.warnings],
    )


def tavily_search_results(query: str, max_results: int) -> list[SearchResult]:
    """功能：调用 Tavily 搜索并合并优先域名与全网结果。

    参数：
        query：搜索词。
        max_results：最多返回的候选搜索结果数量。
    返回值：
        返回去重后的 SearchResult 列表。
    """
    try:
        from tavily import TavilyClient
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 tavily-python。请先安装后端依赖。") from exc

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 TAVILY_API_KEY。请在环境变量或 .env.local 中配置后重试。")

    try:
        client = TavilyClient(api_key=api_key)
        priority_results = client.search(
            query,
            max_results=max_results,
            topic="general",
            timeout=DEFAULT_SEARCH_TIMEOUT,
            include_domains=list(PRIORITY_SEARCH_DOMAINS),
        )
        broad_results = client.search(
            query,
            max_results=max_results,
            topic="general",
            timeout=DEFAULT_SEARCH_TIMEOUT,
        )
    except Exception as exc:
        raise RuntimeError(f"Tavily 搜索失败：{exc}") from exc

    return merge_tavily_candidates(
        query,
        priority_results.get("results", []),
        broad_results.get("results", []),
    )[:max_results]


def merge_tavily_candidates(query: str, *result_groups: list[dict[str, Any]]) -> list[SearchResult]:
    """功能：合并 Tavily 候选结果并按 URL 去重。

    参数：
        query：原始搜索词，用于缺失标题时兜底。
        result_groups：Tavily 返回的结果数组。
    返回值：
        返回去重后的 SearchResult 列表。
    """
    candidates: list[SearchResult] = []
    seen_urls: set[str] = set()
    for result_group in result_groups:
        for result in result_group:
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(
                SearchResult(
                    title=str(result.get("title") or query),
                    url=url,
                    snippet=str(result.get("content") or result.get("snippet") or ""),
                    source="tavily",
                )
            )
    return candidates


def fetch_webpage_markdown(
    url: str,
    timeout: float = DEFAULT_FETCH_TIMEOUT,
    trust_env: bool = False,
) -> str:
    """功能：抓取网页 HTML 并转换成去噪 markdown。

    参数：
        url：网页 URL。
        timeout：请求超时时间，单位秒。
        trust_env：httpx 是否读取代理和证书环境变量。
    返回值：
        返回清噪后的 markdown；失败时返回空字符串。
    """
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx。请先安装后端依赖。") from exc

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    response = httpx.get(
        url,
        headers=headers,
        timeout=timeout,
        trust_env=trust_env,
        follow_redirects=True,
    )
    response.raise_for_status()
    return html_to_clean_markdown(response.text)


def html_to_clean_markdown(html: str) -> str:
    """功能：从 HTML 中选择正文区域并转换成清噪 markdown。

    参数：
        html：原始网页 HTML。
    返回值：
        返回清噪 markdown；正文不足时返回空字符串。
    """
    try:
        from bs4 import BeautifulSoup, Tag
        from markdownify import markdownify
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 beautifulsoup4 或 markdownify。请先安装后端依赖。") from exc

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(REMOVED_TAGS):
        tag.decompose()
    for tag in soup.find_all(lambda item: isinstance(item, Tag) and is_noise_container(item)):
        tag.decompose()

    content_root = choose_content_root(soup)
    if content_root is None:
        return ""

    prune_link_list_containers(content_root)
    for link in content_root.find_all("a"):
        link.unwrap()

    markdown = markdownify(str(content_root), heading_style="ATX")
    markdown = clean_markdown(markdown)
    return markdown if has_meaningful_content(markdown) else ""


def is_noise_container(tag: Any) -> bool:
    """功能：通过节点属性识别常见页面噪声容器。

    参数：
        tag：BeautifulSoup 节点。
    返回值：
        如果节点疑似广告、导航、推荐等噪声容器则返回 True。
    """
    values = [tag.get("id", "")]
    classes = tag.get("class", [])
    values.extend(classes if isinstance(classes, list) else [classes])
    values.extend((tag.get("role", ""), tag.get("aria-label", "")))
    return any(NOISE_ATTR_PATTERN.search(str(value)) for value in values if value)


def choose_content_root(soup: Any) -> Any | None:
    """功能：从网页中选择最像正文的容器。

    参数：
        soup：BeautifulSoup 文档。
    返回值：
        返回正文节点；没有足够正文时返回 None。
    """
    candidates = list(soup.select(CONTENT_SELECTOR))
    candidates.sort(key=content_score, reverse=True)
    if candidates and content_score(candidates[0]) >= MIN_MARKDOWN_CHARS:
        return candidates[0]

    body = soup.body
    if body and content_score(body) >= MIN_MARKDOWN_CHARS:
        return body
    return None


def content_score(tag: Any) -> int:
    """功能：按正文文本量和链接密度给候选容器打分。

    参数：
        tag：BeautifulSoup 节点。
    返回值：
        返回可读文本分数。
    """
    text = normalize_text(tag.get_text(" ", strip=True))
    link_text = " ".join(
        normalize_text(link.get_text(" ", strip=True)) for link in tag.find_all("a")
    )
    return len(text) - len(link_text) // 2


def prune_link_list_containers(content_root: Any) -> None:
    """功能：删除正文内部疑似链接列表的推荐/导航块。

    参数：
        content_root：正文根节点，会被原地清理。
    返回值：
        无。
    """
    for tag in content_root.find_all(("div", "ol", "section", "ul")):
        links = tag.find_all("a")
        if len(links) < 3:
            continue
        text = normalize_text(tag.get_text(" ", strip=True))
        link_text = normalize_text(" ".join(link.get_text(" ", strip=True) for link in links))
        if text and len(text) <= 400 and len(link_text) / len(text) >= 0.7:
            tag.decompose()


def clean_markdown(markdown: str) -> str:
    """功能：清理 markdown 中的图片、链接、URL 和尾部样板内容。

    参数：
        markdown：待清理 markdown。
    返回值：
        返回清理后的 markdown。
    """
    markdown = re.sub(r"!\[[^\]]*]\([^)]*\)", "", markdown)
    markdown = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", markdown)
    markdown = re.sub(r"\n[ \t]+\n", "\n\n", markdown)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    lines = [URL_PATTERN.sub("", line) for line in markdown.splitlines()]
    lines = [line for line in lines if not PROMOTIONAL_LINE_PATTERN.match(normalize_text(line))]
    lines = [line for line in lines if not URL_ONLY_LINE_PATTERN.match(line.strip())]
    lines = trim_boilerplate_tail(lines)
    return "\n".join(lines).strip()


def trim_boilerplate_tail(lines: list[str]) -> list[str]:
    """功能：截断正文之后的相关推荐、页脚等样板内容。

    参数：
        lines：markdown 行列表。
    返回值：
        返回截断后的行列表。
    """
    kept_lines = []
    for line in lines:
        normalized = normalize_text(line).strip("* ")
        if BOILERPLATE_LINE_PATTERN.match(normalized):
            break
        kept_lines.append(line)
    return kept_lines


def has_meaningful_content(markdown: str) -> bool:
    """功能：判断 markdown 是否有足够正文内容。

    参数：
        markdown：待判断 markdown。
    返回值：
        正文字符量达到阈值时返回 True。
    """
    text = re.sub(r"[#*_>`~\-\[\]()]", "", markdown)
    return len(normalize_text(text)) >= MIN_MARKDOWN_CHARS


def extract_candidate_pool(
    bundle: ResearchBundle,
    destination: str,
    preferences: list[str],
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    model: str | None = None,
) -> list[dict[str, object]]:
    """功能：用 DeepSeek 从 markdown 攻略中抽取并排序候选景点池。

    参数：
        bundle：Tavily 搜索和 markdown 抓取得到的调研结果。
        destination：目的地名称，保留给调用方语义和后续扩展。
        preferences：用户偏好，用于 DeepSeek 给 preference_score 打分。
        max_candidates：最多返回的候选景点数量。
        model：DeepSeek 模型名；不传则读取 DEEPSEEK_MODEL。
    返回值：
        返回按景点名称总出现次数和偏好符合分排序的候选景点字典列表。
    """
    markdown_guides = build_markdown_guides(bundle.documents, DEFAULT_MAX_MARKDOWN_CHARS)
    if not markdown_guides:
        raise RuntimeError("没有可供 DeepSeek 抽取候选景点的 markdown 攻略")
    markdown_documents = [document.text for document in bundle.documents if document.text.strip()]

    selected_model = normalize_deepseek_model(
        model or os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    )
    graph = build_graph(build_structured_deepseek(selected_model))
    try:
        result = graph.invoke(
            {
                "markdown_guides": markdown_guides,
                "markdown_documents": markdown_documents,
                "destination": destination,
                "preferences": preferences,
                "max_candidates": max_candidates,
            }
        )
    except Exception as exc:
        raise RuntimeError(f"DeepSeek markdown 候选池生成失败：{exc}") from exc

    ranked_pool = result.get("ranked_candidate_pool")
    if not isinstance(ranked_pool, RankedCandidatePool):
        raise RuntimeError("DeepSeek markdown 候选池生成失败：结构化结果为空")
    return build_candidate_dicts(ranked_pool, bundle.documents, selected_model)


def generate_hot_candidate_pool(
    destination: str,
    days: int,
    preferences: list[str],
    *,
    per_query_limit: int = 3,
    max_search_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_page_chars: int = 12_000,
    max_search_iterations: int = DEFAULT_MAX_SEARCH_ITERATIONS,
    model: str | None = None,
) -> CandidatePoolGenerationResult:
    """功能：运行热门候选景点池 Agent，生成搜索计划、调研网页并抽取候选景点。

    参数：
        destination：目的地名称。
        days：旅行天数，只作为需求背景，不限制搜索词必须围绕天数。
        preferences：用户偏好，用于生成搜索词和候选景点偏好打分。
        per_query_limit：每个搜索词最多接受的页面数量。
        max_search_results：整体最多接受的搜索结果数量。
        max_candidates：最多返回的候选景点数量。
        max_page_chars：每篇 markdown 最多保留字符数。
        max_search_iterations：最多允许搜索工具调用轮次。
        model：DeepSeek 模型名；不传则读取 DEEPSEEK_MODEL。
    返回值：
        返回网页调研结果和带提及频率、偏好分的热门候选景点池。
    """
    load_local_env()
    selected_model = normalize_deepseek_model(
        model or os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    )
    graph = build_candidate_pool_agent_graph(
        build_structured_query_planner(selected_model),
        build_structured_deepseek(selected_model),
        per_query_limit=per_query_limit,
        max_search_results=max_search_results,
        max_page_chars=max_page_chars,
        max_search_iterations=max_search_iterations,
    )
    try:
        result = graph.invoke(
            {
                "destination": destination,
                "days": days,
                "preferences": preferences,
                "max_candidates": max_candidates,
            }
        )
    except Exception as exc:
        raise RuntimeError(f"热门候选景点池 Agent 生成失败：{exc}") from exc

    ranked_pool = result.get("ranked_candidate_pool")
    research_bundle = result.get("research_bundle")
    if not isinstance(ranked_pool, RankedCandidatePool) or not isinstance(
        research_bundle, ResearchBundle
    ):
        raise RuntimeError("热门候选景点池 Agent 生成失败：结构化结果为空")
    return CandidatePoolGenerationResult(
        research_bundle=research_bundle,
        candidates=build_candidate_dicts(
            ranked_pool,
            research_bundle.documents,
            selected_model,
            candidate_builder="deepseek_candidate_pool_agent",
        ),
    )


def build_markdown_guides(documents: list[ResearchDocument], max_chars: int) -> str:
    """功能：把多篇 markdown 攻略合并成发送给 DeepSeek 的上下文。

    参数：
        documents：已清噪 markdown 文档。
        max_chars：最多保留字符数。
    返回值：
        返回合并后的 markdown 字符串。
    """
    markdown = "\n\n---\n\n".join(document.text.strip() for document in documents if document.text.strip())
    return markdown[:max_chars].strip()


def build_prompt(
    markdown_guides: str,
    preferences: list[str],
    max_candidates: int,
    destination: str,
) -> str:
    """功能：构造 DeepSeek 候选池抽取提示词。

    参数：
        markdown_guides：清噪后的 markdown 攻略。
        preferences：用户偏好。
        max_candidates：最多输出景点数量。
        destination：用户指定的目的地城市或行政区。
    返回值：
        返回完整提示词。
    """
    preference_text = "、".join(preferences) if preferences else "无明确偏好"
    destination_text = destination.strip() or "用户指定目的地"
    return f"""
请从 FloatTrip 的 markdown 旅行攻略中抽取候选景点池。

用户指定目的地：{destination_text}
用户偏好：{preference_text}
最多输出：{max_candidates} 个景点

抽取要求：
- 只能输出位于“{destination_text}”行政区范围内的景点；不要输出从“{destination_text}”出发前往外地、周边城市、跨城线路中的景点。
- 如果攻略标题或正文出现“{destination_text}周边”“{destination_text}到外地”“{destination_text}-其他城市”“从{destination_text}出发”等跨城语境，只抽取仍在“{destination_text}”本地的景点，忽略其他城市景点。
- 遇到名称带有其他城市前缀或明显属于其他城市的景点，必须排除，即使文本中出现过。
- 只输出真实可游玩的景点、景区、博物馆、公园、历史街区、古镇、寺庙、主题乐园、自然风景区。
- 不输出酒店、餐厅、美食菜名、商场、交通站点、行政区地址、攻略标题词、路线词、开放时间、预约和门票信息。
- 同一景点的简称、别名和全称只保留一个名称。
- name 必须选择 markdown 攻略中出现过的那个景点名称，后续程序会按 name 原文统计总出现次数。
- 不要统计景点出现次数，程序会在结构化抽取后统计。
- preference_score 只衡量景点和用户偏好的符合程度，使用 0 到 10 的整数。
- 文本没有足够证据时不要猜测景点；没有可靠候选时返回空数组。

markdown 攻略：
{markdown_guides}
""".strip()


def build_structured_deepseek(model: str) -> Any:
    """功能：创建支持结构化输出的 DeepSeek Chat 模型。

    参数：
        model：DeepSeek 模型名。
    返回值：
        返回绑定 CandidatePool schema 的 LangChain 模型。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY。请在环境变量或 .env.local 中配置后重试。")

    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx 或 langchain-openai。请先安装后端依赖。") from exc

    proxy = choose_http_proxy()
    http_client = httpx.Client(proxy=proxy, trust_env=False)
    http_async_client = httpx.AsyncClient(proxy=proxy, trust_env=False)
    llm = ChatOpenAI(
        model=normalize_deepseek_model(model),
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        http_client=http_client,
        http_async_client=http_async_client,
        http_socket_options=(),
        extra_body={"thinking": {"type": "disabled"}},
    )
    return llm.with_structured_output(CandidatePool, method="function_calling", strict=True)


def build_structured_query_planner(model: str) -> Any:
    """功能：创建支持结构化输出的 DeepSeek 搜索词规划模型。

    参数：
        model：DeepSeek 模型名。
    返回值：
        返回绑定 SearchQueryPlan schema 的 LangChain 模型。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY。请在环境变量或 .env.local 中配置后重试。")

    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx 或 langchain-openai。请先安装后端依赖。") from exc

    proxy = choose_http_proxy()
    http_client = httpx.Client(proxy=proxy, trust_env=False)
    http_async_client = httpx.AsyncClient(proxy=proxy, trust_env=False)
    llm = ChatOpenAI(
        model=normalize_deepseek_model(model),
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        http_client=http_client,
        http_async_client=http_async_client,
        http_socket_options=(),
        extra_body={"thinking": {"type": "disabled"}},
    )
    return llm.with_structured_output(SearchQueryPlan, method="function_calling", strict=True)


def build_query_plan_prompt(destination: str, days: int, preferences: list[str]) -> str:
    """功能：构造热门候选景点池 Agent 的搜索词规划提示词。

    参数：
        destination：目的地名称。
        days：旅行天数。
        preferences：用户偏好。
    返回值：
        返回完整提示词。
    """
    preference_text = "、".join(preferences) if preferences else "无明确偏好"
    day_text = chinese_days(days)
    return f"""
请为 FloatTrip 的“热门候选景点池”生成多条网页搜索 query。

用户目的地：{destination}
用户旅行天数：{days} 天（约等于 {day_text}，只能作为背景，不要让所有 query 都局限于几日游）
用户偏好：{preference_text}

搜索目标：
- 找到目的地本地范围内高频出现、游客常去、攻略稳定推荐的热门景点。
- 同时覆盖宽泛热门景点、必去榜单、景点推荐、经典路线、用户偏好玩法。
- 可以包含“{destination} 热门旅游景点”“{destination} 必去景点”“{destination} 景点推荐”等放宽搜索。
- 也可以包含“{destination} {day_text} 攻略”“{destination} 自由行路线”等行程相关搜索。

输出要求：
- 返回 5 到 8 条中文 query。
- 每条 query 应能直接用于 Tavily 搜索。
- 不要输出酒店、美食、交通、门票预约这种非候选景点池主目标的 query。
""".strip()


def build_followup_query_plan_prompt(state: CandidatePoolState) -> str:
    """功能：构造候选池 Agent 在证据不足时继续搜索的提示词。

    参数：
        state：包含目的地、已有搜索词、候选池和调研文档的 Agent 状态。
    返回值：
        返回完整提示词。
    """
    destination = state.get("destination", "")
    days = state.get("days", 1)
    preferences = state.get("preferences", [])
    preference_text = "、".join(preferences) if preferences else "无明确偏好"
    ranked_pool = state.get("ranked_candidate_pool")
    candidate_names = []
    if isinstance(ranked_pool, RankedCandidatePool):
        candidate_names = [candidate.name for candidate in ranked_pool.candidate_pool[:12]]
    searched_text = "、".join(state.get("searched_queries", [])) or "暂无"
    candidate_text = "、".join(candidate_names) or "暂无稳定候选"
    document_count = len(state.get("markdown_documents", []))
    return f"""
FloatTrip 热门候选景点池 Agent 已经完成一轮真实搜索，但信息仍不足，需要继续生成补充 query。

目的地：{destination}
旅行天数：{days} 天
用户偏好：{preference_text}
已搜索 query：{searched_text}
当前候选景点：{candidate_text}
当前可用 markdown 文档数：{document_count}

请继续生成 2 到 4 条新的中文搜索 query，用于补足热门候选景点池。

补充搜索目标：
- 优先补足目的地本地热门景点、必去榜单、景点排行榜、经典景区集合。
- 如果当前候选偏少，放宽到“{destination} 值得去的景点”“{destination} 旅游景点排名”“{destination} 景区推荐”。
- 如果偏好相关候选不足，增加偏好玩法 query，但不要只搜小众内容。
- 避免重复已经搜索过的 query。

不要输出酒店、美食、交通、门票预约等非景点候选池 query。
""".strip()


def plan_search_queries_node(structured_query_llm: Any):
    """功能：生成候选景点池 Agent 的搜索词规划节点。

    参数：
        structured_query_llm：绑定 SearchQueryPlan schema 的 LLM。
    返回值：
        返回可注册到 LangGraph 的节点函数。
    """

    def plan_search_queries(state: CandidatePoolState) -> CandidatePoolState:
        """功能：调用 DeepSeek 生成并归一化多 query 搜索计划。

        参数：
            state：包含目的地、天数和偏好的 Agent 状态。
        返回值：
            返回写入 query_plan 的状态增量。
        """
        plan = structured_query_llm.invoke(
            [
                (
                    "system",
                    "你是 FloatTrip 的旅行调研搜索词规划器。必须按结构化输出 schema 返回结果。",
                ),
                (
                    "human",
                    build_query_plan_prompt(
                        state.get("destination", ""),
                        state.get("days", 1),
                        state.get("preferences", []),
                    ),
                ),
            ]
        )
        raw_queries = []
        if isinstance(plan, SearchQueryPlan):
            raw_queries = plan.queries
        elif isinstance(plan, dict):
            raw_queries = [str(query) for query in plan.get("queries", [])]
        query_plan = normalize_query_plan(
            raw_queries,
            state.get("destination", ""),
            state.get("days", 1),
            state.get("preferences", []),
        )
        return {
            "query_plan": query_plan,
            "pending_search_queries": query_plan,
            "searched_queries": [],
            "search_iterations": 0,
        }

    return plan_search_queries


def plan_followup_search_queries_node(structured_query_llm: Any):
    """功能：生成候选池 Agent 的补充搜索词规划节点。

    参数：
        structured_query_llm：绑定 SearchQueryPlan schema 的 LLM。
    返回值：
        返回可注册到 LangGraph 的节点函数。
    """

    def plan_followup_search_queries(state: CandidatePoolState) -> CandidatePoolState:
        """功能：根据当前候选池和已搜索 query 继续生成补充 query。

        参数：
            state：包含当前候选池、搜索历史和调研文档的 Agent 状态。
        返回值：
            返回更新后的 query_plan 和 pending_search_queries。
        """
        plan = structured_query_llm.invoke(
            [
                (
                    "system",
                    "你是 FloatTrip 的旅行调研搜索 Agent。你会根据已有搜索结果决定下一轮补充搜索词。",
                ),
                ("human", build_followup_query_plan_prompt(state)),
            ]
        )
        raw_queries = []
        if isinstance(plan, SearchQueryPlan):
            raw_queries = plan.queries
        elif isinstance(plan, dict):
            raw_queries = [str(query) for query in plan.get("queries", [])]

        existing_queries = [
            *state.get("query_plan", []),
            *state.get("searched_queries", []),
        ]
        pending_queries = normalize_followup_query_plan(
            raw_queries,
            state.get("destination", ""),
            state.get("days", 1),
            state.get("preferences", []),
            existing_queries,
        )
        return {
            "query_plan": dedupe_preserve_order([*state.get("query_plan", []), *pending_queries]),
            "pending_search_queries": pending_queries,
        }

    return plan_followup_search_queries


def collect_research_node(
    per_query_limit: int,
    max_search_results: int,
    max_page_chars: int,
):
    """功能：生成按 Agent 搜索计划抓取 markdown 攻略的节点。

    参数：
        per_query_limit：每个搜索词最多接受的页面数量。
        max_search_results：整体最多接受的搜索结果数量。
        max_page_chars：每篇 markdown 最多保留字符数。
    返回值：
        返回可注册到 LangGraph 的节点函数。
    """

    def collect_research_from_plan(state: CandidatePoolState) -> CandidatePoolState:
        """功能：调用真实搜索工具执行 Tavily 多 query 搜索和网页 markdown 提纯。

        参数：
            state：包含 query_plan 的 Agent 状态。
        返回值：
            返回调研结果和供 DeepSeek 抽取的 markdown 上下文。
        """
        pending_queries = state.get("pending_search_queries", [])
        search_budget = min(
            TAVILY_MAX_RESULTS,
            max_search_results * (state.get("search_iterations", 0) + 1),
        )
        bundle = search_markdown_research_tool(
            pending_queries,
            existing_bundle=state.get("research_bundle"),
            per_query_limit=per_query_limit,
            max_results=search_budget,
            max_page_chars=max_page_chars,
        )
        searched_queries = dedupe_preserve_order(
            [*state.get("searched_queries", []), *pending_queries]
        )
        return {
            "research_bundle": bundle,
            "query_plan": bundle.query_plan,
            "searched_queries": searched_queries,
            "pending_search_queries": [],
            "search_iterations": state.get("search_iterations", 0) + 1,
            "markdown_guides": build_markdown_guides(bundle.documents, DEFAULT_MAX_MARKDOWN_CHARS),
            "markdown_documents": [
                document.text for document in bundle.documents if document.text.strip()
            ],
        }

    return collect_research_from_plan


def extract_candidates_node(structured_llm: Any):
    """功能：生成 LangGraph 的 DeepSeek 抽取节点。

    参数：
        structured_llm：绑定结构化输出 schema 的 LLM。
    返回值：
        返回可注册到 LangGraph 的节点函数。
    """

    def extract_candidates(state: CandidatePoolState) -> CandidatePoolState:
        """功能：执行 DeepSeek 结构化候选池抽取。

        参数：
            state：包含 markdown 攻略、用户偏好和最大候选数量的 LangGraph 状态。
        返回值：
            返回写入 candidate_pool 的状态增量。
        """
        pool = structured_llm.invoke(
            [
                (
                    "system",
                    "你是 FloatTrip 的旅行景点候选池抽取器。必须按结构化输出 schema 返回结果。",
                ),
                (
                    "human",
                    build_prompt(
                        state["markdown_guides"],
                        state.get("preferences", []),
                        state.get("max_candidates", DEFAULT_MAX_CANDIDATES),
                        state.get("destination", ""),
                    ),
                ),
            ]
        )
        return {"candidate_pool": pool}

    return extract_candidates


def sort_candidates_node(state: CandidatePoolState) -> CandidatePoolState:
    """功能：统计候选景点名称总出现次数并排序。

    参数：
        state：包含 DeepSeek 原始候选池、markdown 攻略和单篇网页文本的图状态。
    返回值：
        返回包含 ranked_candidate_pool 的状态增量。
    """
    candidate_pool = state.get("candidate_pool")
    if not isinstance(candidate_pool, CandidatePool):
        raise RuntimeError("DeepSeek 未返回候选景点池，请检查模型结构化输出或重试")
    return {
        "ranked_candidate_pool": rank_candidate_pool(
            candidate_pool,
            state.get("markdown_documents", [state["markdown_guides"]]),
            state.get("max_candidates", DEFAULT_MAX_CANDIDATES),
        )
    }


def candidate_pool_needs_more_search(
    state: CandidatePoolState,
    *,
    max_search_iterations: int,
    max_search_results: int,
) -> bool:
    """功能：判断热门候选池证据是否不足，是否需要继续搜索。

    参数：
        state：包含候选池、搜索轮次和调研结果的 Agent 状态。
        max_search_iterations：最多搜索轮次。
        max_search_results：最多接受的搜索结果数量。
    返回值：
        候选数量或文档证据不足且仍有搜索预算时返回 True。
    """
    if state.get("search_iterations", 0) >= max_search_iterations:
        return False

    ranked_pool = state.get("ranked_candidate_pool")
    candidate_count = (
        len(ranked_pool.candidate_pool)
        if isinstance(ranked_pool, RankedCandidatePool)
        else 0
    )
    document_count = len(state.get("markdown_documents", []))
    target_candidates = min(
        state.get("max_candidates", DEFAULT_MAX_CANDIDATES),
        max(8, state.get("days", 1) * 3),
    )
    evidence_is_low = document_count < 3 or candidate_count < target_candidates
    research_bundle = state.get("research_bundle")
    if (
        evidence_is_low
        and isinstance(research_bundle, ResearchBundle)
        and len(research_bundle.search_results) >= TAVILY_MAX_RESULTS
    ):
        return False
    if document_count < 3:
        return True
    return candidate_count < target_candidates


def route_after_candidate_quality_check(
    max_search_iterations: int,
    max_search_results: int,
):
    """功能：生成 LangGraph 条件边函数，根据候选池质量决定继续搜索或结束。

    参数：
        max_search_iterations：最多搜索轮次。
        max_search_results：最多接受的搜索结果数量。
    返回值：
        返回条件边函数，输出 search_more 或 finish。
    """

    def route(state: CandidatePoolState) -> str:
        """功能：返回候选池 Agent 下一步路由。

        参数：
            state：当前 Agent 状态。
        返回值：
            返回 search_more 或 finish。
        """
        if candidate_pool_needs_more_search(
            state,
            max_search_iterations=max_search_iterations,
            max_search_results=max_search_results,
        ):
            return "search_more"
        return "finish"

    return route


def build_graph(structured_llm: Any) -> Any:
    """功能：构建 DeepSeek 抽取和代码排序的 LangGraph。

    参数：
        structured_llm：绑定结构化输出 schema 的 LLM。
    返回值：
        返回已编译的 LangGraph。
    """
    from langgraph.graph import END, START, StateGraph

    graph_builder = StateGraph(CandidatePoolState)
    graph_builder.add_node("extract_candidates", extract_candidates_node(structured_llm))
    graph_builder.add_node("sort_candidates", sort_candidates_node)
    graph_builder.add_edge(START, "extract_candidates")
    graph_builder.add_edge("extract_candidates", "sort_candidates")
    graph_builder.add_edge("sort_candidates", END)
    return graph_builder.compile()


def build_candidate_pool_agent_graph(
    structured_query_llm: Any,
    structured_candidate_llm: Any,
    *,
    per_query_limit: int,
    max_search_results: int,
    max_page_chars: int,
    max_search_iterations: int = DEFAULT_MAX_SEARCH_ITERATIONS,
) -> Any:
    """功能：构建带搜索工具和补充搜索循环的热门候选池 Agent。

    参数：
        structured_query_llm：绑定 SearchQueryPlan schema 的搜索词规划 LLM。
        structured_candidate_llm：绑定 CandidatePool schema 的候选抽取 LLM。
        per_query_limit：每个搜索词最多接受的页面数量。
        max_search_results：整体最多接受的搜索结果数量。
        max_page_chars：每篇 markdown 最多保留字符数。
        max_search_iterations：最多允许搜索工具调用轮次。
    返回值：
        返回已编译的 LangGraph。
    """
    from langgraph.graph import END, START, StateGraph

    graph_builder = StateGraph(CandidatePoolState)
    graph_builder.add_node("plan_search_queries", plan_search_queries_node(structured_query_llm))
    graph_builder.add_node(
        "plan_followup_search_queries",
        plan_followup_search_queries_node(structured_query_llm),
    )
    graph_builder.add_node(
        "collect_research",
        collect_research_node(per_query_limit, max_search_results, max_page_chars),
    )
    graph_builder.add_node("extract_candidates", extract_candidates_node(structured_candidate_llm))
    graph_builder.add_node("sort_candidates", sort_candidates_node)
    graph_builder.add_edge(START, "plan_search_queries")
    graph_builder.add_edge("plan_search_queries", "collect_research")
    graph_builder.add_edge("collect_research", "extract_candidates")
    graph_builder.add_edge("extract_candidates", "sort_candidates")
    graph_builder.add_conditional_edges(
        "sort_candidates",
        route_after_candidate_quality_check(max_search_iterations, max_search_results),
        {
            "search_more": "plan_followup_search_queries",
            "finish": END,
        },
    )
    graph_builder.add_edge("plan_followup_search_queries", "collect_research")
    return graph_builder.compile()


def rank_candidate_pool(
    pool: CandidatePool,
    markdown_documents: list[str],
    max_candidates: int,
) -> RankedCandidatePool:
    """功能：按景点名称总出现次数和偏好符合分排序候选景点。

    参数：
        pool：DeepSeek 输出的候选景点池。
        markdown_documents：用于统计名称总出现次数的单篇 markdown 原文列表。
        max_candidates：最多保留候选数。
    返回值：
        返回排序后的候选景点池。
    """
    counted_by_name: dict[str, RankedAttractionCandidate] = {}
    for candidate in pool.candidate_pool:
        name = candidate.name.strip()
        mention_count = count_name_mentions(markdown_documents, name)
        if not name or mention_count < 1:
            continue
        previous = counted_by_name.get(name)
        preference_score = max(
            candidate.preference_score,
            previous.preference_score if previous else 0,
        )
        counted_by_name[name] = RankedAttractionCandidate(
            name=name,
            preference_score=preference_score,
            mention_count=mention_count,
        )

    sorted_candidates = sorted(
        counted_by_name.values(),
        key=lambda candidate: (
            -candidate.mention_count,
            -candidate.preference_score,
            candidate.name,
        ),
    )
    return RankedCandidatePool(candidate_pool=sorted_candidates[:max_candidates])


def build_candidate_dicts(
    pool: RankedCandidatePool,
    documents: list[ResearchDocument],
    model: str,
    candidate_builder: str = "deepseek_markdown",
) -> list[dict[str, object]]:
    """功能：把排序后的候选景点模型转换成后续 POI 校验使用的字典。

    参数：
        pool：排序后的候选景点池。
        documents：markdown 来源文档，用于补充 sources。
        model：实际使用的 DeepSeek 模型名。
        candidate_builder：候选池构建器标识。
    返回值：
        返回候选景点字典列表。
    """
    candidates: list[dict[str, object]] = []
    for candidate in pool.candidate_pool:
        candidates.append(
            {
                "name": candidate.name,
                "mention_count": candidate.mention_count,
                "preference_score": candidate.preference_score,
                "score": candidate.mention_count * 100 + candidate.preference_score,
                "candidate_builder": candidate_builder,
                "model": model,
                "sources": [
                    {"title": document.title, "url": document.url, "source": document.source}
                    for document in documents
                    if candidate.name in document.text
                ][:4],
            }
        )
    return candidates


def count_name_mentions(markdown_documents: list[str], name: str) -> int:
    """功能：统计景点名称在所有 markdown 网页中的总出现次数。

    参数：
        markdown_documents：单篇 markdown 攻略原文列表。
        name：景点名称。
    返回值：
        返回景点名称出现总次数；同一网页重复出现会重复累计。
    """
    normalized_name = name.strip()
    if not normalized_name:
        return 0
    return sum(document.count(normalized_name) for document in markdown_documents)


def build_queries(destination: str, days: int, preferences: list[str]) -> list[str]:
    """功能：根据目的地、天数和偏好生成 Tavily 搜索词兜底计划。

    参数：
        destination：目的地名称。
        days：旅行天数。
        preferences：用户偏好。
    返回值：
        返回搜索词列表。
    """
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


def build_popular_fallback_queries(destination: str, days: int, preferences: list[str]) -> list[str]:
    """功能：生成保证候选池覆盖热门景点的兜底搜索词。

    参数：
        destination：目的地名称。
        days：旅行天数。
        preferences：用户偏好。
    返回值：
        返回宽泛热门景点、必去榜单、推荐攻略和行程攻略搜索词。
    """
    day_text = chinese_days(days)
    pref_text = " ".join(preferences)
    queries = [
        f"{destination} 热门旅游景点",
        f"{destination} 必去景点 排行榜",
        f"{destination} 景点推荐 攻略",
        f"{destination} {day_text} 攻略 景点",
        f"{destination} 自由行 经典路线 景点",
    ]
    if pref_text:
        queries.insert(3, f"{destination} {pref_text} 景点推荐")
    return queries


def normalize_query_plan(
    llm_queries: list[str],
    destination: str,
    days: int,
    preferences: list[str],
    max_queries: int = 8,
) -> list[str]:
    """功能：合并 LLM 搜索词和热门兜底搜索词，并去重限制数量。

    参数：
        llm_queries：DeepSeek 生成的搜索词。
        destination：目的地名称。
        days：旅行天数。
        preferences：用户偏好。
        max_queries：最多保留搜索词数量。
    返回值：
        返回优先覆盖热门景点的多 query 搜索计划。
    """
    merged_queries = [
        *build_popular_fallback_queries(destination, days, preferences),
        *llm_queries,
    ]
    normalized_queries: list[str] = []
    seen_queries: set[str] = set()
    for query in merged_queries:
        cleaned = re.sub(r"\s+", " ", str(query).strip())
        if not cleaned:
            continue
        dedupe_key = cleaned.casefold()
        if dedupe_key in seen_queries:
            continue
        normalized_queries.append(cleaned)
        seen_queries.add(dedupe_key)
        if len(normalized_queries) >= max_queries:
            break
    return normalized_queries


def normalize_followup_query_plan(
    llm_queries: list[str],
    destination: str,
    days: int,
    preferences: list[str],
    existing_queries: list[str],
    max_queries: int = 4,
) -> list[str]:
    """功能：归一化补充搜索词，过滤已搜索 query，并在 LLM 输出不足时补充兜底 query。

    参数：
        llm_queries：DeepSeek 生成的补充搜索词。
        destination：目的地名称。
        days：旅行天数。
        preferences：用户偏好。
        existing_queries：已计划或已搜索的 query。
        max_queries：最多保留补充搜索词数量。
    返回值：
        返回本轮待搜索的新 query。
    """
    fallback_queries = [
        f"{destination} 值得去的景点",
        f"{destination} 旅游景点排名",
        f"{destination} 景区推荐",
        *build_popular_fallback_queries(destination, days, preferences),
    ]
    existing_keys = {query.casefold() for query in existing_queries}
    normalized_queries: list[str] = []
    seen_queries: set[str] = set()
    for query in [*llm_queries, *fallback_queries]:
        cleaned = re.sub(r"\s+", " ", str(query).strip())
        if not cleaned:
            continue
        dedupe_key = cleaned.casefold()
        if dedupe_key in existing_keys or dedupe_key in seen_queries:
            continue
        normalized_queries.append(cleaned)
        seen_queries.add(dedupe_key)
        if len(normalized_queries) >= max_queries:
            break
    return normalized_queries


def dedupe_preserve_order(items: list[str]) -> list[str]:
    """功能：按原顺序对字符串列表去重。

    参数：
        items：待去重字符串列表。
    返回值：
        返回去空格、去重后的字符串列表。
    """
    deduped_items: list[str] = []
    seen_items: set[str] = set()
    for item in items:
        cleaned = re.sub(r"\s+", " ", str(item).strip())
        if not cleaned:
            continue
        dedupe_key = cleaned.casefold()
        if dedupe_key in seen_items:
            continue
        deduped_items.append(cleaned)
        seen_items.add(dedupe_key)
    return deduped_items


def chinese_days(days: int) -> str:
    """功能：把旅行天数转换成中文搜索词。

    参数：
        days：旅行天数。
    返回值：
        返回中文天数描述。
    """
    mapping = {1: "一日游", 2: "两日游", 3: "三日游", 4: "四日游", 5: "五日游", 6: "六日游", 7: "七日游"}
    return mapping.get(days, f"{days}日游")


def normalize_deepseek_model(model: str) -> str:
    """功能：兼容旧版 DeepSeek 模型别名。

    参数：
        model：模型名或旧别名。
    返回值：
        返回标准模型名。
    """
    legacy_aliases = {
        "deepseekv4flash": "deepseek-v4-flash",
        "deepseekv4pro": "deepseek-v4-pro",
    }
    return legacy_aliases.get(model.strip(), model.strip())


def choose_http_proxy() -> str | None:
    """功能：选择 httpx 可直接使用的 HTTP 代理。

    参数：
        无。
    返回值：
        返回代理 URL；没有可用代理时返回 None。
    """
    for key in HTTP_PROXY_ENV_KEYS:
        proxy = os.getenv(key, "").strip()
        if proxy.startswith(("http://", "https://")):
            return proxy
    return None


def normalize_text(value: str) -> str:
    """功能：压缩文本空白。

    参数：
        value：原始文本。
    返回值：
        返回压缩空白后的文本。
    """
    return re.sub(r"\s+", " ", value).strip()


def load_local_env() -> None:
    """功能：加载项目根目录 .env.local 中的环境变量，不覆盖已有变量。

    参数：
        无。
    返回值：
        无。
    """
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
