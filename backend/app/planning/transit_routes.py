"""按天生成 FloatTrip 真实公交/步行路线计划。"""

from __future__ import annotations

import itertools
import math
import time
from typing import Any

from backend.app.planning.day_clustering import (
    cluster_candidates_by_days,
    prepare_candidates_for_clustering,
)
from backend.app.providers import amap
from backend.app.schemas.route_plan import (
    DayRoutePlan,
    DaySummaryMetrics,
    RouteSegment,
    SpotMapItem,
    TripRoutePlanResponse,
)
from backend.app.services.planner_logging import (
    compact_candidates_for_log,
    compact_clusters_for_log,
    log_planner_event,
)


SCHEMA_VERSION = "floattrip_daily_transit_routes.v1"
EARTH_RADIUS_KM = 6371.0088
WALKING_FALLBACK_MAX_METERS = 1500


def build_daily_transit_route_plan(
    candidates: list[dict[str, Any]],
    destination: str,
    days: int,
    *,
    api_key: str,
    strategy: int = 0,
    min_cluster_size: int = 2,
    max_iterations: int = 50,
    request_interval: float = 0.4,
    max_day_radius_km: float = 6.0,
    request_id: str | None = None,
    preferences: list[str] | None = None,
) -> TripRoutePlanResponse:
    """功能：把已补高德坐标的候选景点生成可直接返回前端的每日真实路线。

    参数：
        candidates：已包含 poi.location 的候选景点字典列表。
        destination：目的地城市名称或城市编码，用于高德公交 city 参数。
        days：旅行天数，也是地理聚类数量。
        api_key：高德 Web 服务 Key。
        strategy：高德公交策略，默认 0 表示最快捷。
        min_cluster_size：每个地理簇的最小景点数。
        max_iterations：地理聚类最大迭代次数。
        request_interval：两次高德路线请求之间的等待秒数。
        max_day_radius_km：每天围绕簇中心补点时允许的最大半径。
        request_id：一次规划调用的请求追踪 ID，用于串联日志。
        preferences：用户偏好列表，用于写入聚类输入日志。
    返回值：
        返回 TripRoutePlanResponse，包含每日景点、访问顺序、真实路线段和警告信息。
    """
    destination_text = destination.strip()
    if not destination_text:
        raise ValueError("destination must not be empty")

    cluster_input_candidates = prepare_candidates_for_clustering(
        candidates,
        days,
        min_cluster_size=min_cluster_size,
    )
    if request_id:
        log_planner_event(
            "cluster_input_candidate_pool",
            request_id,
            {
                "destination": destination_text,
                "days": days,
                "preferences": preferences or [],
                "min_cluster_size": min_cluster_size,
                "max_iterations": max_iterations,
                "stage": "按用户必去优先、分数、出现次数截取后的实际聚类输入；数量上限为 3 * days",
                "candidates": compact_candidates_for_log(cluster_input_candidates),
            },
        )

    clusters = cluster_candidates_by_days(
        cluster_input_candidates,
        days,
        min_cluster_size=min_cluster_size,
        max_iterations=max_iterations,
    )
    if request_id:
        log_planner_event(
            "cluster_result",
            request_id,
            {
                "destination": destination_text,
                "days": days,
                "preferences": preferences or [],
                "min_cluster_size": min_cluster_size,
                "max_iterations": max_iterations,
                "clusters": compact_clusters_for_log(clusters),
            },
        )
    warnings: list[str] = []
    day_plans: list[DayRoutePlan] = []
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
        matrix, segment_results, day_warnings = build_transit_time_matrix(
            day_candidates,
            destination_text,
            api_key,
            strategy=strategy,
            request_interval=request_interval,
        )
        warnings.extend(f"day {day_index}: {warning}" for warning in day_warnings)
        order, complete = optimize_visit_order(day_candidates, matrix)
        if not complete and len(day_candidates) > 1:
            warnings.append(f"day {day_index}: 没有完整可行公交访问顺序，已回退到候选排序")
        spots = [
            candidate_to_spot(candidate, order=index + 1)
            for index, candidate in enumerate(day_candidates)
        ]
        route_segments = build_route_segments(order, spots, matrix, segment_results)
        total_duration = route_duration(order, matrix)
        failed_segment_count = count_failed_segments(order, matrix)
        route_status = "route_planned" if failed_segment_count == 0 else "route_partial"
        day_plans.append(
            DayRoutePlan(
                day_index=day_index,
                cluster_id=int(cluster.get("cluster_id", day_index - 1)),
                spots=spots,
                route_order=[spots[index].name for index in order],
                route_segments=route_segments,
                summary_metrics=DaySummaryMetrics(
                    spot_count=len(spots),
                    cluster_radius_km=float(cluster.get("radius_km") or 0.0),
                    route_status=route_status,
                    total_duration_seconds=total_duration,
                    total_duration_minutes=round(total_duration / 60, 1)
                    if total_duration is not None
                    else None,
                    failed_segment_count=failed_segment_count,
                ),
                duration_matrix_seconds=matrix,
                optimized_order=[spots[index].spot_id or spots[index].name for index in order],
            )
        )

    return TripRoutePlanResponse(
        schema_version=SCHEMA_VERSION,
        destination=destination_text,
        days_count=days,
        route_mode="amap_transit",
        strategy=strategy,
        days=day_plans,
        warnings=warnings,
    )


