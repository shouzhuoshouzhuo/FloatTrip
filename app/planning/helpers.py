"""纯工具函数（无 LLM、无外部 API 调用）。"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

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


def _has_coords(loc: Any) -> bool:
    """location 是否为含数值经纬度的 dict。"""
    return (
        isinstance(loc, dict)
        and isinstance(loc.get("lat"), (int, float))
        and isinstance(loc.get("lng"), (int, float))
    )


def cluster_pois_by_location(
    pois: list[dict[str, Any]], k: int
) -> dict[str, int]:
    """按经纬度把候选景点聚成 k 个地理分区，返回 {景点名: 分区编号(0-based)}。

    用于给 Planner 提供「真实坐标距离」的地理分区软提示，替代坐标盲的行政区名
    （adname）——同一行政区的景点可能相距很远（如玄武湖与中山陵同属玄武区却
    相距约 10km）。

    - 无坐标的景点归入分区 -1（不参与聚类）。
    - k<=1 或有效景点过少时，全部归入分区 0。
    - 确定性：固定种子初始化（按经度排序等距取点），同一输入每次结果一致。
    """
    result: dict[str, int] = {}
    valid: list[tuple[str, dict[str, float]]] = []
    for s in pois:
        loc = s.get("location")
        if _has_coords(loc):
            valid.append((s["name"], loc))
        else:
            result[s["name"]] = -1

    n = len(valid)
    if n == 0:
        return result
    k = max(1, min(k, n))
    if k == 1:
        for name, _ in valid:
            result[name] = 0
        return result

    # 确定性初始化：按经度（再纬度）排序后等距取 k 个种子
    ordered = sorted(valid, key=lambda x: (x[1]["lng"], x[1]["lat"]))
    centroids = [
        {"lat": ordered[round(i * (n - 1) / (k - 1))][1]["lat"],
         "lng": ordered[round(i * (n - 1) / (k - 1))][1]["lng"]}
        for i in range(k)
    ]

    assign: dict[str, int] = {}
    for _ in range(20):
        new_assign = {
            name: min(range(k), key=lambda c: haversine_km(centroids[c], loc))
            for name, loc in valid
        }
        if new_assign == assign:
            break
        assign = new_assign
        for c in range(k):
            members = [loc for name, loc in valid if assign[name] == c]
            if members:
                centroids[c] = {
                    "lat": sum(m["lat"] for m in members) / len(members),
                    "lng": sum(m["lng"] for m in members) / len(members),
                }

    result.update(assign)
    return result


# ─── 偏好清洗 ─────────────────────────────────────────────────

# LLM 在用户未提供偏好时偶尔吐出的占位垃圾值（应等同于"无偏好"）
_JUNK_PREF = {"null", "none", "undefined", "n/a", "na", "无", "暂无", "没有", "不限", "无偏好"}


def clean_pref(v: str | None) -> str | None:
    """把偏好字段归一化：去空白；整串为占位垃圾值（如 'null'/'无'）时视为无偏好返回 None。

    只在『整串』等于垃圾 token 时清空，避免误伤 '无辣不欢' 这类正常偏好。
    """
    s = (v or "").strip()
    return None if (not s or s.lower() in _JUNK_PREF) else s


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

_CLUSTER_LABELS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def _spot_line(s: dict[str, Any]) -> str:
    loc = s.get("location") or {}
    rating = f"{s['rating']:.1f}" if s.get("rating") else "无"
    open_t = s.get("open_time") or "未知"
    area = s.get("adname") or "未知"
    if _has_coords(loc):
        coord = f"坐标 {loc['lng']:.4f},{loc['lat']:.4f}"
    else:
        coord = "坐标未知"
    return f"- {s['name']}（区域 {area}，评分 {rating}，开放 {open_t}，{coord}）"


def format_spots_for_llm(
    pois: list[dict[str, Any]],
    cluster_map: dict[str, int] | None = None,
) -> str:
    """候选景点池的紧凑清单（喂给 LLM）。

    传入 cluster_map（{景点名: 分区编号}，见 cluster_pois_by_location）时，按
    『地理分区』分组展示——同一分区的景点连续列出，引导 LLM 把同区景点排在同
    一天。不传则保持平铺（向后兼容）。
    """
    if not cluster_map:
        return "\n".join(_spot_line(s) for s in pois)

    groups: dict[int, list[dict[str, Any]]] = {}
    for s in pois:
        cid = cluster_map.get(s["name"], -1)
        groups.setdefault(cid, []).append(s)

    blocks = []
    # 有效分区按编号升序在前，无坐标(-1)放最后
    for cid in sorted(groups, key=lambda c: (c == -1, c)):
        if cid == -1:
            header = "📍其他（无坐标，地理分区未知）"
        else:
            label = _CLUSTER_LABELS[cid] if cid < len(_CLUSTER_LABELS) else f"#{cid + 1}"
            header = f"📍地理分区{label}"
        lines = "\n".join(_spot_line(s) for s in groups[cid])
        blocks.append(f"{header}\n{lines}")
    return "\n\n".join(blocks)


def spot_location_map(pois: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    return {s["name"]: s["location"] for s in pois}



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

    诊断日志：
    - 每次调用打印耗时（帮助区分"网络慢"和"重试导致慢"）
    - 出现 None 时打印警告，标明是第几次重试
    """
    # 估算输入 token（粗略：字符数 / 2 ≈ token 数，仅供参考）
    total_chars = sum(len(role) + len(content) for role, content in messages)
    schema_name = getattr(getattr(llm, "schema", None), "__name__", None)
    # 从 llm 对象尝试取 schema 名（with_structured_output 绑定的 Pydantic 类）
    if schema_name is None:
        # langchain with_structured_output 把 schema 存在内部不同位置，尝试常见路径
        for attr in ("_schema", "schema_", "output_schema"):
            s = getattr(llm, attr, None)
            if s and hasattr(s, "__name__"):
                schema_name = s.__name__
                break
    label = schema_name or "unknown"

    for attempt in range(retries):
        t0 = time.perf_counter()
        result = llm.invoke(messages)
        elapsed = time.perf_counter() - t0

        if result is not None:
            if attempt > 0:
                logger.warning(
                    "[invoke_structured] %s 第 %d 次重试后成功，本次耗时 %.2fs，"
                    "输入约 %d chars",
                    label, attempt + 1, elapsed, total_chars,
                )
            else:
                logger.debug(
                    "[invoke_structured] %s 首次成功，耗时 %.2fs，输入约 %d chars",
                    label, elapsed, total_chars,
                )
            return result

        logger.warning(
            "[invoke_structured] %s 第 %d 次调用返回 None（耗时 %.2fs），准备重试…",
            label, attempt + 1, elapsed,
        )

    raise RuntimeError(f"结构化输出连续 {retries} 次返回 None，模型未产出有效结果")


