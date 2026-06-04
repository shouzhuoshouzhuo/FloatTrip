"""纯工具函数（无 LLM、无外部 API 调用）。"""

from __future__ import annotations

import math
import os
import re
from datetime import date
from typing import Any

from app.core.env import load_local_env
from app.providers.amap.poi import (
    parse_location,
    normalize_address,
    search_attraction_pois,
    poi_to_spot,
)


# ─── 环境变量 ─────────────────────────────────────────────────

def amap_key() -> str:
    load_local_env()
    key = os.getenv("AMAP_API_KEY", "").strip()
    if not key:
        raise RuntimeError("缺少 AMAP_API_KEY，请在 .env.local 中配置")
    return key


# ─── 日期解析 ─────────────────────────────────────────────────

def parse_iso_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# ─── 地理距离 ─────────────────────────────────────────────────

EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: dict[str, float], b: dict[str, float]) -> float:
    """两点球面 haversine 距离（km）。"""
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lng"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lng"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# ─── 候选景点池 ───────────────────────────────────────────────

def fetch_city_spots(city: str, api_key: str, *, max_spots: int = 30) -> list[dict[str, Any]]:
    """多关键词搜索 + 去重，返回最多 max_spots 个有坐标的候选景点。"""
    keywords_list = [f"{city}必去景点", f"{city}热门景区", f"{city}博物馆"]
    seen: set[str] = set()
    spots: list[dict[str, Any]] = []
    for kw in keywords_list:
        if len(spots) >= max_spots:
            break
        for raw in search_attraction_pois(city, api_key, keywords=kw):
            if len(spots) >= max_spots:
                break
            name = raw.get("name", "")
            if name in seen:
                continue
            spot = poi_to_spot(raw)
            if spot:
                seen.add(name)
                spots.append(spot)
    return spots


