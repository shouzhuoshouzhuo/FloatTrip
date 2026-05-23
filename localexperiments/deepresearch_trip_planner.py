#!/usr/bin/env python3
"""Single-file DeepResearch-style trip planner for FloatTrip.

Examples:
  python3 tools/deepresearch_trip_planner.py "常州 3日游，亲子，公交优先" --mock
  python3 tools/deepresearch_trip_planner.py "南京 2日游，历史文化，步行优先" --output /tmp/floattrip_plan.json

The live planner requires:
  DEEPSEEK_API_KEY
  TAVILY_API_KEY
  AMAP_API_KEY
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV_FILE = PROJECT_ROOT / ".env.local"

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
AMAP_TEXT_SEARCH_URL = "https://restapi.amap.com/v3/place/text"
AMAP_AROUND_SEARCH_URL = "https://restapi.amap.com/v3/place/around"
AMAP_TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"
AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/beta"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) FloatTripDeepResearchPlanner/0.1"
)
EARTH_RADIUS_KM = 6371.0088
MAX_ATTRACTIONS_PER_DAY = 4
MIN_ATTRACTIONS_PER_DAY = 2
WALKING_FALLBACK_MAX_METERS = 1500

TransportMode = Literal["auto", "transit", "walking", "driving"]
StopType = Literal["attraction", "lunch", "dinner"]


@dataclass
class ResearchSource:
    title: str
    url: str
    query: str = ""


@dataclass
class Location:
    lng: float
    lat: float


@dataclass
class Stop:
    stop_id: str
    name: str
    type: StopType
    location: Location
    address: str = ""
    poi_type: str = ""
    source: str = "amap"
    score: float = 0.0
    mention_count: int = 1
    meal: str | None = None


@dataclass
class RouteSegment:
    from_stop_id: str
    from_name: str
    to_stop_id: str
    to_name: str
    mode: str
    duration_seconds: int | None
    distance_meters: int | None
    summary: str
    path: list[Location] = field(default_factory=list)
    fallback_mode: str | None = None


@dataclass
class ParsedRequest:
    destination: str
    days: int
    preferences: list[str]
    transport_preference: TransportMode
    pace: str = "balanced"


class PlannerError(RuntimeError):
    """Raised for clear user-facing planning failures."""


class AgentLogger:
    """Small stderr logger so stdout can remain valid JSON."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.step = 0

    def agent(self, message: str) -> None:
        self._write("agent", message, numbered=True)

    def subagent(self, message: str) -> None:
        self._write("subagent", message)

    def tool(self, message: str) -> None:
        self._write("tool", message)

    def warn(self, message: str) -> None:
        self._write("warn", message)

    def _write(self, label: str, message: str, *, numbered: bool = False) -> None:
        if not self.enabled:
            return
        prefix = f"[{label}]"
        if numbered:
            self.step += 1
            prefix = f"[{label} {self.step:02d}]"
        print(f"{prefix} {message}", file=sys.stderr, flush=True)


NULL_LOGGER = AgentLogger(enabled=False)


def load_local_env() -> None:
    """Load project-local .env.local without overriding exported variables."""
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


