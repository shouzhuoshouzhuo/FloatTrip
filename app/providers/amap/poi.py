"""高德地点搜索与 POI 解析。"""

from __future__ import annotations

import time
import urllib.parse
from typing import Any

from app.core.cache import get_cached, set_cached, poi_cache_key, POI_TTL
from app.core.http import http_get_json
from app.providers.amap.client import (
    AMAP_AROUND_SEARCH_URL,
    AMAP_RATE_LIMIT_INFOS,
    AMAP_TEXT_SEARCH_URL,
    int_or_none,
)

ATTRACTION_TYPE = "风景名胜"


# ─── 周边搜索 ────────────────────────────────────────────────

def search_around_pois(
    location: dict[str, float],
    api_key: str,
    *,
    types: str = "",
    keyword: str = "",
    radius: int = 1000,
    offset: int = 6,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """调用高德周边搜索，围绕坐标查找餐饮、景点等 POI。
    餐饮搜索传 types='餐饮服务'，按分类搜索覆盖所有餐馆；
    有 types 时不发 keywords（两者语义不同，混用结果偏少）。
    """
    params = {
        "key": api_key,
        "location": f"{location['lng']},{location['lat']}",
        "radius": str(radius),
        "offset": str(offset),
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
    if types:
        params["types"] = types
    elif keyword:
        params["keywords"] = keyword
    url = f"{AMAP_AROUND_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(max_retries + 1):
        data = http_get_json(url)
        if data.get("status") == "1":
            pois = data.get("pois", [])
            return pois if isinstance(pois, list) else []
        info = str(data.get("info") or "未知错误")
        if info not in AMAP_RATE_LIMIT_INFOS or attempt >= max_retries:
            raise RuntimeError(f"高德周边搜索失败：{info}")
        time.sleep(1.2 * (attempt + 1))
    return []


# ─── 景点关键字搜索 ──────────────────────────────────────────

def search_attraction_pois(
    city: str,
    api_key: str,
    *,
    keywords: str = "景点",
    offset: int = 25,
    page: int = 1,
) -> list[dict[str, Any]]:
    """用高德关键字搜索 API 返回景点 POI 列表，类型固定为风景名胜。"""
    # 缓存逻辑：仅缓存 page=1 的请求
    cache_key = poi_cache_key(city, keywords) if page == 1 else None
    if cache_key is not None:
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

    params: dict[str, str] = {
        "key": api_key,
        "keywords": keywords,
        "types": ATTRACTION_TYPE,
        "city": city,
        "citylimit": "true",
        "offset": str(offset),
        "page": str(page),
        "extensions": "all",
        "output": "json",
    }
    url = f"{AMAP_TEXT_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        data = http_get_json(url)
        if data.get("status") == "1":
            pois = data.get("pois", [])
            if page == 1 and pois:
                set_cached(cache_key, pois, POI_TTL)
            return pois if isinstance(pois, list) else []
        info = str(data.get("info") or "未知错误")
        if info not in AMAP_RATE_LIMIT_INFOS or attempt >= 3:
            raise RuntimeError(f"高德搜索失败：{info}")
        time.sleep(1.2 * (attempt + 1))
    return []


def search_city_pois(
    city: str,
    api_key: str,
    *,
    keywords: str,
    types: str,
    offset: int = 8,
) -> list[dict[str, Any]]:
    """通用城市关键字搜索（手动编辑换点用）：类型可指定（景点/餐饮），不做缓存（由调用方决定）。"""
    params: dict[str, str] = {
        "key": api_key,
        "keywords": keywords,
        "types": types,
        "city": city,
        "citylimit": "true",
        "offset": str(offset),
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
    url = f"{AMAP_TEXT_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        data = http_get_json(url)
        if data.get("status") == "1":
            pois = data.get("pois", [])
            return pois if isinstance(pois, list) else []
        info = str(data.get("info") or "未知错误")
        if info not in AMAP_RATE_LIMIT_INFOS or attempt >= 3:
            raise RuntimeError(f"高德搜索失败：{info}")
        time.sleep(1.2 * (attempt + 1))
    return []


# ─── POI 解析 ────────────────────────────────────────────────

def parse_location(value: Any) -> dict[str, float] | None:
    """把高德 "lng,lat" 字符串解析成结构化坐标，失败返回 None。"""
    if not isinstance(value, str) or "," not in value:
        return None
    lng_text, lat_text = value.split(",", 1)
    try:
        return {"lng": float(lng_text), "lat": float(lat_text)}
    except ValueError:
        return None


def normalize_address(value: Any) -> str:
    """把高德可能返回的字符串或数组地址统一成字符串。"""
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value or "")


def poi_to_spot(poi: dict[str, Any]) -> dict[str, Any] | None:
    """把高德景点 POI 原始字段整理成规划用结构。缺坐标返回 None。"""
    loc_str = poi.get("location", "")
    if not loc_str or "," not in loc_str:
        return None
    lng, lat = loc_str.split(",", 1)
    try:
        location = {"lng": float(lng), "lat": float(lat)}
    except ValueError:
        return None

    biz_ext = poi.get("biz_ext") or {}
    rating_raw = biz_ext.get("rating", "") if isinstance(biz_ext, dict) else ""
    try:
        rating: float | None = float(rating_raw) if rating_raw else None
    except ValueError:
        rating = None

    open_time: str | None = (
        str(biz_ext["opentime2"]).strip() if isinstance(biz_ext, dict) and biz_ext.get("opentime2") else None
    ) or (
        str(biz_ext["opentime"]).strip() if isinstance(biz_ext, dict) and biz_ext.get("opentime") else None
    ) or None

    photos = poi.get("photos") or []
    first_photo: str | None = None
    if isinstance(photos, list) and photos and isinstance(photos[0], dict):
        first_photo = str(photos[0].get("url", "")).strip() or None

    return {
        "name": poi.get("name", ""),
        "rating": rating,
        "open_time": open_time,
        "location": location,
        "photo": first_photo,
    }