# ─── 餐厅 POI 解析 ────────────────────────────────────────────

# ─── 天气工具 ─────────────────────────────────────────────────

def fetch_weather_for_dates(
    destination: str,
    start_date: date,
    end_date: date,
    api_key: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """获取旅游日期范围内的逐日天气预报。

    调用高德天气 API（最多约 4 天预报），按旅游日期切片匹配。

    Returns:
        (forecast_list, weather_note)
        - forecast_list: 与旅游日期匹配的天气列表（空表示无可用预报）
        - weather_note:  降级说明文字（正常获取时为 None）
    """
    from app.providers.weather.amap import fetch_forecast

    try:
        all_forecasts = fetch_forecast(destination, api_key)
    except Exception:
        all_forecasts = []

    if not all_forecasts:
        return [], "天气信息获取失败，按晴天规划路线"

    forecast_map = {f["date"]: f for f in all_forecasts}

    # 生成旅游日期序列
    travel_dates: list[str] = []
    cur = start_date
    while cur <= end_date:
        travel_dates.append(cur.isoformat())
        cur += timedelta(days=1)

    matched = [forecast_map[d] for d in travel_dates if d in forecast_map]
    missing_dates = [d for d in travel_dates if d not in forecast_map]

    if not matched:
        return [], "旅游日期超出天气预报范围（高德预报约 4 天内），建议出行前关注天气预报"

    note: str | None = None
    if missing_dates:
        note = (
            f"部分旅游日期（{'、'.join(missing_dates)}）超出天气预报范围，"
            "建议出行前关注天气预报"
        )

    return matched, note


def format_weather_for_llm(forecast: list[dict[str, Any]]) -> str:
    """格式化天气信息供 LLM 读取，如：
    2024-06-05: 白天晴/夜间晴，气温22-32°C
    2024-06-06: 白天中雨/夜间小雨，气温18-24°C ⚠️ 雨雪天气
    """
    if not forecast:
        return ""
    lines = []
    for w in forecast:
        warning = " ⚠️ 雨雪天气，请优先安排室内景点" if w.get("is_bad") else ""
        lines.append(
            f"{w['date']}: 白天{w['day_weather']}/夜间{w['night_weather']}，"
            f"气温{w['night_temp']}-{w['day_temp']}°C{warning}"
        )
    return "\n".join(lines)


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

    open_time_r = (
        str(biz_ext.get("opentime2", "")).strip()
        or str(biz_ext.get("opentime", "")).strip()
        or None
    )
    tel_r = str(poi.get("tel") or "").strip() or None
    type_str = str(poi.get("type") or "")
    category = (type_str.split(";")[-1].strip() if ";" in type_str else type_str.strip()) or None

    return {
        "name": str(poi.get("name", "")),
        "cost": cost_raw or None,
        "rating": rating,
        "keytag": str(poi.get("type", "")),
        "location": location,
        "address": normalize_address(poi.get("address")),
        "photo": photo,
        "open_time": open_time_r,
        "tel": tel_r,
        "category": category,
    }