def require_env(name: str, hint: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise PlannerError(f"缺少 {name}。{hint}")
    return value


def plan_trip(user_request: str, *, mock: bool = False, verbose: bool = False) -> dict[str, Any]:
    """Plan a trip and return frontend-ready JSON."""
    load_local_env()
    logger = AgentLogger(verbose)
    logger.agent("读取用户旅行需求，先做本地粗解析")
    parsed = parse_user_request(user_request)
    logger.tool(
        f"粗解析结果：destination={parsed.destination}, days={parsed.days}, "
        f"transport={parsed.transport_preference}, preferences={parsed.preferences}"
    )
    if mock:
        logger.agent("进入 mock 模式：不调用 Tavily、DeepSeek、高德，只生成可验证结构")
        return build_mock_plan(parsed, user_request)

    logger.agent("检查真实 Agent 所需密钥：Tavily、AMap、DeepSeek")
    require_env("TAVILY_API_KEY", "请在环境变量或 .env.local 中配置 Tavily API Key。")
    require_env("AMAP_API_KEY", "请在环境变量或 .env.local 中配置高德 Web服务 Key。")
    require_env("DEEPSEEK_API_KEY", "请在环境变量或 .env.local 中配置 DeepSeek API Key。")

    return DeepResearchTripPlanner(parsed, user_request, logger).run()


class DeepResearchTripPlanner:
    """A compact DeepResearch-style orchestrator kept in one file."""

    def __init__(self, parsed: ParsedRequest, user_request: str, logger: AgentLogger | None = None) -> None:
        self.parsed = parsed
        self.user_request = user_request
        self.logger = logger or NULL_LOGGER
        self.warnings: list[str] = []

    def run(self) -> dict[str, Any]:
        self.logger.agent("调用 DeepSeek 作为主 Agent，重新理解目的地、天数、偏好和交通方式")
        self.parsed = refine_request_with_deepseek(self.user_request, self.parsed, self.logger)
        self.logger.tool(
            f"主 Agent 确认：destination={self.parsed.destination}, days={self.parsed.days}, "
            f"transport={self.parsed.transport_preference}, pace={self.parsed.pace}, "
            f"preferences={self.parsed.preferences}"
        )
        self.logger.agent("生成 DeepResearch 检索计划和 TODO")
        todos = build_research_todos_with_deepseek(self.user_request, self.parsed, self.logger)
        for index, todo in enumerate(todos, start=1):
            self.logger.subagent(f"TODO {index}: {todo}")

        self.logger.agent("启动网页研究子代理：搜索攻略并汇总可引用资料")
        sources, research_text = travel_web_search(
            self.parsed.destination,
            self.parsed.days,
            self.parsed.preferences,
            self.logger,
        )
        self.logger.tool(f"网页研究完成：sources={len(sources)}, text_chars={len(research_text)}")
        self.logger.agent("调用景点研究子代理：从资料中抽取候选景点")
        raw_names = extract_attraction_names_with_deepseek(
            self.user_request,
            self.parsed,
            research_text,
            self.logger,
        )
        self.logger.subagent(f"候选景点抽取完成：{[item.get('name') for item in raw_names[:12]]}")
        candidates = rank_candidate_names(raw_names, research_text)
        self.logger.agent("调用高德 POI 工具：校验景点真实性并补齐坐标")
        attractions = amap_search_attractions(candidates, self.parsed.destination, self.logger)
        self.logger.tool(f"高德景点校验完成：valid_attractions={len(attractions)}")
        if len(attractions) < self.parsed.days * MIN_ATTRACTIONS_PER_DAY:
            raise PlannerError(
                f"有效景点不足：需要至少 {self.parsed.days * MIN_ATTRACTIONS_PER_DAY} 个，"
                f"高德校验后只有 {len(attractions)} 个。"
            )

        self.logger.agent("按地理位置把景点分配到每天")
        day_groups = split_attractions_by_day(attractions, self.parsed.days)
        days = []
        for day_index, day_attractions in enumerate(day_groups, start=1):
            self.logger.agent(
                f"规划第 {day_index} 天：景点={', '.join(stop.name for stop in day_attractions)}"
            )
            days.append(self.plan_day(day_index, day_attractions))

        self.logger.agent("完成结构化行程 JSON")
        return {
            "schema_version": "floattrip_deepresearch_trip_plan.v1",
            "planner": "single_file_deepresearch_trip_planner",
            "destination": self.parsed.destination,
            "days_count": self.parsed.days,
            "transport_preference": self.parsed.transport_preference,
            "preferences": self.parsed.preferences,
            "days": days,
            "warnings": self.warnings,
            "research_sources": [asdict(source) for source in sources],
        }

    def plan_day(self, day_index: int, attractions: list[Stop]) -> dict[str, Any]:
        ordered_attractions, attraction_segments = optimize_attraction_order(
            attractions,
            self.parsed.destination,
            self.parsed.transport_preference,
            self.warnings,
            self.logger,
        )
        stops = insert_restaurant_stops(
            ordered_attractions,
            self.parsed.destination,
            self.warnings,
            self.logger,
        )
        route_segments = build_route_segments_for_stops(
            stops,
            self.parsed.destination,
            self.parsed.transport_preference,
            self.warnings,
            self.logger,
        )
        total_duration = sum(
            segment.duration_seconds or 0
            for segment in route_segments
            if segment.duration_seconds is not None
        )
        total_distance = sum(
            segment.distance_meters or 0
            for segment in route_segments
            if segment.distance_meters is not None
        )
        return {
            "day_index": day_index,
            "stops": [stop_to_dict(stop, order=index + 1) for index, stop in enumerate(stops)],
            "route_segments": [route_segment_to_dict(segment) for segment in route_segments],
            "summary_metrics": {
                "attraction_count": len(ordered_attractions),
                "restaurant_count": sum(1 for stop in stops if stop.type in ("lunch", "dinner")),
                "total_duration_seconds": total_duration,
                "total_duration_minutes": round(total_duration / 60, 1),
                "total_distance_meters": total_distance,
                "route_status": "planned" if route_segments else "route_pending",
                "pre_restaurant_attraction_segments": len(attraction_segments),
            },
        }


def parse_user_request(user_request: str) -> ParsedRequest:
    text = user_request.strip()
    if not text:
        raise PlannerError("旅行需求不能为空。")

    days_match = re.search(r"(\d+)\s*(?:天|日|days?)", text, re.IGNORECASE)
    days = int(days_match.group(1)) if days_match else 3
    if days < 1 or days > 14:
        raise PlannerError("旅行天数需要在 1 到 14 天之间。")

    destination = parse_destination(text, days_match.start() if days_match else None)
    preferences = parse_preferences(text, destination)
    transport = parse_transport(text)
    pace = "relaxed" if any(word in text for word in ("轻松", "慢", "亲子", "老人")) else "balanced"
    return ParsedRequest(destination, days, preferences, transport, pace)


def parse_destination(text: str, days_index: int | None) -> str:
    prefix = text[:days_index].strip(" ，,。") if days_index is not None else text
    city_match = re.search(r"([\u4e00-\u9fa5A-Za-z]{2,12})(?:市|省|县|区)?", prefix)
    if city_match:
        return normalize_destination(city_match.group(1))
    city_match = re.search(r"去([\u4e00-\u9fa5A-Za-z]{2,12})", text)
    if city_match:
        return normalize_destination(city_match.group(1))
    raise PlannerError("无法从需求中识别目的地，例如：常州 3日游，亲子，公交优先。")


def normalize_destination(value: str) -> str:
    destination = value.strip()
    for suffix in ("旅游", "旅行", "游玩", "自由行"):
        if destination.endswith(suffix):
            destination = destination[: -len(suffix)]
    return destination


def parse_preferences(text: str, destination: str) -> list[str]:
    known = [
        "亲子",
        "历史",
        "文化",
        "美食",
        "自然",
        "博物馆",
        "古镇",
        "citywalk",
        "购物",
        "小众",
        "轻松",
        "摄影",
        "夜景",
    ]
    preferences = [item for item in known if item.lower() in text.lower()]
    cleaned_parts = [
        part.strip()
        for part in re.split(r"[,，、。；;\s]+", text)
        if part.strip() and not re.search(r"\d+\s*(?:天|日)", part)
    ]
    ignored = {destination, f"{destination}市", "旅游", "旅行", "自由行"}
    for part in cleaned_parts:
        if (
            2 <= len(part) <= 8
            and part not in ignored
            and normalize_destination(part) != destination
            and not any(word in part for word in ("优先", "公交", "步行", "驾车"))
        ):
            if part not in preferences and part != parse_transport(text):
                preferences.append(part)
    return preferences[:8]


def parse_transport(text: str) -> TransportMode:
    if any(word in text for word in ("公交", "地铁", "公共交通")):
        return "transit"
    if any(word in text for word in ("步行", "citywalk", "Citywalk")):
        return "walking"
    if any(word in text for word in ("自驾", "驾车", "开车", "打车")):
        return "driving"
    return "auto"


def create_deepseek_chat_model():
    """Create the DeepSeek chat model used by the live agent."""
    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise PlannerError(
            "缺少 langchain-openai，无法调用 DeepSeek。请安装依赖：python3 -m pip install langchain-openai"
        ) from exc

    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        api_key=require_env("DEEPSEEK_API_KEY", "请先配置 DeepSeek API Key。"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
        temperature=0,
    )


def invoke_deepseek_json(system_prompt: str, human_prompt: str, logger: AgentLogger) -> dict[str, Any]:
    logger.subagent("DeepSeek thinking...")
    content = deepseek_chat_completion(system_prompt, human_prompt)
    logger.subagent(f"DeepSeek returned {len(content)} chars")
    return parse_json_from_text(content)


def deepseek_chat_completion(system_prompt: str, human_prompt: str) -> str:
    """Call DeepSeek's OpenAI-compatible chat completion endpoint directly."""
    api_key = require_env("DEEPSEEK_API_KEY", "请先配置 DeepSeek API Key。")
    base_url = os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL).rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": human_prompt},
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    data = read_json_request(request, timeout=90)
    if "error" in data:
        raise PlannerError(f"DeepSeek 调用失败：{data['error']}")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise PlannerError("DeepSeek 响应缺少 choices。")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise PlannerError("DeepSeek 响应缺少 message。")
    content = str(message.get("content") or "").strip()
    if not content:
        raise PlannerError("DeepSeek 响应内容为空。")
    return content


