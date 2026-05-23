"""第一版后端接口使用的路线计划编排骨架。"""

from __future__ import annotations

from typing import Any

from backend.app.planning.day_clustering import cluster_candidates_by_days
from backend.app.schemas.route_plan import (
    DayRoutePlan,
    DaySummaryMetrics,
    SpotMapItem,
    TripRoutePlanResponse,
)
from backend.app.schemas.trip_request import TripClusterRouteRequest


def build_cluster_route_plan(request: TripClusterRouteRequest) -> TripRoutePlanResponse:
    """把已补地点信息的候选景点按天聚类，并整理成前端可直接消费的地图占位结果。"""
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
    """把单个地理聚类转换成某一天的路线预览结构。"""
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
    """把候选景点字典转换成前端地图点位。"""
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


def model_to_dict(model) -> dict[str, Any]:
    """兼容不同版本的数据模型库，把模型转换成普通字典。"""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
