"""预留给用户可读行程文案的响应数据结构。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MealSuggestion(BaseModel):
    """午餐、晚餐等用餐建议的占位结构。"""

    meal_slot: str
    anchor_spot_name: str | None = None
    candidates: list[dict] = Field(default_factory=list)


class DayItineraryNarrative(BaseModel):
    """某一天面向用户展示的自然语言行程说明。"""

    day_index: int
    title: str = ""
    summary: str = ""
    meal_suggestions: list[MealSuggestion] = Field(default_factory=list)
