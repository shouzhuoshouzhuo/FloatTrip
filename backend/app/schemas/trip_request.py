"""旅行规划请求数据结构。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Location(BaseModel):
    """地图坐标，经度在前、纬度在后。"""

    lng: float
    lat: float


class PoiInfo(BaseModel):
    """高德或其他地图供应商返回的地点基础信息。"""

    provider: str = "amap"
    id: str | None = None
    name: str | None = None
    type: str | None = None
    address: str | None = None
    location: Location


class AttractionCandidate(BaseModel):
    """进入规划流程的候选景点，必须已经带有可用地点坐标。"""

    name: str = Field(min_length=1)
    mention_count: int = Field(ge=1)
    score: float | None = None
    preference_score: int | None = None
    poi: PoiInfo


class TripClusterRouteRequest(BaseModel):
    """前端请求后端进行景点分天和路线占位生成的输入结构。"""

    destination: str = Field(min_length=1)
    days: int = Field(ge=1)
    candidates: list[AttractionCandidate] = Field(min_length=1)
    min_cluster_size: int = Field(default=2, ge=1)
    pace: str | None = None
    preferences: list[str] = Field(default_factory=list)
