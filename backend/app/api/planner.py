"""旅行规划主链路接口路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.schemas.route_plan import ItineraryDetailsRequest, TripRoutePlanResponse
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.services.itinerary_details import build_itinerary_details
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


@router.post("/itinerary-details", response_model=TripRoutePlanResponse)
def generate_itinerary_details(request: ItineraryDetailsRequest) -> TripRoutePlanResponse:
    """功能：基于已有路线结果补齐行程详情页需要的日程、天气、餐厅和注意事项。

    参数：
        request：包含原始用户需求、已有路线结果、交通方式、偏好和开始日期的请求。
    返回值：
        返回补齐 days[].itinerary_detail 的完整路线结果。
    """
    original_request = request.original_request.model_copy(
        update={
            "start_date": request.start_date or request.original_request.start_date,
            "preferences": request.preferences or request.original_request.preferences,
        }
    )
    return build_itinerary_details(
        request.route_plan,
        original_request,
        transport_mode=request.transport_mode,
        preferences=request.preferences or original_request.preferences,
    )