def build_transit_time_matrix(
    candidates: list[dict[str, Any]],
    city: str,
    api_key: str,
    *,
    strategy: int = 0,
    request_interval: float = 0.4,
) -> tuple[list[list[int | None]], dict[tuple[int, int], dict[str, Any]], list[str]]:
    """功能：为某一天景点生成两两通行时间矩阵和路线段原始结果。

    参数：
        candidates：当天候选景点字典列表。
        city：高德公交规划城市名称或城市编码。
        api_key：高德 Web 服务 Key。
        strategy：高德公交策略。
        request_interval：两次高德请求之间的等待秒数。
    返回值：
        返回三元组：时长矩阵、按起终点索引保存的路线结果、警告列表。
    """
    matrix: list[list[int | None]] = [
        [0 if left == right else None for right in range(len(candidates))]
        for left in range(len(candidates))
    ]
    segment_results: dict[tuple[int, int], dict[str, Any]] = {}
    warnings: list[str] = []

    for origin_index, destination_index in itertools.permutations(range(len(candidates)), 2):
        origin = candidates[origin_index]
        destination = candidates[destination_index]
        try:
            transit = amap.query_transit_route(
                lnglat_text(origin),
                lnglat_text(destination),
                city,
                api_key,
                strategy,
            )
        except Exception as exc:
            transit = build_walking_fallback(origin, destination, api_key)
            if transit is None:
                warnings.append(
                    f"{candidate_name(origin)} -> {candidate_name(destination)} 公交通行时间获取失败：{exc}"
                )
                continue
            warnings.append(
                f"{candidate_name(origin)} -> {candidate_name(destination)} 公交通行时间获取失败，已用近距离步行兜底：{exc}"
            )

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
    """功能：当公交路线失败且两点足够近时，调用高德步行路线作为兜底。

    参数：
        origin：起点候选景点字典。
        destination：终点候选景点字典。
        api_key：高德 Web 服务 Key。
    返回值：
        距离足够近且步行可用时返回路线字典，否则返回 None。
    """
    distance_meters = round(candidate_distance_meters(origin, destination))
    if distance_meters > WALKING_FALLBACK_MAX_METERS:
        return None
    return amap.query_walking_route(
        lnglat_text(origin),
        lnglat_text(destination),
        api_key,
    )


def optimize_visit_order(
    candidates: list[dict[str, Any]],
    duration_matrix: list[list[int | None]],
    start_index: int = 0,
) -> tuple[list[int], bool]:
    """功能：暴力枚举当天景点访问顺序，找到总通行时间最短的顺序。

    参数：
        candidates：当天候选景点字典列表。
        duration_matrix：两两通行时间矩阵。
        start_index：固定作为起点的候选索引，默认第一个景点。
    返回值：
        返回二元组：景点索引顺序、是否找到完整可行路线。
    """
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


def route_duration(
    order: tuple[int, ...] | list[int],
    duration_matrix: list[list[int | None]],
) -> int | None:
    """功能：计算一个访问顺序的总通行时间。

    参数：
        order：景点索引访问顺序。
        duration_matrix：两两通行时间矩阵。
    返回值：
        全部路段可达时返回总秒数；任一路段缺失时返回 None。
    """
    total = 0
    for origin, destination in zip(order, order[1:]):
        duration = duration_matrix[origin][destination]
        if duration is None:
            return None
        total += duration
    return total


def fallback_candidate_order(candidates: list[dict[str, Any]]) -> list[int]:
    """功能：在没有完整路线矩阵时，按候选评分回退生成访问顺序。

    参数：
        candidates：当天候选景点字典列表。
    返回值：
        返回按评分、出现次数和名称排序后的景点索引列表。
    """
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


def select_daily_candidates(
    candidates: list[dict[str, Any]],
    *,
    all_candidates: list[dict[str, Any]] | None = None,
    blocked_candidate_ids: set[str] | None = None,
    medoid: dict[str, Any] | None = None,
    limit: int = 4,
    max_day_radius_km: float = 6.0,
) -> list[dict[str, Any]]:
    """功能：从某个地理簇中选择当天 2 到 4 个紧凑景点。

    参数：
        candidates：当前地理簇内的候选景点。
        all_candidates：全部候选景点，用于同区补点。
        blocked_candidate_ids：已经分配或不应重复使用的候选 ID。
        medoid：当前簇中心候选点。
        limit：每天最多景点数。
        max_day_radius_km：围绕簇中心选点的最大半径。
    返回值：
        返回当天最终选中的候选景点列表。
    """
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


