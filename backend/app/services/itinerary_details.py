"""行程详情 Agent 服务。

功能：
    在已有按天景点路线和交通路线基础上，补充每日时间线、午晚餐推荐、天气
    和注意事项，供前端行程详情页直接渲染。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from backend.app.providers import amap, amap_mcp
from backend.app.schemas.route_plan import (
    DayItineraryDetail,
    DayNotice,
    DayRoutePlan,
    DayWeather,
    ItineraryActivity,
    Location,
    MealRecommendation,
    TripRoutePlanResponse,
)
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.services import travel_research
from backend.app.services.unsplash_service import UnsplashService, get_unsplash_service


DAY_START_MINUTE = 9 * 60
DAY_END_MINUTE = 20 * 60 + 30
DEFAULT_SPOT_DURATION = 80
COMPACT_SPOT_DURATION = 65
MEAL_DURATION = 70
LUNCH_TARGET = 12 * 60 + 15
DINNER_TARGET = 18 * 60
DEFAULT_RESTAURANT_RADIUS = 1500
EXPANDED_RESTAURANT_RADIUS = 3000
MAX_IMAGE_SEARCH_ATTEMPTS = 5
SPOT_IMAGE_QUERY_ALIASES = {
    "中山陵": [
        "Nanjing Sun Yat-sen Mausoleum",
        "Sun Yat-sen Mausoleum Nanjing",
        "Zhongshan Ling Nanjing",
    ],
    "明孝陵": [
        "Ming Xiaoling Mausoleum Nanjing",
        "Nanjing Ming Xiaoling",
        "Ming Tomb Nanjing",
    ],
    "夫子庙": [
        "Fuzimiao Nanjing",
        "Qinhuai River Nanjing",
        "Nanjing Confucius Temple",
    ],
    "秦淮河": [
        "Qinhuai River Nanjing",
        "Nanjing Qinhuai River",
    ],
    "老门东": [
        "Laomendong Nanjing",
        "Nanjing old east gate",
    ],
    "南京博物院": [
        "Nanjing Museum",
        "Nanjing Museum China",
    ],
    "总统府": [
        "Nanjing Presidential Palace",
        "Presidential Palace Nanjing",
    ],
    "玄武湖": [
        "Xuanwu Lake Nanjing",
        "Nanjing Xuanwu Lake",
    ],
    "鸡鸣寺": [
        "Jiming Temple Nanjing",
        "Nanjing Jiming Temple",
    ],
    "栖霞山": [
        "Qixia Mountain Nanjing",
        "Nanjing Qixia Mountain",
    ],
    "牛首山": [
        "Niushou Mountain Nanjing",
        "Nanjing Niushou Mountain",
    ],
}


class CrowdNoticeDraft(BaseModel):
    """DeepSeek 生成的高峰提醒草稿。"""

    level: str = Field(description="info 或 warning")
    title: str = Field(description="提醒标题")
    content: str = Field(description="提醒正文")


class DayThemeDraft(BaseModel):
    """DeepSeek 生成的当天行程主题草稿。"""

    theme: str = Field(description="8-18 个汉字的当天行程主题，不包含 Day 前缀")


class ImageSearchQueryPlan(BaseModel):
    """DeepSeek 生成的 Unsplash 图片搜索词计划。"""

    queries: list[str] = Field(
        description="适合 Unsplash Search Photos API 的英文或拼音图片搜索关键词，按优先级排序"
    )


def build_itinerary_details(
    route_plan: TripRoutePlanResponse,
    request: TripGenerateRouteRequest,
    *,
    transport_mode: str | None = "amap_transit",
    preferences: list[str] | None = None,
) -> TripRoutePlanResponse:
    """功能：为完整路线结果补充每天的行程详情。

    参数：
        route_plan：已有的完整路线规划结果。
        request：用户原始规划请求。
        transport_mode：交通方式说明。
        preferences：用户偏好列表；为空时使用 request.preferences。
    返回值：
        返回补齐 days[].itinerary_detail 的路线结果。
    """
    warnings = list(route_plan.warnings)
    api_key = read_optional_amap_key()
    active_preferences = preferences if preferences is not None else request.preferences
    image_service = get_unsplash_service()
    image_warnings = enrich_spot_images(route_plan, image_service)
    warnings.extend(image_warnings)
    for day in route_plan.days:
        day_date = trip_day_date(request.start_date, day.day_index)
        detail, detail_warnings = build_day_detail(
            day,
            destination=route_plan.destination,
            day_date=day_date,
            api_key=api_key,
            preferences=active_preferences,
            transport_mode=transport_mode or route_plan.route_mode,
            image_service=image_service,
        )
        day.itinerary_detail = detail
        warnings.extend(f"day {day.day_index}: {warning}" for warning in detail_warnings)
    route_plan.warnings = warnings
    return route_plan


def enrich_spot_images(route_plan: TripRoutePlanResponse, service: UnsplashService) -> list[str]:
    """功能：为行程详情页中的景点补充 Unsplash 图片。

    参数：
        route_plan：完整路线规划结果，会原地写入 spots[].image_url 等字段。
        service：Unsplash 图片服务。
    返回值：
        返回图片搜索警告列表；未配置 Unsplash 时返回空列表。
    """
    if not service.is_configured():
        return []
    warnings: list[str] = []
    photo_cache: dict[str, dict[str, Any] | None] = {}
    used_photo_keys: set[str] = set()
    for day in route_plan.days:
        for spot in day.spots:
            if spot.image_url:
                used_photo_keys.add(photo_identity({"url": spot.image_url, "id": spot.image_url}))
                continue
            photo, search_warnings = search_spot_photo_with_agent(
                service,
                route_plan.destination,
                spot.name,
                photo_cache,
                poi_type=spot.poi_type,
                used_photo_keys=used_photo_keys,
            )
            warnings.extend(search_warnings)
            apply_spot_photo(spot, photo)
            if photo:
                used_photo_keys.add(photo_identity(photo))
    return warnings


def image_query_for_spot(destination: str, spot_name: str) -> str:
    """功能：构造更适合景点图片检索的关键词。

    参数：
        destination：目的地城市。
        spot_name：景点名称。
    返回值：
        返回 Unsplash 搜索关键词。
    """
    return f"{destination} {spot_name} landmark travel"


def search_spot_photo_with_agent(
    service: UnsplashService,
    destination: str,
    spot_name: str,
    photo_cache: dict[str, dict[str, Any] | None] | None = None,
    *,
    poi_type: str | None = None,
    max_attempts: int = MAX_IMAGE_SEARCH_ATTEMPTS,
    used_photo_keys: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """功能：用多轮 Unsplash query 尽可能为单个景点找到图片。

    参数：
        service：Unsplash 图片服务。
        destination：目的地城市。
        spot_name：景点名称。
        photo_cache：跨景点复用的 query -> 图片缓存。
        poi_type：高德 POI 类型，用于辅助 DeepSeek 判断景点类别。
        max_attempts：最多尝试的 query 数量，避免图片搜索无限重试。
        used_photo_keys：已分配给其他景点的图片标识，命中重复图片时继续尝试后续 query。
    返回值：
        返回命中的图片字典和搜索警告列表；没有命中时图片为 None。
    """
    warnings: list[str] = []
    cache = photo_cache if photo_cache is not None else {}
    attempts = max(1, max_attempts)
    try:
        llm_queries = build_llm_image_queries(
            destination=destination,
            spot_name=spot_name,
            poi_type=poi_type,
            max_queries=attempts,
        )
    except Exception as exc:
        llm_queries = []
        warnings.append(f"{spot_name} 图片搜索 query 生成失败，已使用规则兜底：{exc}")
    for query in image_queries_for_spot(destination, spot_name, llm_queries=llm_queries)[:attempts]:
        if query not in cache:
            try:
                cache[query] = service.get_photo(query)
            except Exception as exc:
                cache[query] = None
                warnings.append(f"{spot_name} 图片搜索失败：query={query}；{exc}")
        if cache[query] and photo_identity(cache[query]) in (used_photo_keys or set()):
            continue
        if cache[query]:
            return cache[query], warnings
    return None, warnings


def photo_identity(photo: dict[str, Any] | None) -> str:
    """功能：生成图片去重标识，优先使用 Unsplash id，其次使用图片 URL。

    参数：
        photo：图片字典，可为空。
    返回值：
        返回用于跨景点去重的稳定字符串；没有可用字段时返回空字符串。
    """
    if not photo:
        return ""
    return str(photo.get("id") or photo.get("url") or "").strip()


def build_llm_image_queries(
    *,
    destination: str,
    spot_name: str,
    poi_type: str | None,
    max_queries: int,
) -> list[str]:
    """功能：调用 DeepSeek 为 Unsplash 图片搜索生成多条高命中 query。

    参数：
        destination：目的地城市。
        spot_name：景点名称。
        poi_type：高德 POI 类型，可为空。
        max_queries：最多返回的 query 数量。
    返回值：
        返回 DeepSeek 生成并清洗后的搜索词列表。
    """
    llm = build_image_search_query_llm()
    prompt = (
        "你是 FloatTrip 图片搜索 Agent。请为 Unsplash Search Photos API 生成图片搜索 query，"
        "目标是尽可能搜到该景点或最接近的片区/地标照片。"
        "\n要求："
        "\n- 优先输出英文官方名、常用英文名、拼音名、所在片区英文名。"
        "\n- Unsplash 对中文景点名命中不稳定，除非非常必要，不要只输出中文。"
        "\n- 如果具体景点可能没有图，给出同片区、同河流、同山体、同城市地标兜底 query。"
        "\n- 不要输出 hotel、restaurant、ticket、map、logo、illustration。"
        f"\n- 最多输出 {max_queries} 条，按最可能命中的顺序排列。"
        f"\n目的地：{destination}"
        f"\n景点：{spot_name}"
        f"\nPOI 类型：{poi_type or '未知'}"
    )
    plan = llm.invoke(
        [
            ("system", "只返回结构化 query 列表，不要解释。"),
            ("user", prompt),
        ]
    )
    if isinstance(plan, ImageSearchQueryPlan):
        return dedupe_image_queries(plan.queries)[:max_queries]
    if isinstance(plan, dict):
        return dedupe_image_queries([str(query) for query in plan.get("queries", [])])[:max_queries]
    raise RuntimeError("DeepSeek 未返回图片搜索 query 计划")


def build_image_search_query_llm() -> Any:
    """功能：创建用于图片搜索 query 规划的 DeepSeek 结构化输出模型。

    参数：
        无。
    返回值：
        返回绑定 ImageSearchQueryPlan 的 LangChain 模型。
    """
    travel_research.load_local_env()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx 或 langchain-openai") from exc
    model = travel_research.normalize_deepseek_model(
        os.getenv("DEEPSEEK_MODEL", travel_research.DEFAULT_DEEPSEEK_MODEL)
    )
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=travel_research.DEEPSEEK_BASE_URL,
        temperature=0,
        http_client=httpx.Client(proxy=travel_research.choose_http_proxy(), trust_env=False),
        http_async_client=httpx.AsyncClient(proxy=travel_research.choose_http_proxy(), trust_env=False),
        http_socket_options=(),
        extra_body={"thinking": {"type": "disabled"}},
    )
    return llm.with_structured_output(ImageSearchQueryPlan, method="function_calling", strict=True)


def image_queries_for_spot(
    destination: str,
    spot_name: str,
    *,
    llm_queries: list[str] | None = None,
) -> list[str]:
    """功能：为图片搜索 Agent 生成多级 Unsplash 检索 query。

    参数：
        destination：目的地城市。
        spot_name：景点名称。
        llm_queries：DeepSeek 生成的优先搜索词。
    返回值：
        返回按优先级排序且去重后的图片搜索 query 列表。
    """
    clean_destination = normalize_image_query_part(destination)
    clean_spot_name = normalize_image_query_part(spot_name)
    if not clean_spot_name:
        return dedupe_image_queries([f"{clean_destination} travel"])

    aliases = aliases_for_spot_image_query(clean_spot_name)
    return dedupe_image_queries(
        [
            *(llm_queries or []),
            image_query_for_spot(clean_destination, clean_spot_name),
            f"{clean_spot_name} {clean_destination} travel",
            *aliases,
            f"{clean_destination} {clean_spot_name}",
            f"{clean_destination} landmark travel",
            f"{clean_destination} travel",
        ]
    )


def aliases_for_spot_image_query(spot_name: str) -> list[str]:
    """功能：根据景点中文名返回适合 Unsplash 的英文名、拼音名和片区名。

    参数：
        spot_name：景点名称。
    返回值：
        返回可能命中 Unsplash 图片库的别名 query 列表。
    """
    aliases: list[str] = []
    for key, values in SPOT_IMAGE_QUERY_ALIASES.items():
        if key in spot_name or spot_name in key:
            aliases.extend(values)
    return aliases


def normalize_image_query_part(value: str) -> str:
    """功能：清理图片搜索关键词中的空白和城市后缀。

    参数：
        value：目的地或景点名称。
    返回值：
        返回适合拼入 Unsplash query 的文本。
    """
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    return re.sub(r"市$", "", cleaned)


def dedupe_image_queries(queries: list[str]) -> list[str]:
    """功能：按原顺序去重图片搜索 query。

    参数：
        queries：候选 query 列表。
    返回值：
        返回清理空白后的去重 query 列表。
    """
    deduped_queries: list[str] = []
    seen_queries: set[str] = set()
    for query in queries:
        cleaned = re.sub(r"\s+", " ", str(query or "").strip())
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen_queries:
            continue
        deduped_queries.append(cleaned)
        seen_queries.add(key)
    return deduped_queries


def apply_spot_photo(spot: Any, photo: dict[str, Any] | None) -> None:
    """功能：把图片结果写入景点模型。

    参数：
        spot：SpotMapItem 景点模型。
        photo：Unsplash 图片字典；为空时不写入。
    返回值：
        无返回值。
    """
    if not photo:
        return
    spot.image_url = str(photo.get("url") or "") or None
    spot.image_thumb_url = str(photo.get("thumb") or "") or None
    spot.image_description = str(photo.get("description") or "") or None
    spot.image_photographer = str(photo.get("photographer") or "") or None


def day_theme_image_queries(destination: str, day_theme: str, route_names: list[str]) -> list[str]:
    """功能：为每日摘要封面图生成主题化 Unsplash 搜索词。

    参数：
        destination：目的地城市。
        day_theme：当天主题标题。
        route_names：当天景点名称列表。
    返回值：
        返回按优先级排序且去重后的封面图搜索词。
    """
    clean_destination = normalize_image_query_part(destination)
    clean_theme = normalize_image_query_part(day_theme)
    route_text = " ".join(normalize_image_query_part(name) for name in route_names[:3] if name)
    queries = [
        f"{clean_destination} {clean_theme} travel landscape",
        f"{clean_destination} {route_text} travel",
        f"{clean_destination} skyline landmark travel",
        f"{clean_destination} travel scenery",
    ]
    return dedupe_image_queries(queries)


def search_day_theme_photo_with_agent(
    service: UnsplashService,
    destination: str,
    day_theme: str,
    route_names: list[str],
    *,
    used_photo_keys: set[str] | None = None,
    max_attempts: int = MAX_IMAGE_SEARCH_ATTEMPTS,
) -> tuple[dict[str, Any] | None, list[str]]:
    """功能：按每日主题搜索摘要卡封面图，避免复用景点图。

    参数：
        service：Unsplash 图片服务。
        destination：目的地城市。
        day_theme：当天主题标题。
        route_names：当天景点名称列表。
        used_photo_keys：已用于景点卡的图片标识。
        max_attempts：最多尝试的 query 数量。
    返回值：
        返回命中的主题图片和警告列表；未命中时图片为 None。
    """
    warnings: list[str] = []
    if not service.is_configured():
        return None, warnings
    try:
        llm_queries = build_llm_image_queries(
            destination=destination,
            spot_name=day_theme,
            poi_type="每日行程主题封面图",
            max_queries=max_attempts,
        )
    except Exception as exc:
        llm_queries = []
        warnings.append(f"{day_theme} 主题封面图 query 生成失败，已使用规则兜底：{exc}")
    queries = dedupe_image_queries([*llm_queries, *day_theme_image_queries(destination, day_theme, route_names)])
    for query in queries[: max(1, max_attempts)]:
        try:
            photo = service.get_photo(query)
        except Exception as exc:
            warnings.append(f"{day_theme} 主题封面图搜索失败：query={query}；{exc}")
            continue
        if not photo:
            continue
        if photo_identity(photo) in (used_photo_keys or set()):
            continue
        return photo, warnings
    return None, warnings


def spot_photo_for_day(day: DayRoutePlan) -> dict[str, Any] | None:
    """功能：选择当天第一个可用景点图片作为摘要卡兜底图。

    参数：
        day：单日路线规划。
    返回值：
        返回图片字典；当天没有景点图时返回 None。
    """
    for spot in ordered_spots_for_day(day):
        if spot.image_url:
            return {
                "url": spot.image_url,
                "thumb": spot.image_thumb_url,
                "description": spot.image_description,
                "photographer": spot.image_photographer,
            }
    return None


def day_hero_photo_fields(photo: dict[str, Any] | None, source: str | None) -> dict[str, Any]:
    """功能：把封面图字典转换为 DayItineraryDetail 字段。

    参数：
        photo：主题图或景点兜底图。
        source：theme 或 spot。
    返回值：
        返回可传入 DayItineraryDetail 的封面图字段。
    """
    if not photo:
        return {}
    return {
        "hero_image_url": str(photo.get("url") or "") or None,
        "hero_image_thumb_url": str(photo.get("thumb") or "") or None,
        "hero_image_description": str(photo.get("description") or "") or None,
        "hero_image_photographer": str(photo.get("photographer") or "") or None,
        "hero_image_source": source,
    }


def build_day_detail(
    day: DayRoutePlan,
    *,
    destination: str,
    day_date: date | None,
    api_key: str | None,
    preferences: list[str],
    transport_mode: str,
    image_service: UnsplashService | None = None,
) -> tuple[DayItineraryDetail, list[str]]:
    """功能：为单日路线生成时间线、餐饮、天气和注意事项。

    参数：
        day：单日路线规划。
        destination：目的地城市。
        day_date：当前旅行日期。
        api_key：高德 Web 服务 Key，可为空。
        preferences：用户偏好。
        transport_mode：交通方式说明。
        image_service：Unsplash 图片服务，可为空；用于搜索每日摘要卡主题封面图。
    返回值：
        返回单日详情和警告列表。
    """
    warnings: list[str] = []
    original_route = ordered_spot_names(day)
    weather, weather_warning = build_weather(destination, day_date, api_key)
    if weather_warning:
        warnings.append(weather_warning)
    meals, meal_warnings = build_meal_recommendations(day, api_key)
    warnings.extend(meal_warnings)
    try:
        day_theme = build_llm_day_theme(
            destination=destination,
            weather=weather,
            original_route=original_route,
            meals=meals,
            preferences=preferences,
            transport_mode=transport_mode,
        )
    except Exception as exc:
        day_theme = fallback_day_theme(destination, original_route)
        warnings.append(f"每日主题 LLM 生成失败，已使用规则兜底：{exc}")
    theme_photo = None
    if image_service:
        used_spot_photo_keys = {photo_identity({"url": spot.image_url, "id": spot.image_url}) for spot in day.spots if spot.image_url}
        theme_photo, theme_photo_warnings = search_day_theme_photo_with_agent(
            image_service,
            destination,
            day_theme,
            original_route,
            used_photo_keys=used_spot_photo_keys,
        )
        warnings.extend(theme_photo_warnings)
    hero_photo = theme_photo or spot_photo_for_day(day)
    hero_photo_source = "theme" if theme_photo else ("spot" if hero_photo else None)
    activities = build_activities(day, meals)
    notices, notice_warnings = build_notices(
        day,
        weather,
        original_route=original_route,
        preferences=preferences,
        transport_mode=transport_mode,
    )
    warnings.extend(notice_warnings)
    return (
        DayItineraryDetail(
            original_route=original_route,
            day_theme=day_theme,
            **day_hero_photo_fields(hero_photo, hero_photo_source),
            weather=weather,
            activities=activities,
            meals=meals,
            notices=notices,
        ),
        warnings,
    )


def read_optional_amap_key() -> str | None:
    """功能：读取高德 Web 服务 Key，缺失时返回 None。

    参数：
        无。
    返回值：
        返回高德 Key 或 None。
    """
    try:
        return amap.require_amap_key()
    except RuntimeError:
        return None


def trip_day_date(start_date: date | None, day_index: int) -> date | None:
    """功能：根据出行开始日期和天序号计算当天日期。

    参数：
        start_date：出行开始日期。
        day_index：第几天，从 1 开始。
    返回值：
        返回当天日期；没有开始日期时返回 None。
    """
    if not start_date:
        return None
    return start_date + timedelta(days=day_index - 1)


def build_weather(destination: str, day_date: date | None, api_key: str | None) -> tuple[DayWeather, str | None]:
    """功能：查询并整理当日天气。

    参数：
        destination：目的地城市。
        day_date：查询日期。
        api_key：高德 Web 服务 Key。
    返回值：
        返回天气结构和可选警告。
    """
    if not day_date:
        return (
            DayWeather(
                city=destination,
                status="missing_start_date",
                dressing_advice="未提供出行日期，建议出发前查看实时天气并准备轻便雨具。",
            ),
            None,
        )
    weather_warning: str | None = None
    try:
        casts = amap_mcp.query_weather(city=destination)
    except Exception as exc:
        casts = []
        weather_warning = f"高德 MCP 天气查询失败：{exc}"

    if not casts and not api_key:
        return (
            DayWeather(
                date=day_date,
                city=destination,
                status="unavailable",
                dressing_advice="暂未配置可用高德天气能力，建议出发前查看实时天气。",
            ),
            weather_warning or "天气查询跳过：缺少 AMAP_API_KEY 和 AMAP_MCP_URL",
        )
    if not casts and api_key:
        try:
            casts = amap.query_weather(destination, api_key)
            weather_warning = None
        except Exception as exc:
            return (
                DayWeather(
                    date=day_date,
                    city=destination,
                    status="unavailable",
                    dressing_advice="天气暂不可用，建议携带雨具并按季节准备外套。",
                ),
                f"{weather_warning}；高德 Web 天气查询失败：{exc}" if weather_warning else f"高德天气查询失败：{exc}",
            )
    target = next((cast for cast in casts if cast.get("date") == day_date.isoformat()), None)
    if not target:
        nearest = latest_available_weather(casts)
        if nearest:
            nearest_date = parse_weather_date(nearest.get("date"))
            weather_text = str(nearest.get("dayweather") or nearest.get("nightweather") or "")
            temperature = format_temperature(nearest)
            wind = str(nearest.get("daywind") or nearest.get("nightwind") or "")
            available_until = nearest_date.isoformat() if nearest_date else str(nearest.get("date") or "近几日")
            return (
                DayWeather(
                    date=nearest_date,
                    city=destination,
                    status="unavailable",
                    weather=weather_text,
                    temperature=temperature,
                    wind=wind,
                    dressing_advice=(
                        f"出行日 {day_date.isoformat()} 超出当前可预报范围。"
                        f"高德目前可参考到 {available_until}：{weather_text or '天气待确认'}"
                        f"{f'，{temperature}' if temperature else ''}；临近出行前请再次确认。"
                    ),
                ),
                weather_warning or f"天气日期超出高德可预报范围，已展示 {available_until} 参考天气",
            )
        return (
            DayWeather(
                date=day_date,
                city=destination,
                status="unavailable",
                dressing_advice="该日期超出当前可预报范围，建议临近出行前再确认天气。",
            ),
            weather_warning or "天气日期超出高德可预报范围",
        )
    weather_text = str(target.get("dayweather") or target.get("nightweather") or "")
    temperature = format_temperature(target)
    wind = str(target.get("daywind") or target.get("nightwind") or "")
    return (
        DayWeather(
            date=day_date,
            city=destination,
            status="ok",
            weather=weather_text,
            temperature=temperature,
            wind=wind,
            dressing_advice=dressing_advice(weather_text, temperature),
        ),
        None,
    )


def latest_available_weather(casts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """功能：从高德预报列表里选择日期最晚的一条作为远期出行参考。

    参数：
        casts：高德天气 forecast cast 字典列表。
    返回值：
        返回日期最晚的天气字典；没有可用日期时返回 None。
    """
    dated_casts = [
        (parsed_date, cast)
        for cast in casts
        if (parsed_date := parse_weather_date(cast.get("date"))) is not None
    ]
    if not dated_casts:
        return None
    return max(dated_casts, key=lambda item: item[0])[1]


def parse_weather_date(value: Any) -> date | None:
    """功能：解析高德天气日期字符串。

    参数：
        value：高德 date 字段。
    返回值：
        返回日期对象；解析失败返回 None。
    """
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def format_temperature(cast: dict[str, Any]) -> str | None:
    """功能：格式化高德天气温度区间。

    参数：
        cast：高德天气 forecast cast 字典。
    返回值：
        返回温度文本。
    """
    day_temp = str(cast.get("daytemp") or "").strip()
    night_temp = str(cast.get("nighttemp") or "").strip()
    if day_temp and night_temp:
        return f"{night_temp}-{day_temp}°C"
    return f"{day_temp or night_temp}°C" if day_temp or night_temp else None


def dressing_advice(weather: str, temperature: str | None) -> str:
    """功能：根据天气文本和温度给出穿衣建议。

    参数：
        weather：天气描述。
        temperature：温度区间文本。
    返回值：
        返回穿衣建议。
    """
    if any(word in weather for word in ("雨", "雪", "雷")):
        return f"{temperature or '气温待确认'}，建议穿防滑舒适鞋并随身带伞。"
    if temperature and any(token in temperature for token in ("0-", "1-", "2-", "3-", "4-", "5-")):
        return f"{temperature}，早晚偏冷，建议穿外套并注意保暖。"
    return f"{temperature or '气温待确认'}，建议穿轻便舒适衣物和适合步行的鞋。"


def build_meal_recommendations(day: DayRoutePlan, api_key: str | None = None) -> tuple[list[MealRecommendation], list[str]]:
    """功能：为当天午餐和晚餐搜索并生成餐厅推荐。

    参数：
        day：单日路线规划。
        api_key：高德 Web 服务 Key，可为空；MCP 不可用时用于 Web 周边搜索兜底。
    返回值：
        返回餐厅推荐列表和警告列表。
    """
    warnings: list[str] = []
    ordered_spots = ordered_spots_for_day(day)
    lunch_anchor = meal_anchor_for_type(ordered_spots, "lunch")
    dinner_anchor = meal_anchor_for_type(ordered_spots, "dinner")
    meals: list[MealRecommendation] = []
    for meal_type, anchor in (("lunch", lunch_anchor), ("dinner", dinner_anchor)):
        if not anchor:
            continue
        meal, warning = restaurant_for_anchor(meal_type, anchor, api_key)
        meals.append(meal)
        if warning:
            warnings.append(warning)
    return meals, warnings


def meal_anchor_for_type(ordered_spots: list[Any], meal_type: str) -> Any | None:
    """功能：为午餐和晚餐选择更符合时间线的餐饮搜索锚点。

    参数：
        ordered_spots：当天按访问顺序排列的景点。
        meal_type：lunch 或 dinner。
    返回值：
        返回用于周边餐饮搜索的景点；无景点时返回 None。
    """
    if not ordered_spots:
        return None
    if meal_type == "lunch":
        return ordered_spots[0] if len(ordered_spots) <= 2 else ordered_spots[1]
    dinner_anchor = ordered_spots[-1] if ordered_spots else None
    return dinner_anchor


def restaurant_for_anchor(meal_type: str, anchor: Any, api_key: str | None = None) -> tuple[MealRecommendation, str | None]:
    """功能：围绕景点调用高德 MCP 搜索餐厅并生成推荐。

    参数：
        meal_type：lunch 或 dinner。
        anchor：餐厅搜索锚点景点。
        api_key：高德 Web 服务 Key，可为空。
    返回值：
        返回餐厅推荐和可选警告。
    """
    first_warning: str | None = None
    for radius in (DEFAULT_RESTAURANT_RADIUS, EXPANDED_RESTAURANT_RADIUS):
        try:
            pois = amap_mcp.search_nearby_pois(
                keywords=meal_keyword(meal_type),
                location=anchor.location.model_dump(),
                radius=radius,
                limit=3,
            )
        except Exception as exc:
            first_warning = f"{anchor.name} 周边餐厅 MCP 搜索失败：{exc}"
            break
        if pois:
            poi = pois[0]
            return meal_from_poi(meal_type, anchor.name, poi), None
    if api_key:
        for radius in (DEFAULT_RESTAURANT_RADIUS, EXPANDED_RESTAURANT_RADIUS):
            try:
                pois = amap.search_around_pois(
                    meal_keyword(meal_type),
                    anchor.location.model_dump(),
                    api_key,
                    radius=radius,
                    offset=5,
                )
            except Exception as exc:
                warning = f"{anchor.name} 周边餐厅 Web 搜索失败：{exc}"
                return fallback_meal(meal_type, anchor), f"{first_warning}；{warning}" if first_warning else warning
            if pois:
                poi = amap.normalize_poi(pois[0])
                return meal_from_poi(meal_type, anchor.name, poi), first_warning
    return fallback_meal(meal_type, anchor), f"{anchor.name} 周边未搜索到餐厅 POI"


def meal_keyword(meal_type: str) -> str:
    """功能：根据用餐类型选择更贴近场景的餐饮搜索关键词。

    参数：
        meal_type：lunch 或 dinner。
    返回值：
        返回用于高德搜索的关键词。
    """
    return "餐厅" if meal_type == "lunch" else "特色餐厅"


def meal_from_poi(meal_type: str, anchor_name: str, poi: dict[str, Any]) -> MealRecommendation:
    """功能：把高德 MCP POI 转换成餐厅推荐。

    参数：
        meal_type：lunch 或 dinner。
        anchor_name：锚点景点名称。
        poi：高德 MCP POI。
    返回值：
        返回餐厅推荐结构。
    """
    location = poi.get("location")
    location_model = Location(**location) if isinstance(location, dict) else None
    name = str(poi.get("name") or "附近餐厅")
    return MealRecommendation(
        meal_type=meal_type,  # type: ignore[arg-type]
        restaurant_name=name,
        address=str(poi.get("address") or "") or None,
        location=location_model,
        distance_meters=poi.get("distance_meters") if isinstance(poi.get("distance_meters"), int) else None,
        reason=f"靠近{anchor_name}，适合在当前路线节奏中就近用餐，减少额外折返。",
        source_poi=poi,
    )


def fallback_meal(meal_type: str, anchor: Any) -> MealRecommendation:
    """功能：当 MCP 搜索失败时生成兜底餐饮建议。

    参数：
        meal_type：lunch 或 dinner。
        anchor：锚点景点。
    返回值：
        返回兜底餐厅推荐。
    """
    label = "午餐" if meal_type == "lunch" else "晚餐"
    return MealRecommendation(
        meal_type=meal_type,  # type: ignore[arg-type]
        restaurant_name=f"{anchor.name}周边{label}",
        address=anchor.address,
        location=anchor.location,
        reason=f"围绕{anchor.name}就近安排{label}，方便衔接前后景点。",
        source_poi={},
    )


def build_activities(day: DayRoutePlan, meals: list[MealRecommendation]) -> list[ItineraryActivity]:
    """功能：生成单日活动时间线。

    参数：
        day：单日路线规划。
        meals：午餐和晚餐推荐。
    返回值：
        返回按时间排序的活动列表。
    """
    ordered_spots = ordered_spots_for_day(day)
    if len(ordered_spots) == 1:
        return build_single_spot_day_activities(day, ordered_spots[0], meals)
    if len(ordered_spots) == 2:
        return build_two_spot_day_activities(day, ordered_spots, meals)

    activities: list[ItineraryActivity] = []
    cursor = DAY_START_MINUTE
    spot_duration = COMPACT_SPOT_DURATION if len(ordered_spots) >= 4 else DEFAULT_SPOT_DURATION
    meal_by_type = {meal.meal_type: meal for meal in meals}

    for index, spot in enumerate(ordered_spots):
        if index >= 1 and "lunch" in meal_by_type and cursor >= LUNCH_TARGET - 45:
            activities.append(meal_activity(meal_by_type.pop("lunch"), max(cursor, LUNCH_TARGET)))
            cursor = time_to_minute(activities[-1].end_time)
        start = cursor
        end = min(start + spot_duration, DAY_END_MINUTE)
        activities.append(spot_activity(day, spot, start, end))
        transit_minutes = transit_buffer_after(day, index)
        if index < len(ordered_spots) - 1:
            transit_end = min(end + transit_minutes, DAY_END_MINUTE)
            next_spot = ordered_spots[index + 1]
            activities.append(transit_activity(day, next_spot, end, transit_end))
            cursor = transit_end
        else:
            cursor = end + 20

    for meal in meal_by_type.values():
        meal_target = LUNCH_TARGET if meal.meal_type == "lunch" else DINNER_TARGET
        meal_start = max(cursor, meal_target)
        if meal_start + MEAL_DURATION <= DAY_END_MINUTE:
            activities.append(meal_activity(meal, meal_start))

    return sorted(activities, key=lambda activity: activity.start_time)


def build_single_spot_day_activities(
    day: DayRoutePlan,
    spot: Any,
    meals: list[MealRecommendation],
) -> list[ItineraryActivity]:
    """功能：单景点日拆成上午和下午两段游览，避免午餐后到晚餐前没有景点。

    参数：
        day：单日路线规划。
        spot：当天唯一景点。
        meals：午晚餐推荐。
    返回值：
        返回上午景点、午餐、下午景点、晚餐的时间线。
    """
    meal_by_type = {meal.meal_type: meal for meal in meals}
    activities = [
        spot_activity(day, spot, DAY_START_MINUTE, LUNCH_TARGET - 25, period="上午"),
    ]
    if lunch := meal_by_type.get("lunch"):
        activities.append(meal_activity(lunch, LUNCH_TARGET))
    afternoon_start = time_to_minute(activities[-1].end_time) + 20
    activities.append(
        spot_activity(
            day,
            spot,
            afternoon_start,
            min(afternoon_start + 120, DINNER_TARGET - 45),
            period="下午",
        )
    )
    if dinner := meal_by_type.get("dinner"):
        activities.append(meal_activity(dinner, DINNER_TARGET))
    return sorted(activities, key=lambda activity: activity.start_time)


def build_two_spot_day_activities(
    day: DayRoutePlan,
    ordered_spots: list[Any],
    meals: list[MealRecommendation],
) -> list[ItineraryActivity]:
    """功能：双景点日固定为上午一个景点、下午一个景点，午餐和晚餐之间保留游览。

    参数：
        day：单日路线规划。
        ordered_spots：当天两个景点，按访问顺序排列。
        meals：午晚餐推荐。
    返回值：
        返回上午景点、午餐、交通、下午景点、晚餐的时间线。
    """
    first_spot, second_spot = ordered_spots
    meal_by_type = {meal.meal_type: meal for meal in meals}
    activities = [
        spot_activity(day, first_spot, DAY_START_MINUTE, LUNCH_TARGET - 25, period="上午"),
    ]
    if lunch := meal_by_type.get("lunch"):
        activities.append(meal_activity(lunch, LUNCH_TARGET))
    transit_start = time_to_minute(activities[-1].end_time) + 10
    transit_end = min(transit_start + transit_buffer_after(day, 0), DINNER_TARGET - 150)
    activities.append(transit_activity(day, second_spot, transit_start, transit_end))
    afternoon_start = transit_end
    activities.append(
        spot_activity(
            day,
            second_spot,
            afternoon_start,
            min(afternoon_start + DEFAULT_SPOT_DURATION, DINNER_TARGET - 45),
            period="下午",
        )
    )
    if dinner := meal_by_type.get("dinner"):
        activities.append(meal_activity(dinner, DINNER_TARGET))
    return sorted(activities, key=lambda activity: activity.start_time)


def spot_activity(
    day: DayRoutePlan,
    spot: Any,
    start: int,
    end: int,
    *,
    period: str | None = None,
) -> ItineraryActivity:
    """功能：把景点转换为时间线活动。

    参数：
        day：单日路线规划。
        spot：景点模型。
        start：开始时间，单位分钟。
        end：结束时间，单位分钟。
        period：上午或下午等时段说明，可为空。
    返回值：
        返回景点活动结构。
    """
    suffix = f"（{period}）" if period else ""
    description_prefix = f"{period}继续" if period == "下午" else "按既有路线"
    return ItineraryActivity(
        type="spot",
        start_time=minute_to_time(start),
        end_time=minute_to_time(end),
        title=f"{spot.name}{suffix}",
        description=f"{description_prefix}游览{spot.name}，建议保留拍照、休息和排队缓冲。",
        location=spot.location,
        related_spot_id=spot.spot_id,
        travel_summary=segment_summary_for_spot(day, spot.spot_id),
        tag=spot.poi_type or "景点游览",
    )


def transit_activity(day: DayRoutePlan, next_spot: Any, start: int, end: int) -> ItineraryActivity:
    """功能：生成前往下一景点的交通衔接活动。

    参数：
        day：单日路线规划。
        next_spot：下一站景点。
        start：开始时间，单位分钟。
        end：结束时间，单位分钟。
    返回值：
        返回交通活动结构。
    """
    return ItineraryActivity(
        type="transit",
        start_time=minute_to_time(start),
        end_time=minute_to_time(end),
        title=f"前往{next_spot.name}",
        description="根据后端高德路线结果预留交通和步行缓冲。",
        related_spot_id=next_spot.spot_id,
        travel_summary=segment_summary_for_spot(day, next_spot.spot_id),
        tag="交通衔接",
    )


def meal_activity(meal: MealRecommendation, start: int) -> ItineraryActivity:
    """功能：把餐厅推荐转换成时间线活动。

    参数：
        meal：餐厅推荐。
        start：开始时间，单位分钟。
    返回值：
        返回活动结构。
    """
    end = min(start + MEAL_DURATION, DAY_END_MINUTE)
    title = ("午餐推荐：" if meal.meal_type == "lunch" else "晚餐推荐：") + meal.restaurant_name
    return ItineraryActivity(
        type="meal",
        start_time=minute_to_time(start),
        end_time=minute_to_time(end),
        title=title,
        description=meal.reason,
        location=meal.location,
        travel_summary=meal.address,
        tag="餐饮推荐",
    )


def build_llm_day_theme(
    *,
    destination: str,
    weather: DayWeather,
    original_route: list[str],
    meals: list[MealRecommendation],
    preferences: list[str],
    transport_mode: str,
) -> str:
    """功能：调用 DeepSeek 生成当天行程主题标题。

    参数：
        destination：目的地城市。
        weather：当日天气。
        original_route：当天景点顺序。
        meals：当天午晚餐推荐。
        preferences：用户偏好。
        transport_mode：交通方式说明。
    返回值：
        返回不包含 Day 前缀的中文短主题。
    """
    llm = build_day_theme_llm()
    meal_names = [meal.restaurant_name for meal in meals if meal.restaurant_name]
    prompt = (
        "请为 FloatTrip 的单日旅行行程生成一个展示在页面顶部的中文主题标题。"
        "要求：只输出主题本身，不要包含 Day、日期、标点包裹或解释；"
        "8-18 个汉字左右，语气轻松自然，能概括当天路线特色。"
        f"\n目的地：{destination}"
        f"\n天气：{weather.weather or '未知'} {weather.temperature or ''}"
        f"\n景点顺序：{' -> '.join(original_route) if original_route else '未知'}"
        f"\n餐饮：{'、'.join(meal_names) if meal_names else '无'}"
        f"\n交通方式：{transport_mode}"
        f"\n用户偏好：{'、'.join(preferences) if preferences else '无'}"
    )
    draft = llm.invoke([("system", "输出中文短标题，避免营销腔。"), ("user", prompt)])
    if not isinstance(draft, DayThemeDraft):
        raise RuntimeError("DeepSeek 未返回每日主题结构化结果")
    return normalize_day_theme(draft.theme) or fallback_day_theme(destination, original_route)


def build_day_theme_llm() -> Any:
    """功能：创建用于每日主题标题的 DeepSeek 结构化输出模型。

    参数：
        无。
    返回值：
        返回绑定 DayThemeDraft 的 LangChain 模型。
    """
    travel_research.load_local_env()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx 或 langchain-openai") from exc
    model = travel_research.normalize_deepseek_model(
        os.getenv("DEEPSEEK_MODEL", travel_research.DEFAULT_DEEPSEEK_MODEL)
    )
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=travel_research.DEEPSEEK_BASE_URL,
        temperature=0,
        http_client=httpx.Client(proxy=travel_research.choose_http_proxy(), trust_env=False),
        http_async_client=httpx.AsyncClient(proxy=travel_research.choose_http_proxy(), trust_env=False),
        http_socket_options=(),
        extra_body={"thinking": {"type": "disabled"}},
    )
    return llm.with_structured_output(DayThemeDraft, method="function_calling", strict=True)


def normalize_day_theme(theme: str | None) -> str:
    """功能：清洗 LLM 返回的每日主题标题。

    参数：
        theme：LLM 生成的标题文本。
    返回值：
        返回去除 Day 前缀、引号和多余空白后的短标题。
    """
    text = (theme or "").strip().strip("「」《》“”\"'")
    text = re.sub(r"^Day\s*\d*\s*[·\-—:：]?\s*", "", text, flags=re.IGNORECASE)
    return text[:18]


def fallback_day_theme(destination: str, original_route: list[str]) -> str:
    """功能：在 LLM 不可用时根据景点顺序生成每日主题兜底标题。

    参数：
        destination：目的地城市。
        original_route：当天景点顺序。
    返回值：
        返回用于页面展示的中文短主题。
    """
    route = [name for name in original_route if name]
    if len(route) >= 2:
        return normalize_day_theme(f"{route[0]}与{route[-1]}一日游")
    if len(route) == 1:
        return normalize_day_theme(f"{route[0]}深度慢游")
    return normalize_day_theme(f"{destination}轻松一日游")


def build_notices(
    day: DayRoutePlan,
    weather: DayWeather,
    *,
    original_route: list[str],
    preferences: list[str],
    transport_mode: str,
) -> tuple[list[DayNotice], list[str]]:
    """功能：生成天气、路线和高峰提醒。

    参数：
        day：单日路线规划。
        weather：当日天气。
        preferences：用户偏好。
        transport_mode：交通方式说明。
    返回值：
        返回注意事项列表和警告列表。
    """
    warnings: list[str] = []
    notices = [
        DayNotice(
            level="info",
            title="路线节奏",
            content=f"今日按{transport_mode}串联 {len(day.spots)} 个景点，建议每段交通前预留 10-15 分钟缓冲。",
            basis="route",
        )
    ]
    if weather.dressing_advice:
        notices.append(
            DayNotice(
                level="info",
                title="天气穿搭",
                content=weather.dressing_advice,
                basis="weather",
            )
        )
    try:
        crowd_notice = build_llm_crowd_notice(
            day,
            weather=weather,
            original_route=original_route,
            preferences=preferences,
            transport_mode=transport_mode,
        )
    except Exception as exc:
        crowd_notice = fallback_crowd_notice(weather.date, preferences)
        warnings.append(f"高峰提醒 LLM 生成失败，已使用规则兜底：{exc}")
    if crowd_notice:
        notices.append(crowd_notice)
    return notices, warnings


def build_llm_crowd_notice(
    day: DayRoutePlan,
    *,
    weather: DayWeather,
    original_route: list[str],
    preferences: list[str],
    transport_mode: str,
) -> DayNotice | None:
    """功能：调用 DeepSeek 综合路线、日期、天气和偏好生成高峰提醒。

    参数：
        day：单日路线规划。
        weather：当日天气。
        original_route：当天景点顺序。
        preferences：用户偏好。
        transport_mode：交通方式说明。
    返回值：
        返回高峰提醒；判断不需要提醒时返回 None。
    """
    llm = build_crowd_notice_llm()
    prompt = (
        "你是 FloatTrip 行程详情 Agent。请只判断当天是否需要给用户高峰期提醒，"
        "结合日期是否周末/节假日倾向、景点是否热门、路线景点数量、天气和用户偏好。"
        "如果不需要强提醒，level 用 info，标题仍保持简短。"
        f"\n日期：{weather.date or '未知'}"
        f"\n天气：{weather.weather or '未知'} {weather.temperature or ''}"
        f"\n景点顺序：{' -> '.join(original_route)}"
        f"\n景点数量：{len(day.spots)}"
        f"\n交通方式：{transport_mode}"
        f"\n用户偏好：{'、'.join(preferences) if preferences else '无'}"
    )
    draft = llm.invoke([("system", "输出中文，语气简洁实用。"), ("user", prompt)])
    if not isinstance(draft, CrowdNoticeDraft):
        return None
    return DayNotice(
        level="warning" if draft.level == "warning" else "info",
        title=draft.title or "高峰提醒",
        content=draft.content or "建议热门景点提前到达，并关注预约入园要求。",
        basis="crowd",
    )


def build_crowd_notice_llm() -> Any:
    """功能：创建用于高峰提醒的 DeepSeek 结构化输出模型。

    参数：
        无。
    返回值：
        返回绑定 CrowdNoticeDraft 的 LangChain 模型。
    """
    travel_research.load_local_env()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx 或 langchain-openai") from exc
    model = travel_research.normalize_deepseek_model(
        os.getenv("DEEPSEEK_MODEL", travel_research.DEFAULT_DEEPSEEK_MODEL)
    )
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=travel_research.DEEPSEEK_BASE_URL,
        temperature=0,
        http_client=httpx.Client(proxy=travel_research.choose_http_proxy(), trust_env=False),
        http_async_client=httpx.AsyncClient(proxy=travel_research.choose_http_proxy(), trust_env=False),
        http_socket_options=(),
        extra_body={"thinking": {"type": "disabled"}},
    )
    return llm.with_structured_output(CrowdNoticeDraft, method="function_calling", strict=True)


def fallback_crowd_notice(day_date: date | None, preferences: list[str]) -> DayNotice | None:
    """功能：在 LLM 不可用时用日期规则生成高峰提醒兜底。

    参数：
        day_date：旅行日期。
        preferences：用户偏好。
    返回值：
        周末返回高峰提醒，否则返回 None。
    """
    if not likely_crowded_day(day_date):
        return None
    return DayNotice(
        level="warning",
        title="高峰提醒",
        content=(
            f"今日可能遇到热门景点或周末高峰，{preference_text(preferences)}"
            "建议热门景点尽量提前到达，并关注预约入园要求。"
        ),
        basis="crowd",
    )


def ordered_spots_for_day(day: DayRoutePlan) -> list[Any]:
    """功能：按优化顺序返回当天景点列表。

    参数：
        day：单日路线规划。
    返回值：
        返回排序后的景点列表。
    """
    spots_by_id = {spot.spot_id: spot for spot in day.spots}
    ordered = [spots_by_id[spot_id] for spot_id in day.optimized_order if spot_id in spots_by_id]
    return ordered or day.spots


def ordered_spot_names(day: DayRoutePlan) -> list[str]:
    """功能：返回当天原始路线名称列表。

    参数：
        day：单日路线规划。
    返回值：
        返回景点名称列表。
    """
    return [spot.name for spot in ordered_spots_for_day(day)]


def segment_summary_for_spot(day: DayRoutePlan, spot_id: str | None) -> str | None:
    """功能：读取抵达某景点前一段交通摘要。

    参数：
        day：单日路线规划。
        spot_id：景点 ID。
    返回值：
        返回交通摘要；没有时返回 None。
    """
    for segment in day.route_segments:
        if segment.to_spot_id == spot_id:
            return segment.summary or f"约 {segment.duration_minutes or 0} 分钟"
    return None


def transit_buffer_after(day: DayRoutePlan, index: int) -> int:
    """功能：根据路线段时长估算两个活动之间的交通缓冲分钟数。

    参数：
        day：单日路线规划。
        index：当前景点下标。
    返回值：
        返回缓冲分钟数。
    """
    if index >= len(day.route_segments):
        return 20
    duration = day.route_segments[index].duration_minutes
    return max(15, int(duration or 20) + 10)


def minute_to_time(value: int) -> str:
    """功能：把一天中的分钟数格式化成 HH:MM。

    参数：
        value：分钟数。
    返回值：
        返回 HH:MM 字符串。
    """
    safe_value = min(max(value, DAY_START_MINUTE), DAY_END_MINUTE)
    return f"{safe_value // 60:02d}:{safe_value % 60:02d}"


def time_to_minute(value: str) -> int:
    """功能：把 HH:MM 字符串转换成分钟数。

    参数：
        value：时间字符串。
    返回值：
        返回分钟数。
    """
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.hour * 60 + parsed.minute


def likely_crowded_day(day_date: date | None) -> bool:
    """功能：粗略判断日期是否容易出现游览高峰。

    参数：
        day_date：旅行日期。
    返回值：
        周末返回 True，否则返回 False。
    """
    return bool(day_date and day_date.weekday() >= 5)


def preference_text(preferences: list[str]) -> str:
    """功能：格式化偏好提示片段。

    参数：
        preferences：用户偏好列表。
    返回值：
        返回自然语言片段。
    """
    return f"结合你偏好的{'、'.join(preferences)}，" if preferences else ""
