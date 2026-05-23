"""把已补高德坐标的候选景点按地理位置聚成每日区域。"""

from __future__ import annotations

import math
from typing import Any


EARTH_RADIUS_KM = 6371.0088
MAX_CANDIDATES_PER_DAY = 4


def cluster_candidates_by_days(
    candidates: list[dict[str, Any]],
    days: int,
    *,
    min_cluster_size: int = 2,
    max_iterations: int = 50,
) -> list[dict[str, Any]]:
    """把候选景点聚成指定天数的地理区域，为后续每日路线规划做准备。"""
    points = prepare_candidates_for_clustering(
        candidates,
        days,
        min_cluster_size=min_cluster_size,
    )
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")

    locations = [candidate_location(candidate) for candidate in points]
    distances = build_distance_matrix(locations)
    weights = [mention_weight(candidate) for candidate in points]
    medoids = initialize_medoids(distances, weights, days)
    clusters: list[list[int]] = []

    for _ in range(max_iterations):
        clusters = assign_to_nearest_medoids(distances, medoids)
        repair_small_clusters(clusters, medoids, distances, min_cluster_size)
        new_medoids = update_medoids(clusters, distances, weights)
        if new_medoids == medoids:
            medoids = new_medoids
            break
        medoids = new_medoids

    clusters = assign_to_nearest_medoids(distances, medoids)
    repair_small_clusters(clusters, medoids, distances, min_cluster_size)
    medoids = update_medoids(clusters, distances, weights)
    clusters = assign_to_nearest_medoids(distances, medoids)
    repair_small_clusters(clusters, medoids, distances, min_cluster_size)

    output = []
    for cluster_id, members in enumerate(clusters):
        medoid_index = medoids[cluster_id]
        radius_km = max(
            (distances[medoid_index][member] for member in members),
            default=0.0,
        )
        output.append(
            {
                "cluster_id": cluster_id,
                "medoid": points[medoid_index],
                "radius_km": round(radius_km, 3),
                "candidates": [points[index] for index in members],
            }
        )
    return output


def prepare_candidates_for_clustering(
    candidates: list[dict[str, Any]],
    days: int,
    *,
    min_cluster_size: int = 2,
) -> list[dict[str, Any]]:
    """校验候选景点，并按分数截取参与聚类的优先窗口。"""
    validate_cluster_inputs(candidates, days, min_cluster_size)
    for candidate in candidates:
        candidate_location(candidate)
        candidate_mention_count(candidate)

    minimum_candidates = days * min_cluster_size
    if len(candidates) < minimum_candidates:
        raise ValueError(
            f"need at least {minimum_candidates} candidates for {days} day cluster(s)"
        )

    limit = days * MAX_CANDIDATES_PER_DAY
    ranked = sorted(
        enumerate(candidates),
        key=lambda indexed: (
            -candidate_rank_score(indexed[1]),
            -candidate_mention_count(indexed[1]),
            str(indexed[1].get("name", "")),
            indexed[0],
        ),
    )
    selected = [candidate for _, candidate in ranked[:limit]]
    if len(selected) < minimum_candidates:
        raise ValueError(
            f"top candidate window cannot satisfy {days} cluster(s) of size {min_cluster_size}"
        )
    return selected


def validate_cluster_inputs(
    candidates: list[dict[str, Any]],
    days: int,
    min_cluster_size: int,
) -> None:
    """校验聚类输入的天数、最小簇大小和候选列表形态。"""
    if days < 1:
        raise ValueError("days must be at least 1")
    if min_cluster_size < 1:
        raise ValueError("min_cluster_size must be at least 1")
    if min_cluster_size > MAX_CANDIDATES_PER_DAY:
        raise ValueError(
            f"min_cluster_size cannot exceed {MAX_CANDIDATES_PER_DAY} in v1"
        )
    if not candidates:
        raise ValueError("candidates must not be empty")
    if not all(isinstance(candidate, dict) for candidate in candidates):
        raise ValueError("every candidate must be a dict")


def candidate_location(candidate: dict[str, Any]) -> tuple[float, float]:
    """从候选景点中读取经纬度，返回高德常用的经度、纬度顺序。"""
    poi = candidate.get("poi")
    location = poi.get("location") if isinstance(poi, dict) else None
    if not isinstance(location, dict):
        raise ValueError(f"candidate is missing poi.location: {candidate_label(candidate)}")
    lng = finite_float(location.get("lng"), "lng", candidate)
    lat = finite_float(location.get("lat"), "lat", candidate)
    if not -180 <= lng <= 180 or not -90 <= lat <= 90:
        raise ValueError(f"candidate has out-of-range coordinates: {candidate_label(candidate)}")
    return lng, lat


def finite_float(value: Any, field: str, candidate: dict[str, Any]) -> float:
    """把坐标字段转换成有限浮点数，并在异常时带上候选景点名称。"""
    if isinstance(value, bool):
        raise ValueError(f"candidate has invalid {field}: {candidate_label(candidate)}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"candidate has invalid {field}: {candidate_label(candidate)}"
        ) from exc
    if not math.isfinite(number):
        raise ValueError(f"candidate has invalid {field}: {candidate_label(candidate)}")
    return number


