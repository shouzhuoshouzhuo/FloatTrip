"""旅行规划相关接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.schemas.route_plan import TripRoutePlanResponse
from backend.app.schemas.trip_request import TripClusterRouteRequest
from backend.app.workflows.trip_planner_graph import build_cluster_route_plan


router = APIRouter(prefix="/api/planner", tags=["planner"])


@router.post("/cluster-routes", response_model=TripRoutePlanResponse)
def cluster_routes(request: TripClusterRouteRequest) -> TripRoutePlanResponse:
    """根据已补坐标的候选景点生成按天聚类后的地图路线占位结果。"""
    try:
        return build_cluster_route_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