def filter_by_rating(
    spots: list[dict[str, Any]], min_rating: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """只保留 rating ≥ min_rating 的景点；无评分视为不达标。"""
    kept = [s for s in spots if s.get("rating") is not None and s["rating"] >= min_rating]
    dropped = [s for s in spots if s not in kept]
    return kept, dropped


# ─── 格式化 ──────────────────────────────────────────────────

def format_spots_for_llm(pois: list[dict[str, Any]]) -> str:
    """候选景点池的紧凑清单（喂给 LLM）。"""
    lines = []
    for s in pois:
        loc = s["location"]
        rating = f"{s['rating']:.1f}" if s.get("rating") else "无"
        open_t = (s.get("open_time") or "未知")[:24]
        lines.append(
            f"- {s['name']}（评分 {rating}，开放 {open_t}，坐标 {loc['lng']:.4f},{loc['lat']:.4f}）"
        )
    return "\n".join(lines)


def spot_location_map(pois: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    return {s["name"]: s["location"] for s in pois}


# ─── Reviewer 预检工具 ────────────────────────────────────────

def day_proximity_report(route: list[dict[str, Any]], pois: list[dict[str, Any]]) -> str:
    """每天景点最大跨度（km），作为客观事实喂给 Reviewer。"""
    loc_map = spot_location_map(pois)
    lines = []
    for day in route:
        coords = [loc_map[s["name"]] for s in day.get("spots", []) if s["name"] in loc_map]
        span = 0.0
        if len(coords) >= 2:
            span = max(
                haversine_km(coords[i], coords[j])
                for i in range(len(coords))
                for j in range(i + 1, len(coords))
            )
        names = "、".join(s["name"] for s in day.get("spots", []))
        lines.append(f"Day {day.get('day')}：{names} —— 当天最大跨度 {span:.1f} km")
    return "\n".join(lines)


_TIME_RANGE_RE = re.compile(r"(\d{1,2})[:：](\d{2})\s*[-~—至]\s*(\d{1,2})[:：](\d{2})")


def _to_minutes(hhmm: str) -> int | None:
    m = re.match(r"\s*(\d{1,2})[:：](\d{2})", hhmm or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def open_time_violations(route: list[dict[str, Any]], pois: list[dict[str, Any]]) -> list[str]:
    """检查每个景点游玩时段是否落在开放时间内。"""
    open_map = {s["name"]: (s.get("open_time") or "") for s in pois}
    bad: list[str] = []
    for day in route:
        for spot in day.get("spots", []):
            rng = _TIME_RANGE_RE.search(open_map.get(spot["name"], ""))
            if not rng:
                continue
            o_start = int(rng.group(1)) * 60 + int(rng.group(2))
            o_end = int(rng.group(3)) * 60 + int(rng.group(4))
            s_start = _to_minutes(spot.get("start_time", ""))
            s_end = _to_minutes(spot.get("end_time", ""))
            if s_start is None or s_end is None:
                continue
            if s_start < o_start or s_end > o_end:
                bad.append(
                    f"Day{day.get('day')} {spot['name']} 游玩 {spot.get('start_time')}-{spot.get('end_time')}"
                    f" 超出开放 {rng.group(0)}"
                )
    return bad


def unknown_spots(route: list[dict[str, Any]], pois: list[dict[str, Any]]) -> list[str]:
    """找出不在候选池的景点名。"""
    valid = {s["name"] for s in pois}
    bad = []
    for day in route:
        for spot in day.get("spots", []):
            if spot["name"] not in valid:
                bad.append(f"Day{day.get('day')} {spot['name']}")
    return bad


# ─── 时间线辅助 ───────────────────────────────────────────────

def last_spot_of_period(day: dict[str, Any], period: str) -> dict[str, Any] | None:
    """返回当天指定时段的最后一个景点（按 spots 列表顺序）。"""
    spots = [s for s in day.get("spots", []) if s.get("period") == period]
    if spots:
        return spots[-1]
    all_spots = day.get("spots", [])
    if not all_spots:
        return None
    return all_spots[0] if period == "morning" else all_spots[-1]


def dinner_anchor_spot(day: dict[str, Any]) -> dict[str, Any] | None:
    """晚餐搜索中心：优先取第一个 evening 景点，无则兜底取最后一个 afternoon 景点。"""
    evening_spots = [s for s in day.get("spots", []) if s.get("period") == "evening"]
    if evening_spots:
        return evening_spots[0]
    return last_spot_of_period(day, "afternoon")


# ─── 结构化 LLM 调用（含 None 重试守卫）────────────────────────

def invoke_structured(llm: Any, messages: list[tuple[str, str]], *, retries: int = 3) -> Any:
    """调用结构化输出 LLM，对偶发返回 None 做重试。

    DeepSeek function_calling 模式偶尔返回 None；重试若干次，
    仍失败则抛出明确错误而非 AttributeError。
    """
    for _ in range(retries):
        result = llm.invoke(messages)
        if result is not None:
            return result
    raise RuntimeError(f"结构化输出连续 {retries} 次返回 None，模型未产出有效结果")


# ─── 餐厅 POI 解析 ────────────────────────────────────────────

def restaurant_to_dict(poi: dict[str, Any]) -> dict[str, Any] | None:
    """把高德周边搜索的餐饮 POI 整理成结构化餐厅信息。缺坐标返回 None。"""
    location = parse_location(poi.get("location"))
    if not location:
        return None

    biz_ext = poi.get("biz_ext") or {}
    if not isinstance(biz_ext, dict):
        biz_ext = {}

    cost_raw = str(biz_ext.get("cost", "")).strip()
    rating_raw = str(biz_ext.get("rating", "")).strip()
    try:
        rating: float | None = float(rating_raw) if rating_raw else None
    except ValueError:
        rating = None

    photos = poi.get("photos") or []
    photo: str | None = None
    if isinstance(photos, list) and photos and isinstance(photos[0], dict):
        photo = str(photos[0].get("url", "")).strip() or None

    return {
        "name": str(poi.get("name", "")),
        "cost": cost_raw or None,
        "rating": rating,
        "keytag": str(poi.get("type", "")),
        "location": location,
        "address": normalize_address(poi.get("address")),
        "photo": photo,
    }