def refine_request_with_deepseek(user_request: str, fallback: ParsedRequest, logger: AgentLogger) -> ParsedRequest:
    prompt = f"""
请把用户旅行需求解析成结构化 JSON。

用户需求：{user_request}
本地粗解析：
{{"destination":"{fallback.destination}","days":{fallback.days},"preferences":{json.dumps(fallback.preferences, ensure_ascii=False)},"transport_preference":"{fallback.transport_preference}","pace":"{fallback.pace}"}}

要求：
- destination 是目的地城市或地区名，不要包含“旅游/旅行/自由行”。
- days 是 1 到 14 的整数。
- preferences 是用户明确表达的旅行偏好数组。
- transport_preference 只能是 auto、transit、walking、driving。
- pace 只能是 relaxed、balanced、intensive。

返回严格 JSON：
{{"destination":"城市","days":3,"preferences":["亲子"],"transport_preference":"transit","pace":"relaxed"}}
""".strip()
    try:
        payload = invoke_deepseek_json(
            "你是 FloatTrip 的旅行需求理解 Agent。你只返回合法 JSON。",
            prompt,
            logger,
        )
    except Exception as exc:
        logger.warn(f"DeepSeek 需求理解失败，回退到本地解析：{exc}")
        return fallback

    destination = normalize_destination(str(payload.get("destination") or fallback.destination))
    days = safe_int(payload.get("days"), default=fallback.days)
    if days < 1 or days > 14:
        days = fallback.days
    preferences = payload.get("preferences")
    if not isinstance(preferences, list):
        preferences = fallback.preferences
    preferences = [str(item).strip() for item in preferences if str(item).strip()][:8]
    transport = str(payload.get("transport_preference") or fallback.transport_preference)
    if transport not in ("auto", "transit", "walking", "driving"):
        transport = fallback.transport_preference
    pace = str(payload.get("pace") or fallback.pace)
    if pace not in ("relaxed", "balanced", "intensive"):
        pace = fallback.pace
    return ParsedRequest(destination, days, preferences, transport, pace)  # type: ignore[arg-type]


def build_research_todos_with_deepseek(user_request: str, parsed: ParsedRequest, logger: AgentLogger) -> list[str]:
    prompt = f"""
你是 FloatTrip 的 DeepResearch 主 Agent。请为下面的旅行规划任务生成 3 到 6 条 TODO。

用户需求：{user_request}
目的地：{parsed.destination}
天数：{parsed.days}
偏好：{", ".join(parsed.preferences) or "无"}
交通：{parsed.transport_preference}

TODO 必须覆盖：网页研究、景点候选、POI 校验、分天、饭店插入、路线不绕路。
返回严格 JSON：{{"todos":["...","..."]}}
""".strip()
    try:
        payload = invoke_deepseek_json(
            "你是会规划工具调用步骤的旅行 DeepResearch Agent。你只返回合法 JSON。",
            prompt,
            logger,
        )
    except Exception as exc:
        logger.warn(f"DeepSeek TODO 生成失败，使用默认 TODO：{exc}")
        return [
            "搜索目的地旅行攻略并收集资料来源",
            "抽取符合偏好的真实景点候选",
            "用高德 POI 校验景点并补齐坐标",
            "按地理位置分天并优化每天访问顺序",
            "在当天路线中段和终点附近插入午餐与晚餐",
            "用高德路线规划生成不绕路的路线段",
        ]
    todos = payload.get("todos")
    if not isinstance(todos, list):
        return []
    return [str(todo).strip() for todo in todos if str(todo).strip()][:6]


def travel_web_search(
    destination: str,
    days: int,
    preferences: list[str],
    logger: AgentLogger | None = None,
) -> tuple[list[ResearchSource], str]:
    """Search travel guides and return sources plus combined markdown-like text."""
    logger = logger or NULL_LOGGER
    api_key = require_env("TAVILY_API_KEY", "请先配置 Tavily API Key。")
    queries = build_research_queries(destination, days, preferences)
    logger.tool(f"Tavily query plan: {queries}")
    sources: list[ResearchSource] = []
    texts: list[str] = []
    seen_urls: set[str] = set()
    for query in queries:
        logger.tool(f"Tavily searching: {query}")
        payload = {
            "query": query,
            "search_depth": "advanced",
            "max_results": 5,
            "topic": "general",
            "country": "china",
            "include_answer": True,
            "include_raw_content": True,
            "include_images": False,
            "include_favicon": False,
        }
        data = post_json(TAVILY_SEARCH_URL, payload, api_key)
        logger.tool(f"Tavily returned {len(data.get('results', []))} results for: {query}")
        if data.get("answer"):
            texts.append(f"## Tavily answer for {query}\n{data['answer']}")
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).split("#", 1)[0]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = str(item.get("title") or url)
            content = str(item.get("raw_content") or item.get("content") or "")
            sources.append(ResearchSource(title=title, url=url, query=query))
            texts.append(f"## {title}\nURL: {url}\n{content[:12000]}")
            logger.tool(f"Collected source: {title} ({url})")
        time.sleep(0.3)
    if not texts:
        raise PlannerError("Tavily 没有返回可用旅行资料，无法继续规划。")
    return sources, "\n\n".join(texts)


def build_research_queries(destination: str, days: int, preferences: list[str]) -> list[str]:
    preference_text = " ".join(preferences) if preferences else "经典 必去"
    return [
        f"{destination} {days}日游 攻略 必去景点 {preference_text}",
        f"{destination} 旅游攻略 景点 排名 {preference_text}",
        f"{destination} 自由行 路线 {days}天 {preference_text}",
    ]


