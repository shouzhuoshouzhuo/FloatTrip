"""面向地图预览和行程详情页的路线计划响应数据结构。"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.trip_request import Location, TripGenerateRouteRequest


class SpotMapItem(BaseModel):
    """前端地图和路线顺序列表使用的单个景点点位。"""

    spot_id: str | None = None
    name: str
    order: int = Field(ge=1)
    location: Location
    address: str | None = None
    poi_type: str | None = None
    image_url: str | None = None
    image_thumb_url: str | None = None
    image_description: str | None = None
    image_photographer: str | None = None
    brief_intro: str | None = None
    raw_candidate: dict[str, Any] = Field(default_factory=dict)


class RouteSegment(BaseModel):
    """两个景点之间的真实路线段。"""

    from_spot_id: str | None = None
    from_name: str | None = None
    to_spot_id: str | None = None
    to_name: str | None = None
    mode: Literal["transit", "walking", "unknown"] | None = None
    distance_meters: int | None = None
    duration_seconds: int | None = None
    duration_minutes: float | None = None
    walking_distance_meters: int | None = None
    cost: str | None = None
    summary: str | None = None
    amap_transit: dict[str, Any] | None = None
    fallback_mode: str | None = None
    path: list[Location] = Field(default_factory=list)


class DayWeather(BaseModel):
    """行程详情页展示的当日天气和穿衣建议。"""

    date: date_type | None = None
    city: str | None = None
    status: Literal["ok", "unavailable", "missing_start_date"] = "unavailable"
    weather: str | None = None
    temperature: str | None = None
    wind: str | None = None
    dressing_advice: str | None = None


class MealRecommendation(BaseModel):
    """行程详情页展示的午餐或晚餐推荐。"""

    meal_type: Literal["lunch", "dinner"]
    restaurant_name: str
    address: str | None = None
    location: Location | None = None
    distance_meters: int | None = None
    reason: str
    source_poi: dict[str, Any] = Field(default_factory=dict)


class ItineraryActivity(BaseModel):
    """行程详情页时间线中的单个活动。"""

    type: Literal["spot", "meal", "transit", "buffer"]
    start_time: str
    end_time: str
    title: str
    description: str
    location: Location | None = None
    related_spot_id: str | None = None
    travel_summary: str | None = None
    tag: str | None = None


class DayNotice(BaseModel):
    """行程详情页展示的天气、路线或高峰提醒。"""

    level: Literal["info", "warning"] = "info"
    title: str
    content: str
    basis: Literal["weather", "crowd", "route", "meal", "general"] = "general"


class DayItineraryDetail(BaseModel):
    """某一天的可展示日程详情。"""

    original_route: list[str] = Field(default_factory=list)
    day_theme: str | None = None
    hero_image_url: str | None = None
    hero_image_thumb_url: str | None = None
    hero_image_description: str | None = None
    hero_image_photographer: str | None = None
    hero_image_source: Literal["theme", "spot"] | None = None
    weather: DayWeather = Field(default_factory=DayWeather)
    activities: list[ItineraryActivity] = Field(default_factory=list)
    meals: list[MealRecommendation] = Field(default_factory=list)
    notices: list[DayNotice] = Field(default_factory=list)


class DaySummaryMetrics(BaseModel):
    """每日路线预览的汇总指标。"""

    spot_count: int
    cluster_radius_km: float
    route_status: Literal["route_planned", "route_partial"] = "route_planned"
    total_duration_seconds: int | None = None
    total_duration_minutes: float | None = None
    failed_segment_count: int = 0


class DayRoutePlan(BaseModel):
    """某一天的地图点位、访问顺序和路线段。"""

    day_index: int = Field(ge=1)
    cluster_id: int = Field(ge=0)
    spots: list[SpotMapItem]
    route_order: list[str]
    route_segments: list[RouteSegment] = Field(default_factory=list)
    summary_metrics: DaySummaryMetrics
    duration_matrix_seconds: list[list[int | None]] | None = None
    optimized_order: list[str] = Field(default_factory=list)
    itinerary_detail: DayItineraryDetail | None = None


class TripRoutePlanResponse(BaseModel):
    """一次旅行的按天路线计划响应。"""

    schema_version: str = "floattrip_daily_transit_routes.v1"
    destination: str
    days_count: int | None = None
    route_mode: Literal["amap_transit"] = "amap_transit"
    strategy: int | None = None
    days: list[DayRoutePlan]
    warnings: list[str] = Field(default_factory=list)
    research_summary: dict[str, Any] | None = None
    candidate_count: int | None = None


class ItineraryDetailsRequest(BaseModel):
    """基于已有路线补全行程详情的请求结构。"""

    original_request: TripGenerateRouteRequest
    route_plan: TripRoutePlanResponse
    transport_mode: str | None = "amap_transit"
    preferences: list[str] = Field(default_factory=list)
    start_date: date_type | None = None