def build_route_segments(
    order: list[int],
    spots: list[SpotMapItem],
    matrix: list[list[int | None]],
    segment_results: dict[tuple[int, int], dict[str, Any]],
) -> list[RouteSegment]:
    """功能：把最优访问顺序和高德路线结果转换成前端路线段结构。

    参数：
        order：景点索引访问顺序。
        spots：当天景点点位模型列表。
        matrix：两两通行时间矩阵。
        segment_results：按起终点索引保存的高德路线结果。
    返回值：
        返回前端可绘制的 RouteSegment 列表。
    """
    segments = []
    for origin, destination in zip(order, order[1:]):
        transit = segment_results.get((origin, destination), {})
        segments.append(
            RouteSegment(
                from_spot_id=spots[origin].spot_id,
                from_name=spots[origin].name,
                to_spot_id=spots[destination].spot_id,
                to_name=spots[destination].name,
                mode=transit.get("mode") or "unknown",
                duration_seconds=matrix[origin][destination],
                duration_minutes=transit.get("duration_minutes"),
                distance_meters=transit.get("distance_meters"),
                walking_distance_meters=transit.get("walking_distance_meters"),
                cost=str(transit.get("cost")) if transit.get("cost") is not None else None,
                summary=transit.get("summary"),
                amap_transit=transit.get("amap_transit"),
                fallback_mode=transit.get("fallback_mode"),
                path=transit.get("path") or [],
            )
        )
    return segments


def count_failed_segments(order: list[int], matrix: list[list[int | None]]) -> int:
    """功能：统计访问顺序中缺失通行时间的路段数量。

    参数：
        order：景点索引访问顺序。
        matrix：两两通行时间矩阵。
    返回值：
        返回缺失路线段数量。
    """
    return sum(
        1
        for origin, destination in zip(order, order[1:])
        if matrix[origin][destination] is None
    )


def candidate_to_spot(candidate: dict[str, Any], order: int) -> SpotMapItem:
    """功能：把候选景点字典转换成前端地图点位模型。

    参数：
        candidate：单个候选景点字典。
        order：景点在当天列表中的展示顺序，从 1 开始。
    返回值：
        返回 SpotMapItem 模型。
    """
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    location = candidate_location(candidate)
    return SpotMapItem(
        spot_id=str(poi.get("id") or f"spot-{order}"),
        name=candidate_name(candidate),
        order=order,
        location=location,
        address=str(poi.get("address") or "") or None,
        poi_type=str(poi.get("type") or "") or None,
        raw_candidate=candidate,
    )


def lnglat_text(candidate: dict[str, Any]) -> str:
    """功能：读取候选景点坐标并转换成高德接口需要的字符串。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回 "lng,lat" 格式坐标字符串。
    """
    location = candidate_location(candidate)
    return f"{location['lng']},{location['lat']}"


def candidate_location(candidate: dict[str, Any]) -> dict[str, float]:
    """功能：从候选景点中读取并校验经纬度。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回 {"lng": 经度, "lat": 纬度} 字典。
    """
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
    """功能：把候选景点坐标字段转换成有限浮点数。

    参数：
        value：待转换的坐标值。
        field：字段名，用于错误提示。
        candidate：当前候选景点字典，用于错误提示。
    返回值：
        返回转换后的有限浮点数。
    """
    if isinstance(value, bool):
        raise ValueError(f"candidate has invalid {field}: {candidate_name(candidate)!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"candidate has invalid {field}: {candidate_name(candidate)!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"candidate has invalid {field}: {candidate_name(candidate)!r}")
    return number


def candidate_distance_meters(left: dict[str, Any], right: dict[str, Any]) -> float:
    """功能：计算两个候选景点之间的球面直线距离。

    参数：
        left：第一个候选景点字典。
        right：第二个候选景点字典。
    返回值：
        返回两个坐标点之间的距离，单位为米。
    """
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


def candidate_identity(candidate: dict[str, Any]) -> str:
    """功能：生成候选景点的稳定身份标识，用于去重和跨天分配。

    参数：
        candidate：单个候选景点字典。
    返回值：
        优先返回高德 POI ID，其次返回景点名称。
    """
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    return str(poi.get("id") or candidate.get("name") or id(candidate))


def candidate_district(candidate: dict[str, Any]) -> str:
    """功能：读取候选景点所属区县名称。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回高德 POI district 字段，没有则返回空字符串。
    """
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    return str(poi.get("district") or "")


def candidate_name(candidate: dict[str, Any]) -> str:
    """功能：读取候选景点展示名称。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回候选名称、POI 名称或兜底名称。
    """
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    return str(candidate.get("name") or poi.get("name") or "<unnamed>")


def candidate_score(candidate: dict[str, Any]) -> float:
    """功能：读取候选景点评分，缺失或非法时回退到出现次数。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回可排序的浮点评分。
    """
    value = candidate.get("score")
    if value in (None, ""):
        return float(candidate_mentions(candidate))
    try:
        score = float(value)
    except (TypeError, ValueError):
        return float(candidate_mentions(candidate))
    return score if math.isfinite(score) else float(candidate_mentions(candidate))


def candidate_mentions(candidate: dict[str, Any]) -> int:
    """功能：读取候选景点在语料中的出现次数。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回整数出现次数，非法时返回 0。
    """
    try:
        return int(candidate.get("mention_count") or 0)
    except (TypeError, ValueError):
        return 0
