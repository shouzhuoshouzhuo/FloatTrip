"""所有 Pydantic 数据模型：LLM 结构化输出 Schema + LangGraph 状态。"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── LLM 结构化输出 Schema ────────────────────────────────────

class IntentExtraction(BaseModel):
    """意图识别 Agent 的抽取结果。"""

    destination: str = Field(default="", description="旅游目的地城市名，如『南京』；没有则空字符串")
    travel_start_date: str = Field(default="", description="开始日期，格式 YYYY-MM-DD；没有则空")
    travel_end_date: str = Field(default="", description="结束日期，格式 YYYY-MM-DD；没有则空")
    travel_days: int = Field(default=0, description="旅游天数，如『3日游』→3、『五天四夜』→5；没有则0")
    attraction_preference: str = Field(default="", description="景点偏好，如『历史古迹/自然风光』；没有则空")
    food_preference: str = Field(default="", description="用餐偏好，如『本地小吃/清淡』；没有则空")
    habit_preference: str = Field(
        default="", description="游玩习惯/节奏，如『早出晚归/慢节奏/每天景点别太多/睡到自然醒』；没有则空"
    )


class SpotPlan(BaseModel):
    """单个景点的安排（含游玩时段）。"""

    name: str = Field(description="景点名，必须严格来自候选景点池")
    start_time: str = Field(description="开始游玩时间，格式 HH:MM")
    end_time: str = Field(description="结束游玩时间，格式 HH:MM")
    period: str = Field(description="时段：morning / afternoon / evening")


class DayRoute(BaseModel):
    """单天的路线。"""

    day: int = Field(description="第几天，从 1 开始")
    theme: str = Field(description="当天主题，一句话")
    spots: list[SpotPlan] = Field(description="当天景点（按时间先后排列）")


class TravelRoute(BaseModel):
    """Planner 产出的逐天路线（含时刻表）。"""

    days: list[DayRoute] = Field(description="逐天路线")
    notes: str = Field(default="", description="本版说明 / 相比上一版的改动")


class RouteReview(BaseModel):
    """Reviewer 对路线的评审结论。"""

    approved: bool = Field(description="路线是否达标")
    score: int = Field(description="综合评分 0-100")
    issues: list[str] = Field(default_factory=list, description="发现的问题列表")
    route_modify_opinion: str = Field(default="", description="给 Planner 的修改意见；approved=true 时可空")


class DayMealPick(BaseModel):
    """单天的午/晚餐选择（餐厅名必须来自候选餐厅列表）。"""

    day: int = Field(description="第几天")
    lunch_name: str = Field(description="午餐餐厅名，来自该天候选餐厅；无合适则空字符串")
    lunch_reason: str = Field(default="", description="午餐推荐理由")
    lunch_fallback_reason: str = Field(default="", description="午餐降级理由；满足偏好时返回空字符串")
    dinner_name: str = Field(description="晚餐餐厅名，来自该天候选餐厅；无合适则空字符串")
    dinner_reason: str = Field(default="", description="晚餐推荐理由")
    dinner_fallback_reason: str = Field(default="", description="晚餐降级理由；满足偏好时返回空字符串")


class MealRecommendation(BaseModel):
    """餐厅推荐 Agent 的逐天选择。"""

    picks: list[DayMealPick] = Field(description="逐天午/晚餐选择")


# ─── LangGraph 状态 ───────────────────────────────────────────

class TravelPlanState(BaseModel):
    # 输入（仅 query 必填）
    query: str

    # 意图识别抽取
    destination: Optional[str] = None
    travel_start_date: Optional[date] = None
    travel_end_date: Optional[date] = None
    attraction_preference: Optional[str] = None
    food_preference: Optional[str] = None
    habit_preference: Optional[str] = None
    days: int = 0
    missing_fields: list[str] = Field(default_factory=list)

    # 配置
    max_per_day: int = 3
    min_rating: float = 4.5
    max_spots: int = 30
    max_review_rounds: int = 3
    model_name: Optional[str] = None

    # 高德景点搜索
    pois: list[dict[str, Any]] = Field(default_factory=list)

    # Planner / Reviewer 循环
    route: list[dict[str, Any]] = Field(default_factory=list)
    need_modify_route: bool = False
    route_modify_opinion: Optional[str] = None
    review_round: int = 0
    approved: bool = False
    history: list[str] = Field(default_factory=list)
    # Planner 与 Reviewer 的共享对话记忆（每轮追加，两者均可读）
    planner_reviewer_dialogue: list[str] = Field(default_factory=list)

    # 天气（意图识别后拉取）
    weather_forecast: list[dict[str, Any]] = Field(default_factory=list)
    weather_note: Optional[str] = None      # 超出预报范围/接口失败时的降级说明

    # 餐饮（一次成型）
    meal_candidates: list[dict[str, Any]] = Field(default_factory=list)
    meals: list[dict[str, Any]] = Field(default_factory=list)

    # Reviewer 最后一轮发现的问题（最大轮数未通过时透传给前端）
    reviewer_issues: list[str] = Field(default_factory=list)

    # 最终输出
    final_plan: Optional[dict[str, Any]] = None
