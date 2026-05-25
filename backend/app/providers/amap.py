"""高德地点能力的公共工具，供命令行脚本和后端服务复用。"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripAmapProvider/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"
AMAP_TEXT_SEARCH_URL = "https://restapi.amap.com/v3/place/text"
AMAP_AROUND_SEARCH_URL = "https://restapi.amap.com/v3/place/around"
AMAP_TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"
AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
AMAP_RATE_LIMIT_INFOS = {
    "CUQPS_HAS_EXCEEDED_THE_LIMIT",
    "USER_DAILY_QUERY_OVER_LIMIT",
    "USER_KEY_RECYCLED",
}


def load_local_env() -> None:
    """功能：读取项目根目录的本地环境变量文件，并且不覆盖已有环境变量。

    参数：
        无。
    返回值：
        无返回值，会把 .env.local 中缺失的键写入 os.environ。
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


def require_amap_key() -> str:
    """功能：读取高德网络服务密钥，没有配置时抛出明确错误。

    参数：
        无。
    返回值：
        返回 AMAP_API_KEY 字符串。
    """
    load_local_env()
    api_key = os.getenv("AMAP_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 AMAP_API_KEY。请在环境变量或 .env.local 中配置高德 Web服务 Key 后重试。")
    return api_key


def http_get_json(url: str, timeout: int = 15) -> dict[str, Any]:
    """功能：发起高德网络请求并解析结构化响应，失败时自动重试。

    参数：
        url：完整请求地址。
        timeout：单次请求超时时间，单位为秒。
    返回值：
        返回解析后的 JSON 字典。
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(response.read().decode(charset, errors="replace"))
        except Exception as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"请求失败：{redact_url(url)}；原因：{last_error}")


def redact_url(url: str) -> str:
    """功能：隐藏网址中的密钥字段，避免错误信息泄露凭据。

    参数：
        url：可能包含 key、token 等敏感查询参数的 URL。
    返回值：
        返回已脱敏的 URL 字符串。
    """
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for secret_key in ("key", "api_key", "access_token", "token"):
        if secret_key in query:
            query[secret_key] = ["<redacted>"]
    redacted_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=redacted_query))


def search_amap_pois(
    keyword: str,
    admin_region: str,
    api_key: str,
    offset: int,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """功能：调用高德关键字地点搜索，返回指定行政区内的候选地点列表。

    参数：
        keyword：待搜索的景点名称或关键词。
        admin_region：行政区名称或行政区编码。
        api_key：高德 Web 服务 Key。
        offset：单页返回数量。
        max_retries：遇到高德限流类错误时的最大重试次数。
    返回值：
        返回高德 POI 原始字典列表。
    """
    params = {
        "key": api_key,
        "keywords": keyword,
        "city": admin_region,
        "citylimit": "true",
        "offset": str(offset),
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
    url = f"{AMAP_TEXT_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(max_retries + 1):
        data = http_get_json(url)
        if data.get("status") == "1":
            pois = data.get("pois", [])
            return pois if isinstance(pois, list) else []

        info = str(data.get("info") or "未知错误")
        if info not in AMAP_RATE_LIMIT_INFOS or attempt >= max_retries:
            raise RuntimeError(f"高德 POI 搜索失败：{info}")
        time.sleep(1.2 * (attempt + 1))

    return []


def search_around_pois(
    keyword: str,
    location: dict[str, float],
    api_key: str,
    *,
    radius: int = 1500,
    offset: int = 6,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """功能：调用高德周边搜索，围绕坐标查找餐饮、景点等 POI。

    参数：
        keyword：待搜索关键词，例如“餐厅”。
        location：中心点坐标，格式为 {"lng": 经度, "lat": 纬度}。
        api_key：高德 Web 服务 Key。
        radius：搜索半径，单位为米。
        offset：单页返回数量。
        max_retries：遇到高德限流类错误时的最大重试次数。
    返回值：
        返回高德 POI 原始字典列表。
    """
    params = {
        "key": api_key,
        "keywords": keyword,
        "location": f"{location['lng']},{location['lat']}",
        "radius": str(radius),
        "offset": str(offset),
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
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


def parse_location(value: Any) -> dict[str, float] | None:
    """功能：把高德返回的经纬度字符串解析成结构化坐标。

    参数：
        value：高德 location 字符串，通常为 "lng,lat"。
    返回值：
        返回 {"lng": 经度, "lat": 纬度}；解析失败返回 None。
    """
    if not isinstance(value, str) or "," not in value:
        return None
    lng_text, lat_text = value.split(",", 1)
    try:
        return {"lng": float(lng_text), "lat": float(lat_text)}
    except ValueError:
        return None


def normalize_poi(poi: dict[str, Any]) -> dict[str, Any]:
    """功能：把高德原始地点字段整理成项目内部统一结构。

    参数：
        poi：高德 POI 原始字典。
    返回值：
        返回 FloatTrip 内部统一 POI 字典。
    """
    normalized = {
        "provider": "amap",
        "id": str(poi.get("id", "")),
        "name": str(poi.get("name", "")),
        "type": str(poi.get("type", "")),
        "adcode": str(poi.get("adcode", "")),
        "province": str(poi.get("pname", "")),
        "city": str(poi.get("cityname", "")),
        "district": str(poi.get("adname", "")),
        "address": normalize_address(poi.get("address")),
        "distance_meters": int_or_none(poi.get("distance")),
        "location": parse_location(poi.get("location")),
    }
    return {key: value for key, value in normalized.items() if value not in ("", None, [])}


def normalize_address(value: Any) -> str:
    """功能：把高德可能返回的字符串或数组地址统一成字符串。

    参数：
        value：高德 address 字段，可能是字符串、数组或空值。
    返回值：
        返回整理后的地址字符串。
    """
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value or "")


def query_weather(city: str, api_key: str) -> list[dict[str, Any]]:
    """功能：调用高德天气预报接口，返回城市未来天气列表。

    参数：
        city：目的地城市名称或行政区编码。
        api_key：高德 Web 服务 Key。
    返回值：
        返回高德 forecasts[0].casts 列表；没有可用天气时返回空列表。
    """
    params = {
        "key": api_key,
        "city": city,
        "extensions": "all",
        "output": "json",
    }
    data = http_get_json(f"{AMAP_WEATHER_URL}?{urllib.parse.urlencode(params)}")
    if data.get("status") != "1":
        raise RuntimeError(
            f"高德天气查询失败：info={data.get('info')}, infocode={data.get('infocode')}"
        )
    forecasts = data.get("forecasts", [])
    if not isinstance(forecasts, list) or not forecasts:
        return []
    casts = forecasts[0].get("casts", []) if isinstance(forecasts[0], dict) else []
    return casts if isinstance(casts, list) else []


class AMapRouteError(RuntimeError):
    """表示高德路线规划接口没有返回可用于 FloatTrip 的路线结果。"""


def query_transit_route(
    origin_lnglat: str,
    destination_lnglat: str,
    city: str,
    api_key: str,
    strategy: int = 0,
) -> dict[str, Any]:
    """功能：调用高德公交/地铁路线接口并返回最短耗时方案。

    参数：
        origin_lnglat：起点坐标字符串，格式为 "lng,lat"。
        destination_lnglat：终点坐标字符串，格式为 "lng,lat"。
        city：高德公交规划使用的城市名称或城市编码。
        api_key：高德 Web 服务 Key。
        strategy：高德公交策略，默认 0 表示最快捷。
    返回值：
        返回包含时长、距离、费用、摘要、原始压缩公交结构和真实 path 的字典。
    """
    params = {
        "key": api_key,
        "origin": origin_lnglat,
        "destination": destination_lnglat,
        "city": city,
        "strategy": str(strategy),
        "output": "json",
    }
    data = http_get_json(f"{AMAP_TRANSIT_URL}?{urllib.parse.urlencode(params)}")
    if data.get("status") != "1":
        raise AMapRouteError(
            f"高德公交路径规划失败：info={data.get('info')}, infocode={data.get('infocode')}"
        )

    transits = data.get("route", {}).get("transits", [])
    valid_transits = [
        transit
        for transit in transits
        if isinstance(transit, dict) and str(transit.get("duration", "")).isdigit()
    ]
    if not valid_transits:
        raise AMapRouteError("高德没有返回可用公交路线")

    best = min(valid_transits, key=lambda item: int(item["duration"]))
    duration_seconds = int(best["duration"])
    distance_meters = int_or_none(best.get("distance"))
    walking_distance_meters = int_or_none(best.get("walking_distance"))
    return {
        "mode": "transit",
        "duration_seconds": duration_seconds,
        "duration_minutes": round(duration_seconds / 60, 1),
        "distance_meters": distance_meters,
        "walking_distance_meters": walking_distance_meters,
        "cost": none_if_empty(best.get("cost")),
        "segments_count": len(best.get("segments", [])) if isinstance(best.get("segments"), list) else 0,
        "summary": summarize_transit_plan(best),
        "amap_transit": compact_transit(best),
        "path": extract_transit_path(best),
    }


def query_walking_route(
    origin_lnglat: str,
    destination_lnglat: str,
    api_key: str,
) -> dict[str, Any]:
    """功能：调用高德步行路线接口，作为近距离无公交方案时的兜底。

    参数：
        origin_lnglat：起点坐标字符串，格式为 "lng,lat"。
        destination_lnglat：终点坐标字符串，格式为 "lng,lat"。
        api_key：高德 Web 服务 Key。
    返回值：
        返回包含步行时长、距离、摘要和真实 path 的字典。
    """
    params = {
        "key": api_key,
        "origin": origin_lnglat,
        "destination": destination_lnglat,
        "output": "json",
    }
    data = http_get_json(f"{AMAP_WALKING_URL}?{urllib.parse.urlencode(params)}")
    if data.get("status") != "1":
        raise AMapRouteError(
            f"高德步行路径规划失败：info={data.get('info')}, infocode={data.get('infocode')}"
        )

    paths = data.get("route", {}).get("paths", [])
    valid_paths = [
        path
        for path in paths
        if isinstance(path, dict) and str(path.get("duration", "")).isdigit()
    ]
    if not valid_paths:
        raise AMapRouteError("高德没有返回可用步行路线")

    best = min(valid_paths, key=lambda item: int(item["duration"]))
    path_points = extract_walking_path(best)
    if len(path_points) < 2:
        raise AMapRouteError("高德步行路线缺少真实 polyline")

    duration_seconds = int(best["duration"])
    distance_meters = int_or_none(best.get("distance"))
    return {
        "mode": "walking",
        "duration_seconds": duration_seconds,
        "duration_minutes": round(duration_seconds / 60, 1),
        "distance_meters": distance_meters,
        "walking_distance_meters": distance_meters,
        "cost": None,
        "segments_count": 1,
        "summary": f"步行约 {round((distance_meters or 0) / 1000, 1)} km",
        "amap_transit": None,
        "fallback_mode": "walking",
        "path": path_points,
    }


def int_or_none(value: Any) -> int | None:
    """功能：把高德返回的数字字符串转成整数，无法转换时返回空值。

    参数：
        value：任意待转换的高德字段值。
    返回值：
        返回整数或 None。
    """
    return int(value) if str(value).isdigit() else None


def none_if_empty(value: Any) -> Any:
    """功能：把高德接口中的空字符串、空数组和空对象统一成 None。

    参数：
        value：任意高德字段值。
    返回值：
        空值返回 None，其余原样返回。
    """
    return None if value in ("", [], {}) else value


def summarize_transit_plan(best_transit: dict[str, Any]) -> str:
    """功能：从高德公交方案中提取人能读懂的线路摘要。

    参数：
        best_transit：高德 transits 数组中选出的最优公交方案。
    返回值：
        返回公交/地铁线路文字摘要；无法解析时返回兜底文案。
    """
    parts = []
    for segment in best_transit.get("segments", []):
        if not isinstance(segment, dict):
            continue
        buslines = segment.get("bus", {}).get("buslines", [])
        if not buslines:
            continue
        line = buslines[0]
        name = line.get("name", "")
        departure = line.get("departure_stop", {}).get("name", "")
        arrival = line.get("arrival_stop", {}).get("name", "")
        if name:
            parts.append(f"{name}: {departure} -> {arrival}")
    return "；".join(parts) if parts else "未解析到公交/地铁线路明细"


def compact_transit(best_transit: dict[str, Any]) -> dict[str, Any]:
    """功能：压缩高德公交原始结构，只保留前端调试和行程详情需要的字段。

    参数：
        best_transit：高德 transits 数组中选出的最优公交方案。
    返回值：
        返回包含时长、距离、费用和分段线路的字典。
    """
    return {
        "duration": best_transit.get("duration"),
        "distance": best_transit.get("distance"),
        "walking_distance": best_transit.get("walking_distance"),
        "cost": none_if_empty(best_transit.get("cost")),
        "segments": compact_segments(best_transit.get("segments", [])),
    }


def compact_segments(segments: Any) -> list[dict[str, Any]]:
    """功能：把高德公交分段压缩成步行 path 与公交线路字段。

    参数：
        segments：高德公交方案中的 segments 字段。
    返回值：
        返回压缩后的分段列表。
    """
    compacted = []
    if not isinstance(segments, list):
        return compacted
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        buslines = segment.get("bus", {}).get("buslines", [])
        line = buslines[0] if buslines else {}
        compacted.append(
            {
                "walking_distance": segment.get("walking", {}).get("distance"),
                "walking_path": extract_walking_segment_path(segment),
                "busline": {
                    "name": line.get("name"),
                    "type": line.get("type"),
                    "departure_stop": line.get("departure_stop", {}).get("name"),
                    "arrival_stop": line.get("arrival_stop", {}).get("name"),
                    "via_num": line.get("via_num"),
                    "distance": line.get("distance"),
                    "duration": line.get("duration"),
                    "path": parse_polyline(line.get("polyline")),
                }
                if line
                else None,
            }
        )
    return compacted


def extract_transit_path(best_transit: dict[str, Any]) -> list[dict[str, float]]:
    """功能：从高德公交方案中提取完整真实 polyline 路径。

    参数：
        best_transit：高德 transits 数组中选出的最优公交方案。
    返回值：
        返回按行进顺序排列的经纬度点列表。
    """
    path: list[dict[str, float]] = []
    for segment in best_transit.get("segments", []):
        if not isinstance(segment, dict):
            continue
        path.extend(extract_walking_segment_path(segment))
        buslines = segment.get("bus", {}).get("buslines", [])
        for line in buslines if isinstance(buslines, list) else []:
            if isinstance(line, dict):
                path.extend(parse_polyline(line.get("polyline")))
    return dedupe_consecutive_path(path)


def extract_walking_segment_path(segment: dict[str, Any]) -> list[dict[str, float]]:
    """功能：从公交分段中的步行 steps 提取真实 polyline 路径。

    参数：
        segment：高德公交方案中的单个 segment。
    返回值：
        返回步行部分的经纬度点列表。
    """
    path: list[dict[str, float]] = []
    walking = segment.get("walking") if isinstance(segment.get("walking"), dict) else {}
    steps = walking.get("steps", []) if isinstance(walking, dict) else []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            path.extend(parse_polyline(step.get("polyline")))
    return dedupe_consecutive_path(path)


def extract_walking_path(path_payload: dict[str, Any]) -> list[dict[str, float]]:
    """功能：从高德步行方案 steps 中提取完整真实 polyline 路径。

    参数：
        path_payload：高德步行接口 paths 数组中的单个方案。
    返回值：
        返回按行进顺序排列的经纬度点列表。
    """
    path: list[dict[str, float]] = []
    steps = path_payload.get("steps", [])
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            path.extend(parse_polyline(step.get("polyline")))
    return dedupe_consecutive_path(path)


def parse_polyline(polyline: Any) -> list[dict[str, float]]:
    """功能：把高德 polyline 字符串解析为前端地图可用坐标点。

    参数：
        polyline：高德返回的 "lng,lat;lng,lat" 字符串。
    返回值：
        返回 [{"lng": 经度, "lat": 纬度}] 形式的点列表。
    """
    if not isinstance(polyline, str) or not polyline.strip():
        return []
    points = []
    for pair in polyline.split(";"):
        if "," not in pair:
            continue
        lng_text, lat_text = pair.split(",", 1)
        try:
            lng = float(lng_text)
            lat = float(lat_text)
        except ValueError:
            continue
        if math.isfinite(lng) and math.isfinite(lat):
            points.append({"lng": lng, "lat": lat})
    return points


def dedupe_consecutive_path(path: list[dict[str, float]]) -> list[dict[str, float]]:
    """功能：去掉路径中连续重复的坐标点，减少前端绘制冗余。

    参数：
        path：经纬度点列表。
    返回值：
        返回去重后的经纬度点列表。
    """
    deduped = []
    for point in path:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    return deduped
