"""把已补高德坐标的候选景点按地理位置聚成每日区域。"""

from __future__ import annotations

import math
from typing import Any


EARTH_RADIUS_KM = 6371.0088
MAX_CLUSTER_INPUT_CANDIDATES_PER_DAY = 3


def cluster_candidates_by_days(
    candidates: list[dict[str, Any]],
    days: int,
    *,
    min_cluster_size: int = 2,
    max_iterations: int = 50,
) -> list[dict[str, Any]]:
    """功能：把候选景点聚成指定天数的地理区域，为每日路线规划做准备。

    参数：
        candidates：已补齐 poi.location 的候选景点字典列表。
        days：旅行天数，也是需要生成的地理簇数量。
        min_cluster_size：每个地理簇至少包含的候选景点数量。
        max_iterations：K-Medoids 风格迭代的最大轮数。
    返回值：
        返回按天组织的聚类结果，每项包含 cluster_id、medoid、radius_km 和 candidates。
    """
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
    """功能：校验候选景点，并按用户必去优先级与分数截取参与聚类的优先窗口。

    参数：
        candidates：原始候选景点字典列表。
        days：旅行天数。
        min_cluster_size：每个地理簇至少需要的候选景点数量。
    返回值：
        返回通过坐标校验且按“必去优先、分数优先”截取后的前 3 * days 个候选景点。
    """
    validate_cluster_inputs(candidates, days, min_cluster_size)
    for candidate in candidates:
        candidate_location(candidate)
        candidate_mention_count(candidate)

    minimum_candidates = days * min_cluster_size
    if len(candidates) < minimum_candidates:
        raise ValueError(
            f"need at least {minimum_candidates} candidates for {days} day cluster(s)"
        )

    limit = days * MAX_CLUSTER_INPUT_CANDIDATES_PER_DAY
    ranked = sorted(
        enumerate(candidates),
        key=lambda indexed: (
            -candidate_user_requested_priority(indexed[1]),
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
    """功能：校验聚类输入的天数、最小簇大小和候选列表形态。

    参数：
        candidates：原始候选景点字典列表。
        days：旅行天数。
        min_cluster_size：每个地理簇至少需要的候选景点数量。
    返回值：
        无返回值；输入非法时抛出 ValueError。
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    if min_cluster_size < 1:
        raise ValueError("min_cluster_size must be at least 1")
    if min_cluster_size > MAX_CLUSTER_INPUT_CANDIDATES_PER_DAY:
        raise ValueError(
            f"min_cluster_size cannot exceed {MAX_CLUSTER_INPUT_CANDIDATES_PER_DAY} in v1"
        )
    if not candidates:
        raise ValueError("candidates must not be empty")
    if not all(isinstance(candidate, dict) for candidate in candidates):
        raise ValueError("every candidate must be a dict")


def candidate_location(candidate: dict[str, Any]) -> tuple[float, float]:
    """功能：从候选景点中读取经纬度，返回高德常用的经度、纬度顺序。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回 (lng, lat) 坐标元组。
    """
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
    """功能：把坐标字段转换成有限浮点数，并在异常时带上候选景点名称。

    参数：
        value：待转换的坐标字段值。
        field：字段名，用于错误信息。
        candidate：当前候选景点字典，用于错误信息。
    返回值：
        返回转换后的有限浮点数。
    """
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
    """功能：生成用于错误信息的候选景点标签。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回可读的候选景点名称标签。
    """
    return repr(str(candidate.get("name") or "<unnamed>"))


def candidate_mention_count(candidate: dict[str, Any]) -> int:
    """功能：读取并校验候选景点在攻略语料中的出现次数。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回合法的正整数出现次数。
    """
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
    """功能：读取候选景点评分；没有评分时回退到出现次数。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回用于排序的浮点评分。
    """
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


def candidate_user_requested_priority(candidate: dict[str, Any]) -> int:
    """功能：判断候选景点是否来自用户指定必去清单，用于聚类输入截取置顶。

    参数：
        candidate：单个候选景点字典。
    返回值：
        用户指定必去景点返回 1，否则返回 0。
    """
    return 1 if candidate.get("user_requested") is True else 0


def mention_weight(candidate: dict[str, Any]) -> float:
    """功能：把出现次数转换成聚类权重，避免高频景点被低估。

    参数：
        candidate：单个候选景点字典。
    返回值：
        返回用于聚类中心选择的权重。
    """
    return 1.0 + math.log(max(1, candidate_mention_count(candidate)))


def haversine_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    """功能：用球面距离公式计算两个经纬度点之间的公里距离。

    参数：
        left：第一个坐标点，格式为 (lng, lat)。
        right：第二个坐标点，格式为 (lng, lat)。
    返回值：
        返回两点之间的球面距离，单位为公里。
    """
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
    """功能：根据所有候选点坐标生成两两地理距离矩阵。

    参数：
        locations：候选景点坐标列表，每项格式为 (lng, lat)。
    返回值：
        返回对称距离矩阵，矩阵值单位为公里。
    """
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
    """功能：用加权最远点策略初始化每日聚类中心。

    参数：
        distances：候选点之间的距离矩阵。
        weights：每个候选点的提及频率权重。
        cluster_count：需要初始化的聚类中心数量。
    返回值：
        返回聚类中心在候选列表中的索引列表。
    """
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
    """功能：把每个候选点分配给最近的聚类中心。

    参数：
        distances：候选点之间的距离矩阵。
        medoids：当前聚类中心索引列表。
    返回值：
        返回按聚类中心分组的候选点索引列表。
    """
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
    """功能：当某个簇小于最小景点数时，从其他簇迁移代价最低的点。

    参数：
        clusters：按簇保存的候选点索引列表，会被原地调整。
        medoids：当前聚类中心索引列表。
        distances：候选点之间的距离矩阵。
        min_cluster_size：每个簇至少需要的候选点数量。
    返回值：
        无返回值；无法修复时抛出 ValueError。
    """
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
    """功能：在每个簇内部重新选择加权距离总和最小的真实候选点作为中心。

    参数：
        clusters：按簇保存的候选点索引列表。
        distances：候选点之间的距离矩阵。
        weights：每个候选点的提及频率权重。
    返回值：
        返回新的聚类中心索引列表。
    """
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
