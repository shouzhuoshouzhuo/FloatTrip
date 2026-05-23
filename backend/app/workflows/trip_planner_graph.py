"""第一版后端接口使用的路线计划编排骨架。"""

from __future__ import annotations

from typing import Any

from backend.app.planning.day_clustering import cluster_candidates_by_days
from backend.app.planning.transit_routes import build_daily_transit_route_plan
from backend.app.providers.amap import require_amap_key
from backend.app.schemas.route_plan import (
    DayRoutePlan,
    DaySummaryMetrics,
    SpotMapItem,
    TripRoutePlanResponse,
)
from backend.app.schemas.trip_request import TripClusterRouteRequest


def build_cluster_route_plan(request: TripClusterRouteRequest) -> TripRoutePlanResponse:
    """功能：把已补地点信息的候选景点按天聚类，生成前端可消费的占位路线结果。

    参数：
        request：包含目的地、天数和已补坐标候选景点的请求模型。
    返回值：
        返回 TripRoutePlanResponse，其中 route_segments 为空，供前端先预览点位。
    """
    candidate_dicts = [model_to_dict(candidate) for candidate in request.candidates]
    clusters = cluster_candidates_by_days(
        candidate_dicts,
        request.days,
        min_cluster_size=request.min_cluster_size,
    )
    days = [
        build_day_route_plan(day_index=index + 1, cluster=cluster)
        for index, cluster in enumerate(clusters)
    ]
    return TripRoutePlanResponse(
        destination=request.destination,
        days=days,
        warnings=[
            "route_segments 当前为占位数据，后续接入高德时间矩阵和路线优化后填充"
        ],
    )


def build_day_route_plan(day_index: int, cluster: dict[str, Any]) -> DayRoutePlan:
    """功能：把单个地理聚类转换成某一天的路线预览结构。

    参数：
        day_index：当前天数序号，从 1 开始。
        cluster：地理聚类结果字典，包含 cluster_id、radius_km 和 candidates。
    返回值：
        返回 DayRoutePlan，占位路线段为空。
    """
    candidates = list(cluster.get("candidates", []))
    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            -float(candidate.get("score") or candidate.get("mention_count") or 0),
            str(candidate.get("name", "")),
        ),
    )
    spots = [
        candidate_to_spot(candidate, order=index + 1)
        for index, candidate in enumerate(ordered_candidates)
    ]
    return DayRoutePlan(
        day_index=day_index,
        cluster_id=int(cluster.get("cluster_id", day_index - 1)),
        spots=spots,
        route_order=[spot.name for spot in spots],
        route_segments=[],
        summary_metrics=DaySummaryMetrics(
            spot_count=len(spots),
            cluster_radius_km=float(cluster.get("radius_km") or 0.0),
        ),
    )


def candidate_to_spot(candidate: dict[str, Any], order: int) -> SpotMapItem:
    """功能：把候选景点字典转换成前端地图点位。

    参数：
        candidate：单个已补坐标候选景点字典。
        order：当天展示顺序，从 1 开始。
    返回值：
        返回 SpotMapItem。
    """
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    location = poi.get("location") if isinstance(poi.get("location"), dict) else {}
    return SpotMapItem(
        spot_id=str(poi.get("id") or "") or None,
        name=str(candidate.get("name") or poi.get("name") or ""),
        order=order,
        location={
            "lng": float(location.get("lng")),
            "lat": float(location.get("lat")),
        },
        address=str(poi.get("address") or "") or None,
        poi_type=str(poi.get("type") or "") or None,
        raw_candidate=candidate,
    )


def build_transit_route_plan(request: TripClusterRouteRequest) -> TripRoutePlanResponse:
    """功能：根据候选景点生成带高德真实路径的每日公交/步行路线。

    参数：
        request：包含目的地、天数和已补坐标候选景点的请求模型。
    返回值：
        返回 TripRoutePlanResponse，其中 route_segments 包含真实 path，可直接给前端画线。
    """
    candidate_dicts = [model_to_dict(candidate) for candidate in request.candidates]
    return build_daily_transit_route_plan(
        candidate_dicts,
        request.destination,
        request.days,
        api_key=require_amap_key(),
        min_cluster_size=request.min_cluster_size,
    )


def model_to_dict(model: Any) -> dict[str, Any]:
    """功能：兼容不同版本的数据模型库，把模型转换成普通字典。

    参数：
        model：Pydantic v1 或 v2 模型实例。
    返回值：
        返回普通 dict。
    """
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
