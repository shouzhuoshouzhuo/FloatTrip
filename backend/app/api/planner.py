"""旅行规划相关接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.schemas.route_plan import TripRoutePlanResponse
from backend.app.schemas.trip_request import TripClusterRouteRequest, TripGenerateRouteRequest
from backend.app.workflows.research_route_planner import build_generated_route_plan
from backend.app.workflows.trip_planner_graph import (
    build_cluster_route_plan,
    build_transit_route_plan,
)


router = APIRouter(prefix="/api/planner", tags=["planner"])


@router.post("/cluster-routes", response_model=TripRoutePlanResponse)
def cluster_routes(request: TripClusterRouteRequest) -> TripRoutePlanResponse:
    """功能：根据已补坐标的候选景点生成按天聚类后的地图路线占位结果。

    参数：
        request：目的地、旅行天数和候选景点列表。
    返回值：
        返回只有点位和访问顺序的 TripRoutePlanResponse，route_segments 为空。
    """
    try:
        return build_cluster_route_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transit-routes", response_model=TripRoutePlanResponse)
def transit_routes(request: TripClusterRouteRequest) -> TripRoutePlanResponse:
    """功能：根据已补坐标的候选景点生成高德公交/步行真实路线规划。

    参数：
        request：目的地、旅行天数和候选景点列表，候选景点必须带 poi.location。
    返回值：
        返回可直接给前端消费的 TripRoutePlanResponse，包含每日 route_segments[].path。
    """
    try:
        return build_transit_route_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/generate", response_model=TripRoutePlanResponse)
def generate_routes(request: TripGenerateRouteRequest) -> TripRoutePlanResponse:
    """功能：从网页调研、候选景点抽取、POI 补坐标到真实路线一次完成。"""
    try:
        return build_generated_route_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
