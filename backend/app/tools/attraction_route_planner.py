"""把候选景点转换成路线计划的工具边界。"""

from __future__ import annotations

from backend.app.schemas.route_plan import TripRoutePlanResponse
from backend.app.schemas.trip_request import TripClusterRouteRequest
from backend.app.workflows.trip_planner_graph import build_cluster_route_plan


def plan_attraction_routes(request: TripClusterRouteRequest) -> TripRoutePlanResponse:
    """供后续智能体或流程编排调用的景点路线规划工具入口。"""
    return build_cluster_route_plan(request)
