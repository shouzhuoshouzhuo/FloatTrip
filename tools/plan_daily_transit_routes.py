#!/usr/bin/env python3
"""Plan daily FloatTrip attraction visit order with AMap transit durations."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from geo_day_cluster import cluster_candidates_by_days


SCHEMA_VERSION = "floattrip_daily_transit_routes.v1"
LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"
AMAP_TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"
AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
EARTH_RADIUS_KM = 6371.0088
WALKING_FALLBACK_MAX_METERS = 1500
WALKING_SPEED_METERS_PER_SECOND = 1.25
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripTransitRoutePlanner/0.1"
)


class AMapTransitError(RuntimeError):
    """Raised when AMap transit routing does not return a usable route."""


def load_local_env() -> None:
    """Load project-local env vars without overriding exported values."""
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
    api_key = os.getenv("AMAP_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 AMAP_API_KEY。请在环境变量或 .env.local 中配置高德 Web服务 Key 后重试。")
    return api_key


def load_candidate_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("候选池文件必须是 JSON object")
    if not isinstance(payload.get("candidate_pool"), list):
        raise RuntimeError("候选池文件缺少 candidate_pool 数组")
    return payload


def http_get_json(url: str, timeout: int = 15) -> dict[str, Any]:
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
    raise AMapTransitError(f"请求失败：{redact_url(url)}；原因：{last_error}")


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if "key" in query:
        query["key"] = ["<redacted>"]
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
    )


def lnglat_text(candidate: dict[str, Any]) -> str:
    location = candidate_location(candidate)
    return f"{location['lng']},{location['lat']}"


def candidate_location(candidate: dict[str, Any]) -> dict[str, float]:
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    location = poi.get("location") if isinstance(poi.get("location"), dict) else None
    if not isinstance(location, dict):
        raise ValueError(f"candidate is missing poi.location: {candidate_name(candidate)!r}")
    lng = finite_float(location.get("lng"), "lng", candidate)
    lat = finite_float(location.get("lat"), "lat", candidate)
    if not -180 <= lng <= 180 or not -90 <= lat <= 90:
        raise ValueError(f"candidate has out-of-range poi.location: {candidate_name(candidate)!r}")
    return {"lng": lng, "lat": lat}


def finite_float(value: Any, field: str, candidate: dict[str, Any]) -> float:
    if isinstance(value, bool):
        raise ValueError(f"candidate has invalid {field}: {candidate_name(candidate)!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"candidate has invalid {field}: {candidate_name(candidate)!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"candidate has invalid {field}: {candidate_name(candidate)!r}")
    return number


def candidate_name(candidate: dict[str, Any]) -> str:
    return str(candidate.get("name") or candidate.get("poi", {}).get("name") or "<unnamed>")


def query_amap_transit_by_location(
    origin_lnglat: str,
    destination_lnglat: str,
    city: str,
    api_key: str,
    strategy: int = 0,
) -> dict[str, Any]:
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
        raise AMapTransitError(
            f"高德公交路径规划失败：info={data.get('info')}, infocode={data.get('infocode')}"
        )

    transits = data.get("route", {}).get("transits", [])
    valid_transits = [
        transit
        for transit in transits
        if isinstance(transit, dict) and str(transit.get("duration", "")).isdigit()
    ]
    if not valid_transits:
        raise AMapTransitError("高德没有返回可用公交路线")

    best = min(valid_transits, key=lambda item: int(item["duration"]))
    duration_seconds = int(best["duration"])
    distance_meters = int_or_none(best.get("distance"))
    walking_distance_meters = int_or_none(best.get("walking_distance"))
    return {
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


def int_or_none(value: Any) -> int | None:
    return int(value) if str(value).isdigit() else None


def none_if_empty(value: Any) -> Any:
    return None if value in ("", [], {}) else value


def summarize_transit_plan(best_transit: dict[str, Any]) -> str:
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
    return {
        "duration": best_transit.get("duration"),
        "distance": best_transit.get("distance"),
        "walking_distance": best_transit.get("walking_distance"),
        "cost": none_if_empty(best_transit.get("cost")),
        "segments": compact_segments(best_transit.get("segments", [])),
    }


def compact_segments(segments: Any) -> list[dict[str, Any]]:
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
    path: list[dict[str, float]] = []
    walking = segment.get("walking") if isinstance(segment.get("walking"), dict) else {}
    steps = walking.get("steps", []) if isinstance(walking, dict) else []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            path.extend(parse_polyline(step.get("polyline")))
    return dedupe_consecutive_path(path)


def parse_polyline(polyline: Any) -> list[dict[str, float]]:
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
    deduped = []
    for point in path:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    return deduped


def query_amap_walking_by_location(
    origin_lnglat: str,
    destination_lnglat: str,
    api_key: str,
) -> dict[str, Any]:
    params = {
        "key": api_key,
        "origin": origin_lnglat,
        "destination": destination_lnglat,
        "output": "json",
    }
    data = http_get_json(f"{AMAP_WALKING_URL}?{urllib.parse.urlencode(params)}")
    if data.get("status") != "1":
        raise AMapTransitError(
            f"高德步行路径规划失败：info={data.get('info')}, infocode={data.get('infocode')}"
        )

    paths = data.get("route", {}).get("paths", [])
    valid_paths = [
        path
        for path in paths
        if isinstance(path, dict) and str(path.get("duration", "")).isdigit()
    ]
    if not valid_paths:
        raise AMapTransitError("高德没有返回可用步行路线")

    best = min(valid_paths, key=lambda item: int(item["duration"]))
    path_points = extract_walking_path(best)
    if len(path_points) < 2:
        raise AMapTransitError("高德步行路线缺少真实 polyline")

    duration_seconds = int(best["duration"])
    distance_meters = int_or_none(best.get("distance"))
    return {
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


def extract_walking_path(path_payload: dict[str, Any]) -> list[dict[str, float]]:
    path: list[dict[str, float]] = []
    steps = path_payload.get("steps", [])
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            path.extend(parse_polyline(step.get("polyline")))
    return dedupe_consecutive_path(path)


def build_transit_time_matrix(
    candidates: list[dict[str, Any]],
    city: str,
    api_key: str,
    strategy: int = 0,
    request_interval: float = 0.4,
) -> tuple[list[list[int | None]], dict[tuple[int, int], dict[str, Any]], list[str]]:
    matrix: list[list[int | None]] = [
        [0 if left == right else None for right in range(len(candidates))]
        for left in range(len(candidates))
    ]
    segment_results: dict[tuple[int, int], dict[str, Any]] = {}
    warnings = []

    for origin_index, destination_index in itertools.permutations(range(len(candidates)), 2):
        origin = candidates[origin_index]
        destination = candidates[destination_index]
        try:
            transit = query_amap_transit_by_location(
                lnglat_text(origin),
                lnglat_text(destination),
                city,
                api_key,
                strategy,
            )
        except Exception as exc:
            try:
                walking_fallback = build_walking_fallback(origin, destination, api_key)
            except Exception as walking_exc:
                walking_fallback = None
                walking_error = walking_exc
            else:
                walking_error = None
            if walking_fallback:
                matrix[origin_index][destination_index] = walking_fallback["duration_seconds"]
                segment_results[(origin_index, destination_index)] = walking_fallback
                warnings.append(
                    f"{candidate_name(origin)} -> {candidate_name(destination)} 公交通行时间获取失败，已用近距离步行兜底：{exc}"
                )
            else:
                detail = f"{exc}"
                if walking_error:
                    detail = f"{exc}；步行兜底失败：{walking_error}"
                warnings.append(
                    f"{candidate_name(origin)} -> {candidate_name(destination)} 公交通行时间获取失败：{detail}"
                )
                continue
        else:
            matrix[origin_index][destination_index] = transit["duration_seconds"]
            segment_results[(origin_index, destination_index)] = transit
            if not transit.get("path"):
                warnings.append(
                    f"{candidate_name(origin)} -> {candidate_name(destination)} 高德未返回真实路径 polyline"
                )
        if request_interval > 0:
            time.sleep(request_interval)

    return matrix, segment_results, warnings


def build_walking_fallback(
    origin: dict[str, Any],
    destination: dict[str, Any],
    api_key: str,
) -> dict[str, Any] | None:
    distance_meters = round(candidate_distance_meters(origin, destination))
    if distance_meters > WALKING_FALLBACK_MAX_METERS:
        return None
    return query_amap_walking_by_location(
        lnglat_text(origin),
        lnglat_text(destination),
        api_key,
    )


def candidate_distance_meters(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_location = candidate_location(left)
    right_location = candidate_location(right)
    left_lng = math.radians(left_location["lng"])
    left_lat = math.radians(left_location["lat"])
    right_lng = math.radians(right_location["lng"])
    right_lat = math.radians(right_location["lat"])
    lat_delta = right_lat - left_lat
    lng_delta = right_lng - left_lng
    haversine = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(left_lat) * math.cos(right_lat) * math.sin(lng_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(haversine))) * 1000


def optimize_visit_order(
    candidates: list[dict[str, Any]],
    duration_matrix: list[list[int | None]],
    start_index: int = 0,
) -> tuple[list[int], bool]:
    best_order: tuple[int, ...] | None = None
    best_duration: int | None = None
    if not candidates:
        return [], True
    remaining_indexes = [index for index in range(len(candidates)) if index != start_index]
    for tail in itertools.permutations(remaining_indexes):
        order = (start_index, *tail)
        total = route_duration(order, duration_matrix)
        if total is None:
            continue
        if best_duration is None or total < best_duration:
            best_duration = total
            best_order = order
    if best_order is not None:
        return list(best_order), True
    return fallback_candidate_order(candidates), False


def route_duration(order: tuple[int, ...] | list[int], duration_matrix: list[list[int | None]]) -> int | None:
    total = 0
    for origin, destination in zip(order, order[1:]):
        duration = duration_matrix[origin][destination]
        if duration is None:
            return None
        total += duration
    return total


def fallback_candidate_order(candidates: list[dict[str, Any]]) -> list[int]:
    return [
        index
        for index, _candidate in sorted(
            enumerate(candidates),
            key=lambda indexed: (
                -candidate_score(indexed[1]),
                -candidate_mentions(indexed[1]),
                candidate_name(indexed[1]),
                indexed[0],
            ),
        )
    ]


def candidate_score(candidate: dict[str, Any]) -> float:
    value = candidate.get("score")
    if value in (None, ""):
        return float(candidate_mentions(candidate))
    try:
        score = float(value)
    except (TypeError, ValueError):
        return float(candidate_mentions(candidate))
    return score if math.isfinite(score) else float(candidate_mentions(candidate))


def candidate_mentions(candidate: dict[str, Any]) -> int:
    try:
        return int(candidate.get("mention_count") or 0)
    except (TypeError, ValueError):
        return 0


def build_daily_route_plan(
    payload: dict[str, Any],
    days: int,
    *,
    api_key: str,
    strategy: int = 0,
    min_cluster_size: int = 2,
    max_iterations: int = 50,
    request_interval: float = 0.4,
    max_day_radius_km: float = 6.0,
) -> dict[str, Any]:
    candidates = payload.get("candidate_pool")
    if not isinstance(candidates, list):
        raise RuntimeError("候选池文件缺少 candidate_pool 数组")
    destination = str(payload.get("destination") or "").strip()
    if not destination:
        raise RuntimeError("候选池文件缺少 destination，无法作为高德公交 city 参数")

    clusters = cluster_candidates_by_days(
        candidates,
        days,
        min_cluster_size=min_cluster_size,
        max_iterations=max_iterations,
    )
    output_warnings = []
    day_plans = []
    clustered_candidate_ids = {
        candidate_identity(candidate)
        for cluster in clusters
        for candidate in cluster.get("candidates", [])
    }
    assigned_candidate_ids: set[str] = set()
    for day_index, cluster in enumerate(clusters, start=1):
        day_candidates = select_daily_candidates(
            list(cluster.get("candidates", [])),
            all_candidates=candidates,
            blocked_candidate_ids=clustered_candidate_ids | assigned_candidate_ids,
            medoid=cluster.get("medoid"),
            max_day_radius_km=max_day_radius_km,
        )
        assigned_candidate_ids.update(candidate_identity(candidate) for candidate in day_candidates)
        matrix, segment_results, warnings = build_transit_time_matrix(
            day_candidates,
            destination,
            api_key,
            strategy,
            request_interval,
        )
        output_warnings.extend(
            f"day {day_index}: {warning}" for warning in warnings
        )
        order, complete = optimize_visit_order(day_candidates, matrix)
        if not complete and len(day_candidates) > 1:
            output_warnings.append(f"day {day_index}: 没有完整可行公交访问顺序，已回退到候选排序")
        spots = [candidate_to_spot(candidate, index) for index, candidate in enumerate(day_candidates)]
        route_segments = build_route_segments(order, spots, matrix, segment_results)
        total_duration = route_duration(order, matrix)
        failed_segment_count = count_failed_segments(order, matrix)
        day_plans.append(
            {
                "day_index": day_index,
                "cluster_id": int(cluster.get("cluster_id", day_index - 1)),
                "spots": spots,
                "duration_matrix_seconds": matrix,
                "optimized_order": [spots[index]["spot_id"] for index in order],
                "route_segments": route_segments,
                "summary": {
                    "spot_count": len(spots),
                    "total_duration_seconds": total_duration,
                    "total_duration_minutes": round(total_duration / 60, 1)
                    if total_duration is not None
                    else None,
                    "failed_segment_count": failed_segment_count,
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "destination": destination,
        "days_count": days,
        "route_mode": "amap_transit",
        "strategy": strategy,
        "days": day_plans,
        "warnings": output_warnings,
    }


def select_daily_candidates(
    candidates: list[dict[str, Any]],
    *,
    all_candidates: list[dict[str, Any]] | None = None,
    blocked_candidate_ids: set[str] | None = None,
    medoid: dict[str, Any] | None = None,
    limit: int = 4,
    max_day_radius_km: float = 6.0,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    anchor = medoid if isinstance(medoid, dict) else candidates[0]
    nearby_original = [
        candidate
        for candidate in candidates
        if candidate_distance_meters(anchor, candidate) <= max_day_radius_km * 1000
    ]
    selected = sorted(
        nearby_original if nearby_original else candidates,
        key=lambda candidate: (
            -candidate_score(candidate),
            -candidate_mentions(candidate),
            candidate_name(candidate),
        ),
    )[:limit]

    if len(selected) >= min(limit, len(candidates)) or not all_candidates:
        return selected

    selected_ids = {candidate_identity(candidate) for candidate in selected}
    blocked_ids = blocked_candidate_ids or set()
    same_district_candidates = [
        candidate
        for candidate in all_candidates
        if candidate_identity(candidate) not in selected_ids
        and candidate_identity(candidate) not in blocked_ids
        and candidate_district(candidate) == candidate_district(anchor)
        and candidate_distance_meters(anchor, candidate) <= max_day_radius_km * 1000
    ]
    for candidate in sorted(
        same_district_candidates,
        key=lambda item: (
            candidate_distance_meters(anchor, item),
            -candidate_score(item),
            -candidate_mentions(item),
            candidate_name(item),
        ),
    ):
        selected.append(candidate)
        selected_ids.add(candidate_identity(candidate))
        if len(selected) >= limit:
            break
    return selected


def candidate_identity(candidate: dict[str, Any]) -> str:
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    return str(poi.get("id") or candidate.get("name") or id(candidate))


def candidate_district(candidate: dict[str, Any]) -> str:
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    return str(poi.get("district") or "")


def candidate_to_spot(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    location = candidate_location(candidate)
    spot_id = str(poi.get("id") or f"spot-{index + 1}")
    return {
        "spot_id": spot_id,
        "name": candidate_name(candidate),
        "poi_name": none_if_empty(poi.get("name")),
        "poi_type": none_if_empty(poi.get("type")),
        "address": none_if_empty(poi.get("address")),
        "location": location,
        "mention_count": candidate.get("mention_count"),
        "score": candidate.get("score"),
        "preference_score": candidate.get("preference_score"),
    }


def build_route_segments(
    order: list[int],
    spots: list[dict[str, Any]],
    matrix: list[list[int | None]],
    segment_results: dict[tuple[int, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    segments = []
    for origin, destination in zip(order, order[1:]):
        transit = segment_results.get((origin, destination), {})
        segments.append(
            {
                "from_spot_id": spots[origin]["spot_id"],
                "from_name": spots[origin]["name"],
                "to_spot_id": spots[destination]["spot_id"],
                "to_name": spots[destination]["name"],
                "duration_seconds": matrix[origin][destination],
                "duration_minutes": transit.get("duration_minutes"),
                "distance_meters": transit.get("distance_meters"),
                "walking_distance_meters": transit.get("walking_distance_meters"),
                "cost": transit.get("cost"),
                "summary": transit.get("summary"),
                "amap_transit": transit.get("amap_transit"),
                "fallback_mode": transit.get("fallback_mode"),
                "path": transit.get("path") or [],
            }
        )
    return segments


def count_failed_segments(order: list[int], matrix: list[list[int | None]]) -> int:
    return sum(
        1
        for origin, destination in zip(order, order[1:])
        if matrix[origin][destination] is None
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按天生成 FloatTrip 高德公交路线规划 JSON。")
    parser.add_argument("input_json", type=Path, help="amap_poi_filter.py --json 输出的候选池 JSON")
    parser.add_argument("--days", type=int, required=True, help="旅行天数，也是地理聚类天数")
    parser.add_argument("--output", type=Path, help="输出 JSON 文件路径；不传则输出到 stdout")
    parser.add_argument("--strategy", type=int, default=0, help="高德公交策略，默认 0 最快捷")
    parser.add_argument("--min-cluster-size", type=int, default=2, help="每一天最少景点数，默认 2")
    parser.add_argument("--max-iterations", type=int, default=50, help="K-Medoids 最大迭代轮数，默认 50")
    parser.add_argument("--request-interval", type=float, default=0.4, help="高德公交请求间隔秒数，默认 0.4")
    parser.add_argument("--max-day-radius-km", type=float, default=6.0, help="每天围绕簇中心选点的最大半径，默认 6km")
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()
    try:
        payload = load_candidate_payload(args.input_json)
        output = build_daily_route_plan(
            payload,
            args.days,
            api_key=require_amap_key(),
            strategy=args.strategy,
            min_cluster_size=args.min_cluster_size,
            max_iterations=args.max_iterations,
            request_interval=args.request_interval,
            max_day_radius_km=args.max_day_radius_km,
        )
    except Exception as exc:
        print(f"每日公交路线规划失败：{exc}", file=sys.stderr)
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
