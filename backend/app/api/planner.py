"""旅行规划主链路接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.schemas.route_plan import TripRoutePlanResponse
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.workflows.research_route_planner import build_generated_route_plan


router = APIRouter(prefix="/api/planner", tags=["planner"])


@router.post("/generate", response_model=TripRoutePlanResponse)
def generate_routes(request: TripGenerateRouteRequest) -> TripRoutePlanResponse:
    """功能：从用户输入开始生成前端可展示的完整旅行规划结果。

    参数：
        request：目的地、天数、偏好、必去/避开景点和调研数量配置。
    返回值：
        返回包含调研摘要、每日景点、访问顺序、路线段和汇总指标的规划结果。
    """
    try:
        return build_generated_route_plan(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