def extract_attraction_names_with_deepseek(
    user_request: str,
    parsed: ParsedRequest,
    research_text: str,
    logger: AgentLogger | None = None,
) -> list[dict[str, Any]]:
    """Use DeepSeek to extract candidate attraction names from research text."""
    logger = logger or NULL_LOGGER

    prompt = f"""
你是 FloatTrip 的 DeepResearch 景点候选抽取器。

用户需求：{user_request}
目的地：{parsed.destination}
天数：{parsed.days}
偏好：{", ".join(parsed.preferences) or "无"}

请只从资料中抽取真实可游玩的景点、景区、博物馆、公园、历史街区、古镇、寺庙、主题乐园、自然风景区。
不要输出酒店、餐厅、美食菜名、商场、交通站点、政府机构、地址、门票或开放时间。

返回严格 JSON，格式：
{{"candidates":[{{"name":"景点名","preference_score":0到10的整数,"reason":"一句话理由"}}]}}

资料：
{research_text[:60000]}
""".strip()
    payload = invoke_deepseek_json(
        "你是 FloatTrip 的 DeepResearch 景点候选抽取子代理。你只返回合法 JSON，不返回 markdown，不返回解释。",
        prompt,
        logger,
    )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise PlannerError("DeepSeek 候选景点抽取结果缺少 candidates 数组。")
    normalized = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized.append(
            {
                "name": name,
                "preference_score": safe_int(item.get("preference_score"), default=0),
                "reason": str(item.get("reason") or ""),
            }
        )
    if not normalized:
        raise PlannerError("DeepSeek 未抽取到可用候选景点。")
    return normalized


def parse_json_from_text(text: str) -> dict[str, Any]:
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise PlannerError("模型没有返回 JSON。")
        return json.loads(match.group(0))


def rank_candidate_names(candidates: list[dict[str, Any]], research_text: str) -> list[dict[str, Any]]:
    ranked = []
    seen: set[str] = set()
    for item in candidates:
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        mention_count = max(1, research_text.count(name))
        preference_score = safe_int(item.get("preference_score"), default=0)
        ranked.append(
            {
                "name": name,
                "mention_count": mention_count,
                "preference_score": preference_score,
                "score": mention_count * 10 + preference_score,
                "reason": item.get("reason") or "",
            }
        )
    return sorted(ranked, key=lambda item: (-item["score"], item["name"]))


def amap_search_attractions(
    candidates: list[dict[str, Any]],
    destination: str,
    logger: AgentLogger | None = None,
) -> list[Stop]:
    logger = logger or NULL_LOGGER
    api_key = require_env("AMAP_API_KEY", "请先配置高德 Web服务 Key。")
    stops: list[Stop] = []
    for candidate in candidates:
        logger.tool(f"AMap POI searching attraction: {candidate['name']}")
        pois = amap_text_search(candidate["name"], destination, api_key, offset=8)
        logger.tool(f"AMap returned {len(pois)} POI candidates for {candidate['name']}")
        poi = choose_attraction_poi(candidate["name"], pois, destination)
        if not poi:
            logger.warn(f"景点未通过高德校验：{candidate['name']}")
            continue
        stop = poi_to_stop(
            poi,
            stop_type="attraction",
            fallback_id=f"attraction-{len(stops) + 1}",
            score=float(candidate.get("score") or 0),
            mention_count=safe_int(candidate.get("mention_count"), default=1),
        )
        if stop.location:
            stops.append(stop)
            logger.tool(f"景点通过校验：{stop.name} @ {stop.location.lng},{stop.location.lat}")
        time.sleep(0.2)
    return dedupe_stops(stops)