def candidate_label(candidate: dict[str, Any]) -> str:
    """生成用于错误信息的候选景点标签。"""
    return repr(str(candidate.get("name") or "<unnamed>"))


def candidate_mention_count(candidate: dict[str, Any]) -> int:
    """读取并校验候选景点在攻略语料中的出现次数。"""
    value = candidate.get("mention_count")
    if isinstance(value, bool):
        raise ValueError(f"candidate has invalid mention_count: {candidate_label(candidate)}")
    try:
        mention_count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"candidate has invalid mention_count: {candidate_label(candidate)}"
        ) from exc
    if mention_count < 1:
        raise ValueError(f"candidate has invalid mention_count: {candidate_label(candidate)}")
    return mention_count


def candidate_rank_score(candidate: dict[str, Any]) -> float:
    """读取候选景点评分；没有评分时回退到出现次数。"""
    value = candidate.get("score")
    if value in (None, ""):
        return float(candidate_mention_count(candidate))
    if isinstance(value, bool):
        return float(candidate_mention_count(candidate))
    try:
        score = float(value)
    except (TypeError, ValueError):
        return float(candidate_mention_count(candidate))
    return score if math.isfinite(score) else float(candidate_mention_count(candidate))


def mention_weight(candidate: dict[str, Any]) -> float:
    """把出现次数转换成聚类权重，避免高频景点被低估。"""
    return 1.0 + math.log(max(1, candidate_mention_count(candidate)))


def haversine_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    """用球面距离公式计算两个经纬度点之间的公里距离。"""
    left_lng, left_lat = map(math.radians, left)
    right_lng, right_lat = map(math.radians, right)
    lat_delta = right_lat - left_lat
    lng_delta = right_lng - left_lng
    haversine = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(left_lat) * math.cos(right_lat) * math.sin(lng_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(haversine)))


def build_distance_matrix(locations: list[tuple[float, float]]) -> list[list[float]]:
    """根据所有候选点坐标生成两两地理距离矩阵。"""
    distances = [[0.0 for _ in locations] for _ in locations]
    for left_index, left in enumerate(locations):
        for right_index in range(left_index + 1, len(locations)):
            distance = haversine_km(left, locations[right_index])
            distances[left_index][right_index] = distance
            distances[right_index][left_index] = distance
    return distances


def initialize_medoids(
    distances: list[list[float]],
    weights: list[float],
    cluster_count: int,
) -> list[int]:
    """用加权最远点策略初始化每日聚类中心。"""
    medoids = [max(range(len(weights)), key=lambda index: (weights[index], -index))]
    while len(medoids) < cluster_count:
        remaining = [index for index in range(len(weights)) if index not in medoids]
        next_medoid = max(
            remaining,
            key=lambda index: (
                min(distances[index][medoid] for medoid in medoids) * weights[index],
                weights[index],
                -index,
            ),
        )
        medoids.append(next_medoid)
    return medoids


def assign_to_nearest_medoids(
    distances: list[list[float]],
    medoids: list[int],
) -> list[list[int]]:
    """把每个候选点分配给最近的聚类中心。"""
    clusters = [[] for _ in medoids]
    for index in range(len(distances)):
        cluster_id = min(
            range(len(medoids)),
            key=lambda current: (distances[index][medoids[current]], current),
        )
        clusters[cluster_id].append(index)
    return clusters


def repair_small_clusters(
    clusters: list[list[int]],
    medoids: list[int],
    distances: list[list[float]],
    min_cluster_size: int,
) -> None:
    """当某个簇小于最小景点数时，从其他簇迁移代价最低的点。"""
    while True:
        small_cluster_id = next(
            (
                cluster_id
                for cluster_id, members in enumerate(clusters)
                if len(members) < min_cluster_size
            ),
            None,
        )
        if small_cluster_id is None:
            return

        move_options = []
        target_medoid = medoids[small_cluster_id]
        for source_cluster_id, members in enumerate(clusters):
            if source_cluster_id == small_cluster_id or len(members) <= min_cluster_size:
                continue
            source_medoid = medoids[source_cluster_id]
            for member in members:
                if member == source_medoid:
                    continue
                move_cost = distances[member][target_medoid] - distances[member][source_medoid]
                move_options.append((move_cost, distances[member][target_medoid], member, source_cluster_id))

        if not move_options:
            raise ValueError("cannot repair clusters to satisfy min_cluster_size")

        _, _, member, source_cluster_id = min(move_options)
        clusters[source_cluster_id].remove(member)
        clusters[small_cluster_id].append(member)


def update_medoids(
    clusters: list[list[int]],
    distances: list[list[float]],
    weights: list[float],
) -> list[int]:
    """在每个簇内部重新选择加权距离总和最小的真实候选点作为中心。"""
    medoids = []
    for members in clusters:
        if not members:
            raise ValueError("cannot update a medoid for an empty cluster")
        medoids.append(
            min(
                members,
                key=lambda candidate: (
                    sum(weights[member] * distances[candidate][member] for member in members),
                    candidate,
                ),
            )
        )
    return medoids
