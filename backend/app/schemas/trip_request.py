"""旅行规划请求数据结构。"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


SPOT_LIST_SEPARATOR = re.compile(r"[、,，;；\n\r\t]+")


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


class TripGenerateRouteRequest(BaseModel):
    """前端请求后端从网页调研开始生成完整路线的输入结构。"""

    destination: str = Field(min_length=1)
    days: int = Field(ge=1, le=7)
    pace: str | None = None
    preferences: list[str] = Field(default_factory=list)
    preferred_spots: list[str] = Field(default_factory=list)
    avoided_spots: list[str] = Field(default_factory=list)
    notes: str | None = None
    min_cluster_size: int = Field(default=2, ge=1)
    max_search_results: int = Field(default=8, ge=1, le=20)
    max_candidates: int = Field(default=28, ge=4, le=60)

    @field_validator("preferred_spots", "avoided_spots", mode="before")
    @classmethod
    def normalize_spot_list(cls, value: object) -> list[str]:
        """功能：把前端输入的景点清单拆分成单个景点名称。

        参数：
            value：前端提交的景点清单，可以是字符串或字符串数组。
        返回值：
            返回去空格、去重后的景点名称数组。
        """
        if value is None:
            return []
        raw_items = value if isinstance(value, list) else [value]
        normalized_spots: list[str] = []
        seen_spots: set[str] = set()
        for raw_item in raw_items:
            for spot in SPOT_LIST_SEPARATOR.split(str(raw_item)):
                name = spot.strip()
                if not name or name in seen_spots:
                    continue
                normalized_spots.append(name)
                seen_spots.add(name)
        return normalized_spots