def amap_search_restaurants_nearby(
    location: Location,
    destination: str,
    meal: Literal["lunch", "dinner"],
    warnings: list[str],
    logger: AgentLogger | None = None,
) -> Stop | None:
    logger = logger or NULL_LOGGER
    api_key = require_env("AMAP_API_KEY", "请先配置高德 Web服务 Key。")
    logger.tool(f"AMap nearby restaurant search: meal={meal}, anchor={location.lng},{location.lat}")
    params = {
        "key": api_key,
        "location": f"{location.lng},{location.lat}",
        "keywords": "餐厅|饭店|美食",
        "types": "050000",
        "city": destination,
        "radius": "1200" if meal == "lunch" else "1800",
        "sortrule": "distance",
        "offset": "12",
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
    data = http_get_json(f"{AMAP_AROUND_SEARCH_URL}?{urllib.parse.urlencode(params)}")
    if data.get("status") != "1":
        warnings.append(f"{meal} restaurant search failed: {data.get('info') or 'unknown'}")
        logger.warn(warnings[-1])
        return None
    pois = [poi for poi in data.get("pois", []) if isinstance(poi, dict)]
    logger.tool(f"AMap returned {len(pois)} nearby restaurant POIs for {meal}")
    poi = choose_restaurant_poi(pois)
    if not poi:
        warnings.append(f"{meal} restaurant search returned no usable POI near {location.lng},{location.lat}")
        logger.warn(warnings[-1])
        return None
    stop = poi_to_stop(
        poi,
        stop_type=meal,
        fallback_id=f"{meal}-{poi.get('id') or 'restaurant'}",
        score=0,
        mention_count=1,
        meal=meal,
    )
    logger.tool(f"餐厅选中：{meal} -> {stop.name}")
    return stop


def amap_text_search(keyword: str, city: str, api_key: str, offset: int = 10) -> list[dict[str, Any]]:
    params = {
        "key": api_key,
        "keywords": keyword,
        "city": city,
        "citylimit": "true",
        "offset": str(offset),
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
    data = http_get_json(f"{AMAP_TEXT_SEARCH_URL}?{urllib.parse.urlencode(params)}")
    if data.get("status") != "1":
        raise PlannerError(f"高德 POI 搜索失败：{data.get('info') or '未知错误'}")
    pois = data.get("pois", [])
    return pois if isinstance(pois, list) else []


def choose_attraction_poi(candidate_name: str, pois: list[dict[str, Any]], destination: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1
    for poi in pois:
        poi_type = str(poi.get("type") or "")
        poi_name = str(poi.get("name") or "")
        if not is_attraction_type(poi_type):
            continue
        if destination and not poi_matches_city(poi, destination):
            continue
        location = parse_location(poi.get("location"))
        if not location:
            continue
        score = attraction_match_score(candidate_name, poi_name, poi_type)
        if score > best_score:
            best_score = score
            best = poi
    return best


def choose_restaurant_poi(pois: list[dict[str, Any]]) -> dict[str, Any] | None:
    blocked = ("住宿服务", "购物服务", "生活服务", "公司企业", "交通设施服务")
    best: dict[str, Any] | None = None
    best_score = -1
    for poi in pois:
        poi_type = str(poi.get("type") or "")
        name = str(poi.get("name") or "")
        if any(item in poi_type for item in blocked) or not parse_location(poi.get("location")):
            continue
        if "餐饮服务" not in poi_type and not any(word in name for word in ("餐厅", "饭店", "菜馆", "小吃", "酒楼")):
            continue
        score = safe_float(poi.get("biz_ext", {}).get("rating") if isinstance(poi.get("biz_ext"), dict) else None) * 10
        if "中餐" in poi_type:
            score += 5
        if score > best_score:
            best_score = score
            best = poi
    return best


def is_attraction_type(poi_type: str) -> bool:
    attraction_keywords = (
        "风景名胜",
        "公园广场",
        "博物馆",
        "展览馆",
        "美术馆",
        "科技馆",
        "纪念馆",
        "寺庙",
        "道观",
        "教堂",
        "文化宫",
        "文物古迹",
        "动物园",
        "植物园",
        "水族馆",
        "海洋馆",
        "游乐场",
        "主题乐园",
        "度假区",
        "自然地名",
    )
    blocked = (
        "住宿服务",
        "餐饮服务",
        "购物服务",
        "生活服务",
        "公司企业",
        "商务住宅",
        "金融保险",
        "医疗保健",
        "政府机构",
        "交通设施服务",
    )
    return bool(poi_type) and not any(item in poi_type for item in blocked) and any(
        item in poi_type for item in attraction_keywords
    )


def poi_matches_city(poi: dict[str, Any], destination: str) -> bool:
    normalized_destination = normalize_region_name(destination)
    names = [str(poi.get(key) or "") for key in ("pname", "cityname", "adname")]
    return any(normalize_region_name(name) == normalized_destination for name in names if name) or any(
        normalized_destination in normalize_region_name(name) for name in names if name
    )


def normalize_region_name(region: str) -> str:
    normalized = region.strip()
    for suffix in ("特别行政区", "自治州", "自治区", "省", "市", "区", "县"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def attraction_match_score(candidate_name: str, poi_name: str, poi_type: str) -> int:
    score = 0
    if candidate_name == poi_name:
        score += 100
    elif candidate_name in poi_name or poi_name in candidate_name:
        score += 70
    else:
        score += common_char_score(candidate_name, poi_name)
    if "风景名胜" in poi_type:
        score += 20
    if any(item in poi_type for item in ("博物馆", "纪念馆", "文物古迹", "公园广场")):
        score += 12
    return score


def common_char_score(left: str, right: str) -> int:
    left_chars = {char for char in left if re.match(r"[\u4e00-\u9fa5A-Za-z0-9]", char)}
    right_chars = {char for char in right if re.match(r"[\u4e00-\u9fa5A-Za-z0-9]", char)}
    if not left_chars or not right_chars:
        return 0
    return int(40 * len(left_chars & right_chars) / len(left_chars | right_chars))


def poi_to_stop(
    poi: dict[str, Any],
    *,
    stop_type: StopType,
    fallback_id: str,
    score: float,
    mention_count: int,
    meal: str | None = None,
) -> Stop:
    location = parse_location(poi.get("location"))
    if not location:
        raise PlannerError(f"高德 POI 缺少坐标：{poi.get('name') or fallback_id}")
    return Stop(
        stop_id=str(poi.get("id") or fallback_id),
        name=str(poi.get("name") or fallback_id),
        type=stop_type,
        location=location,
        address=normalize_address(poi.get("address")),
        poi_type=str(poi.get("type") or ""),
        score=score,
        mention_count=mention_count,
        meal=meal,
    )


def parse_location(value: Any) -> Location | None:
    if not isinstance(value, str) or "," not in value:
        return None
    lng_text, lat_text = value.split(",", 1)
    try:
        lng = float(lng_text)
        lat = float(lat_text)
    except ValueError:
        return None
    if not math.isfinite(lng) or not math.isfinite(lat):
        return None
    return Location(lng=lng, lat=lat)


def normalize_address(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value or "")


def dedupe_stops(stops: list[Stop]) -> list[Stop]:
    seen: set[str] = set()
    output: list[Stop] = []
    for stop in stops:
        key = stop.stop_id or stop.name
        if key in seen:
            continue
        seen.add(key)
        output.append(stop)
    return output


def split_attractions_by_day(attractions: list[Stop], days: int) -> list[list[Stop]]:
    ranked = sorted(attractions, key=lambda stop: (-stop.score, -stop.mention_count, stop.name))
    selected = ranked[: days * MAX_ATTRACTIONS_PER_DAY]
    medoids = initialize_medoids(selected, days)
    groups = assign_to_medoids(selected, medoids)
    repaired = repair_day_groups(groups, selected, days)
    return [sorted(group, key=lambda stop: (-stop.score, stop.name))[:MAX_ATTRACTIONS_PER_DAY] for group in repaired]


def initialize_medoids(stops: list[Stop], days: int) -> list[Stop]:
    medoids = [max(stops, key=lambda stop: (stop.score, stop.mention_count))]
    while len(medoids) < days:
        remaining = [stop for stop in stops if stop not in medoids]
        medoids.append(
            max(
                remaining,
                key=lambda stop: min(distance_meters(stop.location, medoid.location) for medoid in medoids),
            )
        )
    return medoids


def assign_to_medoids(stops: list[Stop], medoids: list[Stop]) -> list[list[Stop]]:
    groups = [[] for _ in medoids]
    for stop in stops:
        index = min(
            range(len(medoids)),
            key=lambda medoid_index: distance_meters(stop.location, medoids[medoid_index].location),
        )
        groups[index].append(stop)
    return groups


def repair_day_groups(groups: list[list[Stop]], stops: list[Stop], days: int) -> list[list[Stop]]:
    groups = [list(group) for group in groups[:days]]
    while len(groups) < days:
        groups.append([])
    assigned = {stop.stop_id for group in groups for stop in group}
    for stop in stops:
        if stop.stop_id not in assigned:
            min(groups, key=len).append(stop)
            assigned.add(stop.stop_id)
    for group in groups:
        group.sort(key=lambda stop: (-stop.score, stop.name))
    return groups


def optimize_attraction_order(
    attractions: list[Stop],
    city: str,
    transport: TransportMode,
    warnings: list[str],
    logger: AgentLogger | None = None,
) -> tuple[list[Stop], list[RouteSegment]]:
    logger = logger or NULL_LOGGER
    if len(attractions) <= 1:
        return attractions, []
    logger.tool(f"构建景点通行时间矩阵：{len(attractions)} spots, transport={transport}")
    matrix, segment_map = build_duration_matrix(attractions, city, transport, warnings, logger)
    if len(attractions) <= 6:
        logger.tool("使用暴力枚举优化当天景点顺序")
        order = brute_force_order(matrix)
    else:
        logger.tool("使用 nearest-neighbor + 2-opt 优化当天景点顺序")
        order = two_opt_order(nearest_neighbor_order(matrix), matrix)
    ordered = [attractions[index] for index in order]
    logger.tool(f"优化后景点顺序：{' -> '.join(stop.name for stop in ordered)}")
    segments = [
        segment_map[(origin, destination)]
        for origin, destination in zip(order, order[1:])
        if (origin, destination) in segment_map
    ]
    return ordered, segments


def build_duration_matrix(
    stops: list[Stop],
    city: str,
    transport: TransportMode,
    warnings: list[str],
    logger: AgentLogger | None = None,
) -> tuple[list[list[int | None]], dict[tuple[int, int], RouteSegment]]:
    logger = logger or NULL_LOGGER
    matrix = [[0 if left == right else None for right in stops] for left in stops]
    segment_map: dict[tuple[int, int], RouteSegment] = {}
    for origin_index, destination_index in itertools.permutations(range(len(stops)), 2):
        try:
            logger.tool(
                f"AMap route matrix query: {stops[origin_index].name} -> {stops[destination_index].name}"
            )
            segment = amap_route(stops[origin_index], stops[destination_index], city, transport, logger)
        except Exception as exc:
            warnings.append(
                f"{stops[origin_index].name} -> {stops[destination_index].name} 路线获取失败：{exc}"
            )
            logger.warn(warnings[-1])
            continue
        matrix[origin_index][destination_index] = segment.duration_seconds
        segment_map[(origin_index, destination_index)] = segment
        logger.tool(
            f"route ok: {segment.mode}, {segment.duration_seconds}s, {segment.distance_meters}m"
        )
        time.sleep(0.15)
    return matrix, segment_map


def brute_force_order(matrix: list[list[int | None]]) -> list[int]:
    best_order: tuple[int, ...] | None = None
    best_duration: int | None = None
    indexes = range(len(matrix))
    for order in itertools.permutations(indexes):
        total = route_duration(order, matrix)
        if total is None:
            continue
        if best_duration is None or total < best_duration:
            best_duration = total
            best_order = order
    return list(best_order) if best_order else list(indexes)


def nearest_neighbor_order(matrix: list[list[int | None]]) -> list[int]:
    unvisited = set(range(1, len(matrix)))
    order = [0]
    while unvisited:
        current = order[-1]
        next_index = min(unvisited, key=lambda index: matrix[current][index] or 10**12)
        order.append(next_index)
        unvisited.remove(next_index)
    return order


def two_opt_order(order: list[int], matrix: list[list[int | None]]) -> list[int]:
    improved = True
    best = order
    while improved:
        improved = False
        for left in range(1, len(best) - 2):
            for right in range(left + 1, len(best)):
                candidate = best[:left] + best[left:right][::-1] + best[right:]
                if route_duration(candidate, matrix, large=True) < route_duration(best, matrix, large=True):
                    best = candidate
                    improved = True
    return best


def route_duration(order: tuple[int, ...] | list[int], matrix: list[list[int | None]], *, large: bool = False) -> int | None:
    total = 0
    for origin, destination in zip(order, order[1:]):
        duration = matrix[origin][destination]
        if duration is None:
            return 10**12 if large else None
        total += duration
    return total


def insert_restaurant_stops(
    attractions: list[Stop],
    city: str,
    warnings: list[str],
    logger: AgentLogger | None = None,
) -> list[Stop]:
    logger = logger or NULL_LOGGER
    if not attractions:
        return []
    stops = list(attractions)
    lunch_anchor = stops[max(0, min(len(stops) - 1, len(stops) // 2 - 1))].location
    dinner_anchor = stops[-1].location
    logger.tool("按不绕路约束插入餐厅：午餐锚点取当天路线中段，晚餐锚点取当天终点")
    lunch = amap_search_restaurants_nearby(lunch_anchor, city, "lunch", warnings, logger)
    dinner = amap_search_restaurants_nearby(dinner_anchor, city, "dinner", warnings, logger)
    if lunch:
        insert_index = max(1, len(stops) // 2)
        stops.insert(insert_index, lunch)
    if dinner:
        stops.append(dinner)
    return stops


def build_route_segments_for_stops(
    stops: list[Stop],
    city: str,
    transport: TransportMode,
    warnings: list[str],
    logger: AgentLogger | None = None,
) -> list[RouteSegment]:
    logger = logger or NULL_LOGGER
    segments = []
    for origin, destination in zip(stops, stops[1:]):
        try:
            logger.tool(f"AMap final route query: {origin.name} -> {destination.name}")
            segment = amap_route(origin, destination, city, transport, logger)
            segments.append(segment)
            logger.tool(
                f"final route ok: {segment.mode}, {segment.duration_seconds}s, {segment.distance_meters}m"
            )
        except Exception as exc:
            warnings.append(f"{origin.name} -> {destination.name} 路线获取失败：{exc}")
            logger.warn(warnings[-1])
    return segments


def amap_route(
    origin: Stop,
    destination: Stop,
    city: str,
    transport: TransportMode,
    logger: AgentLogger | None = None,
) -> RouteSegment:
    logger = logger or NULL_LOGGER
    mode = choose_route_mode(origin.location, destination.location, transport)
    logger.tool(f"route mode selected: {mode} for {origin.name} -> {destination.name}")
    try:
        return query_amap_route(origin, destination, city, mode)
    except Exception as exc:
        if mode == "transit" and distance_meters(origin.location, destination.location) <= WALKING_FALLBACK_MAX_METERS:
            logger.warn(f"transit failed for short segment, fallback walking: {exc}")
            segment = query_amap_route(origin, destination, city, "walking")
            segment.fallback_mode = "walking"
            return segment
        raise exc


def choose_route_mode(origin: Location, destination: Location, transport: TransportMode) -> TransportMode:
    if transport == "auto":
        return "walking" if distance_meters(origin, destination) <= WALKING_FALLBACK_MAX_METERS else "transit"
    return transport


def query_amap_route(origin: Stop, destination: Stop, city: str, mode: TransportMode) -> RouteSegment:
    api_key = require_env("AMAP_API_KEY", "请先配置高德 Web服务 Key。")
    origin_text = location_text(origin.location)
    destination_text = location_text(destination.location)
    if mode == "transit":
        params = {
            "key": api_key,
            "origin": origin_text,
            "destination": destination_text,
            "city": city,
            "strategy": "0",
            "output": "json",
        }
        data = http_get_json(f"{AMAP_TRANSIT_URL}?{urllib.parse.urlencode(params)}")
        return parse_transit_segment(data, origin, destination)
    if mode == "driving":
        params = {
            "key": api_key,
            "origin": origin_text,
            "destination": destination_text,
            "strategy": "0",
            "output": "json",
        }
        data = http_get_json(f"{AMAP_DRIVING_URL}?{urllib.parse.urlencode(params)}")
        return parse_path_segment(data, origin, destination, mode)
    params = {
        "key": api_key,
        "origin": origin_text,
        "destination": destination_text,
        "output": "json",
    }
    data = http_get_json(f"{AMAP_WALKING_URL}?{urllib.parse.urlencode(params)}")
    return parse_path_segment(data, origin, destination, "walking")


def parse_transit_segment(data: dict[str, Any], origin: Stop, destination: Stop) -> RouteSegment:
    if data.get("status") != "1":
        raise PlannerError(f"高德公交路径规划失败：{data.get('info') or 'unknown'}")
    transits = data.get("route", {}).get("transits", [])
    valid = [item for item in transits if isinstance(item, dict) and str(item.get("duration", "")).isdigit()]
    if not valid:
        raise PlannerError("高德没有返回可用公交路线")
    best = min(valid, key=lambda item: int(item["duration"]))
    return RouteSegment(
        from_stop_id=origin.stop_id,
        from_name=origin.name,
        to_stop_id=destination.stop_id,
        to_name=destination.name,
        mode="transit",
        duration_seconds=int(best["duration"]),
        distance_meters=int_or_none(best.get("distance")),
        summary=summarize_transit(best),
        path=extract_transit_path(best),
    )


def parse_path_segment(data: dict[str, Any], origin: Stop, destination: Stop, mode: str) -> RouteSegment:
    if data.get("status") != "1":
        raise PlannerError(f"高德{mode}路径规划失败：{data.get('info') or 'unknown'}")
    paths = data.get("route", {}).get("paths", [])
    valid = [item for item in paths if isinstance(item, dict) and str(item.get("duration", "")).isdigit()]
    if not valid:
        raise PlannerError(f"高德没有返回可用{mode}路线")
    best = min(valid, key=lambda item: int(item["duration"]))
    path_points = extract_path_steps(best)
    distance = int_or_none(best.get("distance"))
    return RouteSegment(
        from_stop_id=origin.stop_id,
        from_name=origin.name,
        to_stop_id=destination.stop_id,
        to_name=destination.name,
        mode=mode,
        duration_seconds=int(best["duration"]),
        distance_meters=distance,
        summary=f"{mode}约 {round((distance or 0) / 1000, 1)} km",
        path=path_points,
    )


def summarize_transit(best: dict[str, Any]) -> str:
    parts = []
    for segment in best.get("segments", []):
        if not isinstance(segment, dict):
            continue
        buslines = segment.get("bus", {}).get("buslines", [])
        if not buslines:
            continue
        line = buslines[0]
        name = line.get("name")
        departure = line.get("departure_stop", {}).get("name", "")
        arrival = line.get("arrival_stop", {}).get("name", "")
        if name:
            parts.append(f"{name}: {departure} -> {arrival}")
    return "；".join(parts) if parts else "公交/地铁路线"


def extract_transit_path(best: dict[str, Any]) -> list[Location]:
    path: list[Location] = []
    for segment in best.get("segments", []):
        if not isinstance(segment, dict):
            continue
        walking = segment.get("walking") if isinstance(segment.get("walking"), dict) else {}
        for step in walking.get("steps", []) if isinstance(walking.get("steps", []), list) else []:
            if isinstance(step, dict):
                path.extend(parse_polyline(step.get("polyline")))
        buslines = segment.get("bus", {}).get("buslines", [])
        for line in buslines if isinstance(buslines, list) else []:
            if isinstance(line, dict):
                path.extend(parse_polyline(line.get("polyline")))
    return dedupe_path(path)


def extract_path_steps(path_payload: dict[str, Any]) -> list[Location]:
    path: list[Location] = []
    steps = path_payload.get("steps", [])
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            path.extend(parse_polyline(step.get("polyline")))
    return dedupe_path(path)


def parse_polyline(value: Any) -> list[Location]:
    if not isinstance(value, str):
        return []
    points = []
    for pair in value.split(";"):
        location = parse_location(pair)
        if location:
            points.append(location)
    return points


def dedupe_path(path: list[Location]) -> list[Location]:
    output = []
    for point in path:
        if not output or point != output[-1]:
            output.append(point)
    return output


def post_json(url: str, payload: dict[str, Any], api_key: str, timeout: int = 30) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    return read_json_request(request, timeout)


def http_get_json(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    try:
        return read_json_request(request, timeout)
    except Exception as exc:
        raise PlannerError(f"请求失败：{redact_url(url)}；原因：{exc}") from exc


def read_json_request(request: urllib.request.Request, timeout: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(response.read().decode(charset, errors="replace"))
        except Exception as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise PlannerError(str(last_error))


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for key in ("key", "api_key", "access_token", "token"):
        if key in query:
            query[key] = ["<redacted>"]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


def distance_meters(left: Location, right: Location) -> float:
    left_lng = math.radians(left.lng)
    left_lat = math.radians(left.lat)
    right_lng = math.radians(right.lng)
    right_lat = math.radians(right.lat)
    lat_delta = right_lat - left_lat
    lng_delta = right_lng - left_lng
    haversine = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(left_lat) * math.cos(right_lat) * math.sin(lng_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(haversine))) * 1000


def location_text(location: Location) -> str:
    return f"{location.lng},{location.lat}"


def int_or_none(value: Any) -> int | None:
    return int(value) if str(value).isdigit() else None


def safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def stop_to_dict(stop: Stop, *, order: int) -> dict[str, Any]:
    return {
        "order": order,
        "stop_id": stop.stop_id,
        "name": stop.name,
        "type": stop.type,
        "meal": stop.meal,
        "location": asdict(stop.location),
        "address": stop.address,
        "poi_type": stop.poi_type,
        "source": stop.source,
        "score": stop.score,
        "mention_count": stop.mention_count,
    }


def route_segment_to_dict(segment: RouteSegment) -> dict[str, Any]:
    return {
        "from_stop_id": segment.from_stop_id,
        "from_name": segment.from_name,
        "to_stop_id": segment.to_stop_id,
        "to_name": segment.to_name,
        "mode": segment.mode,
        "duration_seconds": segment.duration_seconds,
        "duration_minutes": round(segment.duration_seconds / 60, 1) if segment.duration_seconds else None,
        "distance_meters": segment.distance_meters,
        "summary": segment.summary,
        "fallback_mode": segment.fallback_mode,
        "path": [asdict(point) for point in segment.path],
    }


def build_mock_plan(parsed: ParsedRequest, user_request: str) -> dict[str, Any]:
    """Return deterministic JSON without network calls."""
    base_lng = 119.974
    base_lat = 31.782
    names = [
        f"{parsed.destination}博物馆",
        f"{parsed.destination}老街",
        f"{parsed.destination}公园",
        f"{parsed.destination}文化广场",
        f"{parsed.destination}古运河",
        f"{parsed.destination}艺术馆",
        f"{parsed.destination}湖畔景区",
        f"{parsed.destination}历史街区",
    ]
    attractions = [
        Stop(
            stop_id=f"mock-attraction-{index + 1}",
            name=name,
            type="attraction",
            location=Location(base_lng + index * 0.012, base_lat + (index % 3) * 0.008),
            address=f"{name}地址",
            poi_type="风景名胜;风景名胜",
            score=100 - index,
            mention_count=5 - min(index, 4),
        )
        for index, name in enumerate(names[: max(parsed.days * 3, parsed.days * 2)])
    ]
    groups = split_attractions_by_day(attractions, parsed.days)
    days = []
    for day_index, group in enumerate(groups, start=1):
        ordered = sorted(group, key=lambda stop: (stop.location.lng, stop.location.lat))[:MAX_ATTRACTIONS_PER_DAY]
        stops: list[Stop] = []
        for index, stop in enumerate(ordered):
            if index == max(1, len(ordered) // 2):
                stops.append(
                    Stop(
                        stop_id=f"mock-lunch-{day_index}",
                        name=f"{parsed.destination}水岸餐厅",
                        type="lunch",
                        meal="lunch",
                        location=Location(stop.location.lng + 0.002, stop.location.lat + 0.001),
                        address="路线中段附近",
                        poi_type="餐饮服务;中餐厅",
                    )
                )
            stops.append(stop)
        stops.append(
            Stop(
                stop_id=f"mock-dinner-{day_index}",
                name=f"{parsed.destination}晚风饭店",
                type="dinner",
                meal="dinner",
                location=Location(ordered[-1].location.lng + 0.001, ordered[-1].location.lat + 0.001),
                address="当日终点附近",
                poi_type="餐饮服务;中餐厅",
            )
        )
        route_segments = [mock_segment(origin, destination, parsed.transport_preference) for origin, destination in zip(stops, stops[1:])]
        total_duration = sum(segment.duration_seconds or 0 for segment in route_segments)
        total_distance = sum(segment.distance_meters or 0 for segment in route_segments)
        days.append(
            {
                "day_index": day_index,
                "stops": [stop_to_dict(stop, order=i + 1) for i, stop in enumerate(stops)],
                "route_segments": [route_segment_to_dict(segment) for segment in route_segments],
                "summary_metrics": {
                    "attraction_count": len(ordered),
                    "restaurant_count": 2,
                    "total_duration_seconds": total_duration,
                    "total_duration_minutes": round(total_duration / 60, 1),
                    "total_distance_meters": total_distance,
                    "route_status": "planned_mock",
                },
            }
        )
    return {
        "schema_version": "floattrip_deepresearch_trip_plan.v1",
        "planner": "single_file_deepresearch_trip_planner",
        "mock": True,
        "input": user_request,
        "destination": parsed.destination,
        "days_count": parsed.days,
        "transport_preference": parsed.transport_preference,
        "preferences": parsed.preferences,
        "days": days,
        "warnings": ["mock 模式未调用 Tavily、DeepSeek 或高德 API。"],
        "research_sources": [
            {
                "title": "Mock travel guide",
                "url": "mock://floattrip/deepresearch",
                "query": user_request,
            }
        ],
    }


def mock_segment(origin: Stop, destination: Stop, transport: TransportMode) -> RouteSegment:
    distance = round(distance_meters(origin.location, destination.location))
    mode = "walking" if transport == "walking" or distance <= WALKING_FALLBACK_MAX_METERS else (
        "driving" if transport == "driving" else "transit"
    )
    speed = {"walking": 1.25, "driving": 8.0, "transit": 5.0}.get(mode, 5.0)
    duration = round(distance / speed) if distance else 180
    return RouteSegment(
        from_stop_id=origin.stop_id,
        from_name=origin.name,
        to_stop_id=destination.stop_id,
        to_name=destination.name,
        mode=mode,
        duration_seconds=duration,
        distance_meters=distance,
        summary=f"mock {mode} route",
        path=[origin.location, destination.location],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FloatTrip single-file DeepResearch trip planner.")
    parser.add_argument("request", help="自然语言旅行需求，例如：常州 3日游，亲子，公交优先")
    parser.add_argument("--mock", action="store_true", help="使用本地 mock 数据，不调用外部 API")
    parser.add_argument("--output", type=Path, help="输出 JSON 文件路径；不传则打印到 stdout")
    parser.add_argument("--quiet", action="store_true", help="关闭 Agent 步骤日志，只输出 JSON 或输出文件路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = plan_trip(args.request, mock=args.mock, verbose=not args.quiet)
    except Exception as exc:
        print(f"FloatTrip deepresearch planning failed: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
