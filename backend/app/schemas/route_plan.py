"""面向地图预览的路线计划响应数据结构。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.trip_request import Location


class SpotMapItem(BaseModel):
    """前端地图和路线顺序列表使用的单个景点点位。"""

    spot_id: str | None = None
    name: str
    order: int = Field(ge=1)
    location: Location
    address: str | None = None
    poi_type: str | None = None
    image_url: str | None = None
    brief_intro: str | None = None
    raw_candidate: dict[str, Any] = Field(default_factory=dict)


class RouteSegment(BaseModel):
    """两个景点之间的路线段；本轮重构先保留空结构，后续接高德路线。"""

    from_spot_id: str | None = None
    to_spot_id: str | None = None
    mode: str | None = None
    distance_meters: int | None = None
    duration_seconds: int | None = None
    path: list[Location] = Field(default_factory=list)


class DaySummaryMetrics(BaseModel):
    """每日路线预览的汇总指标。"""

    spot_count: int
    cluster_radius_km: float
    route_status: Literal["route_pending"] = "route_pending"


class DayRoutePlan(BaseModel):
    """某一天的地图点位、访问顺序和路线段。"""

    day_index: int = Field(ge=1)
    cluster_id: int = Field(ge=0)
    spots: list[SpotMapItem]
    route_order: list[str]
    route_segments: list[RouteSegment] = Field(default_factory=list)
    summary_metrics: DaySummaryMetrics


class TripRoutePlanResponse(BaseModel):
    """一次旅行的按天路线计划响应。"""

    destination: str
    days: list[DayRoutePlan]
    warnings: list[str] = Field(default_factory=list)
