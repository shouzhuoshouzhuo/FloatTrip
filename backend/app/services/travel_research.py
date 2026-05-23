"""网页搜索、markdown 提纯和 DeepSeek 候选景点池服务。"""

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
DEEPSEEK_BASE_URL = "https://api.deepseek.com/beta"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_SEARCH_RESULTS = 8
DEFAULT_MAX_CANDIDATES = 28
DEFAULT_MAX_MARKDOWN_CHARS = 60_000
TAVILY_MAX_RESULTS = 20
MIN_MARKDOWN_CHARS = 200
DEFAULT_SEARCH_TIMEOUT = 20.0
DEFAULT_FETCH_TIMEOUT = 10.0
PRIORITY_SEARCH_DOMAINS = ("bendibao.com",)
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


class AttractionCandidate(BaseModel):
    """DeepSeek 从 markdown 中识别出的候选景点。"""

    name: str = Field(description="合并别名后的标准景点中文名")
    preference_score: int = Field(
        ge=0,
        le=10,
        description="该景点与用户偏好的符合分，0 表示不符合，10 表示非常符合",
    )


class RankedAttractionCandidate(AttractionCandidate):
    """补充代码统计提及频率后的候选景点。"""

    mention_count: int = Field(ge=1, description="景点名称在 markdown 攻略中的出现次数")


class CandidatePool(BaseModel):
    """DeepSeek 结构化输出的候选景点池。"""

    candidate_pool: list[AttractionCandidate] = Field(description="候选景点池")


class RankedCandidatePool(BaseModel):
    """排序后的候选景点池。"""

    candidate_pool: list[RankedAttractionCandidate] = Field(description="排序后的候选景点池")


class CandidatePoolState(TypedDict, total=False):
    """LangGraph 候选池抽取状态。"""

    markdown_guides: str
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
        返回按提及频率和偏好符合分排序的候选景点字典列表。
    """
    del destination
    markdown_guides = build_markdown_guides(bundle.documents, DEFAULT_MAX_MARKDOWN_CHARS)
    if not markdown_guides:
        raise RuntimeError("没有可供 DeepSeek 抽取候选景点的 markdown 攻略")

    selected_model = normalize_deepseek_model(
        model or os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    )
    graph = build_graph(build_structured_deepseek(selected_model))
    try:
        result = graph.invoke(
            {
                "markdown_guides": markdown_guides,
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


def build_prompt(markdown_guides: str, preferences: list[str], max_candidates: int) -> str:
    """功能：构造 DeepSeek 候选池抽取提示词。

    参数：
        markdown_guides：清噪后的 markdown 攻略。
        preferences：用户偏好。
        max_candidates：最多输出景点数量。
    返回值：
        返回完整提示词。
    """
    preference_text = "、".join(preferences) if preferences else "无明确偏好"
    return f"""
请从 FloatTrip 的 markdown 旅行攻略中抽取候选景点池。

用户偏好：{preference_text}
最多输出：{max_candidates} 个景点

抽取要求：
- 只输出真实可游玩的景点、景区、博物馆、公园、历史街区、古镇、寺庙、主题乐园、自然风景区。
- 不输出酒店、餐厅、美食菜名、商场、交通站点、行政区地址、攻略标题词、路线词、开放时间、预约和门票信息。
- 同一景点的简称、别名和全称只保留一个名称。
- name 必须选择 markdown 攻略中出现过的那个景点名称，后续程序会按 name 原文统计出现频率。
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


def extract_candidates_node(structured_llm: Any):
    """功能：生成 LangGraph 的 DeepSeek 抽取节点。

    参数：
        structured_llm：绑定结构化输出 schema 的 LLM。
    返回值：
        返回可注册到 LangGraph 的节点函数。
    """

    def extract_candidates(state: CandidatePoolState) -> CandidatePoolState:
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
                    ),
                ),
            ]
        )
        return {"candidate_pool": pool}

    return extract_candidates


def sort_candidates_node(state: CandidatePoolState) -> CandidatePoolState:
    """功能：统计候选景点提及频率并排序。

    参数：
        state：包含 DeepSeek 原始候选池和 markdown 攻略的图状态。
    返回值：
        返回包含 ranked_candidate_pool 的状态增量。
    """
    return {
        "ranked_candidate_pool": rank_candidate_pool(
            state["candidate_pool"],
            state["markdown_guides"],
            state.get("max_candidates", DEFAULT_MAX_CANDIDATES),
        )
    }


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


def rank_candidate_pool(
    pool: CandidatePool,
    markdown_guides: str,
    max_candidates: int,
) -> RankedCandidatePool:
    """功能：按 markdown 原文提及频率和偏好符合分排序候选景点。

    参数：
        pool：DeepSeek 输出的候选景点池。
        markdown_guides：用于统计提及频率的 markdown 原文。
        max_candidates：最多保留候选数。
    返回值：
        返回排序后的候选景点池。
    """
    counted_by_name: dict[str, RankedAttractionCandidate] = {}
    for candidate in pool.candidate_pool:
        name = candidate.name.strip()
        mention_count = count_name_mentions(markdown_guides, name)
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
) -> list[dict[str, object]]:
    """功能：把排序后的候选景点模型转换成后续 POI 校验使用的字典。

    参数：
        pool：排序后的候选景点池。
        documents：markdown 来源文档，用于补充 sources。
        model：实际使用的 DeepSeek 模型名。
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
                "candidate_builder": "deepseek_markdown",
                "model": model,
                "sources": [
                    {"title": document.title, "url": document.url, "source": document.source}
                    for document in documents
                    if candidate.name in document.text
                ][:4],
            }
        )
    return candidates


def count_name_mentions(markdown_guides: str, name: str) -> int:
    """功能：统计景点名称在 markdown 原文中的字面出现次数。

    参数：
        markdown_guides：markdown 攻略原文。
        name：景点名称。
    返回值：
        返回出现次数。
    """
    return markdown_guides.count(name.strip()) if name.strip() else 0


def build_queries(destination: str, days: int, preferences: list[str]) -> list[str]:
    """功能：根据目的地、天数和偏好生成 Tavily 搜索词。

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
