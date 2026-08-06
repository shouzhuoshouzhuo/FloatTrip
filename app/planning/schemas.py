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
    period: str = Field(description="时段：morning / afternoon / evening")
    start_time: str = Field(description="开始游玩时间，格式 HH:MM")
    end_time: str = Field(description="结束游玩时间，格式 HH:MM")


class DayRoute(BaseModel):
    """单天的路线。"""

    day: int = Field(description="第几天，从 1 开始")
    spots: list[SpotPlan] = Field(description="当天景点（按时间先后排列）")
    theme: str = Field(description="当天主题，一句话，根据已确定的景点内容归纳")


class TravelRoute(BaseModel):
    """Planner 产出的逐天路线（含时刻表）。

    字段顺序即生成顺序：先 reasoning（CoT 逐维度推理），后 days（落实结论），最后 notes（总结）。
    """

    reasoning: str = Field(
        description=(
            "按【景点相邻】【用户偏好】【无重复】【天气适配】四个维度逐一推理，"
            "每个维度写出本轮决策或改动结论。"
        )
    )
    days: list[DayRoute] = Field(
        description="逐天路线，严格落实 reasoning 中的结论——说换就必须换，说保留就保留"
    )
    notes: str = Field(default="", description="本版总结，一句话说明本轮主要改动，供历史日志展示")
    modification_concern: str = Field(
        default="",
        description="如果用户修改意见会导致路线质量严重下降（如同天景点地理跨度剧增、"
                    "明显时间冲突等），在此写出1-2句顾虑；无担忧则空字符串",
    )


class RouteReview(BaseModel):
    """Reviewer 对路线的评审结论。

    字段顺序即生成顺序：先 reasoning（CoT 逐维分析），后结论字段。
    issues 与 route_modify_opinion 面向不同读者，不要混淆：
    - route_modify_opinion：给 planner 看的修改指令（诊断语气，可技术化）
    - issues：给用户看的友好出行提醒（温和、可执行；告诉用户旅行时要注意什么）
    """

    reasoning: str = Field(
        description=(
            "逐维度评审的完整推理过程：对地点相近/大众常去/真实性/贴合习惯/"
            "夜间合理性/天气合理性/折返路线逐一分析，写出各维度结论（合格/不合格+原因）。"
            "issues 和 route_modify_opinion 仅从此推理的结论中提炼，不得凭空添加。"
        )
    )
    approved: bool = Field(description="路线是否达标")
    score: int = Field(description="综合评分 0-100")
    route_modify_opinion: str = Field(
        default="",
        description="给 planner 看的修改指令，诊断语气，可技术化；approved=true 时可空",
    )
    issues: list[str] = Field(
        default_factory=list,
        description=(
            "给用户看的友好出行提醒列表（不是诊断！）。"
            "将 route_modify_opinion 中的问题转化为温和、可执行的用户语言，"
            "告诉用户实际出行时要注意什么，"
            "例：『Day2 行程较紧凑，建议提前预约餐厅』、"
            "『Day3 雷阵雨天气，记得带伞并优先安排室内景点』。"
            "禁止使用『违规』『冲突』『不合理』『地理跨度过大』这类批判性/技术性词汇。"
            "approved=true 且无需提醒时返回空列表。"
        ),
    )


class TimeViolation(BaseModel):
    """单个景点的开放时间违规事实，仅供 planner 看（用于定位并修正路线）。"""

    day: int = Field(description="第几天，从 1 开始")
    spot_name: str = Field(description="景点名")
    detail: str = Field(description="一句话描述违规事实，planner 仅凭这一条即可定位并修正")


class TimeCheckResult(BaseModel):
    """time_check Agent 的输出。

    字段顺序即生成顺序：先 reasoning（CoT 探索），后 violations（仅确认违规）。
    Pydantic 字段顺序对结构化输出有强引导——模型先生成 reasoning 把每个景点逐项核查，
    再从结论中筛选违规写入 violations，避免"边推理边打违规标签"的矛盾。
    """

    reasoning: str = Field(
        description=(
            "逐景点核查的完整推理过程：『安排时段 vs 开放原文 → 核查 → 结论合法/违规』。"
            "推理必须覆盖所有景点，包括最终判定为合法的项。"
            "violations 字段只写从此推理中确认违规的项。"
        )
    )
    violations: list[TimeViolation] = Field(
        default_factory=list,
        description="确认违规的列表，detail 写一句话事实陈述；reasoning 中判定合法的项不得写入。",
    )


class SingleDayMealPick(BaseModel):
    """单天午/晚餐选择（LLM 输出，不含 day 字段，由调用方注入）。"""

    lunch_name: str = Field(description="午餐餐厅名，严格复制候选列表写法；无合适则空字符串")
    lunch_reason: str = Field(default="", description="午餐推荐/降级理由，1-2句；若无符合偏好的餐厅，在此说明降级原因")
    dinner_name: str = Field(description="晚餐餐厅名，严格复制候选列表写法；无合适则空字符串")
    dinner_reason: str = Field(default="", description="晚餐推荐/降级理由，1-2句；若无符合偏好的餐厅，在此说明降级原因")


class DayMealPick(BaseModel):
    """单天午/晚餐选择（含 day，流水线内部流转用）。"""

    day: int = Field(description="第几天")
    lunch_name: str = Field(default="", description="午餐餐厅名")
    lunch_reason: str = Field(default="", description="午餐推荐/降级理由")
    dinner_name: str = Field(default="", description="晚餐餐厅名")
    dinner_reason: str = Field(default="", description="晚餐推荐/降级理由")


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
    trip_budget: Optional[str] = None
    effective_constraints: list[dict[str, Any]] = Field(default_factory=list)
    constraint_coverage: list[dict[str, Any]] = Field(default_factory=list)
    days: int = 0
    missing_fields: list[str] = Field(default_factory=list)

    # 配置
    max_per_day: int = 5
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
    # 上一轮 Planner 未作任何修改时写入的强警告，下一轮注入 feedback 最前面
    route_stale_warning: str = ""

    # 天气（意图识别后拉取）
    weather_forecast: list[dict[str, Any]] = Field(default_factory=list)
    weather_note: Optional[str] = None      # 超出预报范围/接口失败时的降级说明

    # 餐饮（一次成型）
    meal_candidates: list[dict[str, Any]] = Field(default_factory=list)
    meals: list[dict[str, Any]] = Field(default_factory=list)

    # 景点游玩贴士（spot_tips 节点填充：景点名 → 贴士文本）
    spot_tips: dict[str, str] = Field(default_factory=dict)

    # Reviewer 最后一轮发现的问题（最大轮数未通过时透传给前端）
    reviewer_issues: list[str] = Field(default_factory=list)

    # 时间核查（time_check 节点：planner-reviewer 主循环后插入的二次修正循环）
    time_violations: list[dict[str, Any]] = Field(default_factory=list)
    time_check_round: int = 0
    max_time_check_rounds: int = 3
    time_check_done: bool = False  # 单向门：进入时间修正阶段后置 True，planner 据此决定下一跳

    # Query Rewrite Agent 改写后的查询（由 query_rewrite 节点填充）
    rewritten_query: Optional[str] = None

    # 用户记忆注入（由 API 层填充）
    profile_hint: Optional[str] = None

    # 修改规划相关（由 API 层填充）
    modification_notes: Optional[str] = None
    parent_plan_id: Optional[str] = None
    previous_plan_summary: Optional[str] = None

    # Planner 对修改意见的顾虑（Human-in-the-Loop）
    modification_concern: Optional[str] = None

    # 最终输出
    final_plan: Optional[dict[str, Any]] = None


# ─── Spot Tips Agent Schema ───────────────────────────────────

class SpotTipItem(BaseModel):
    """单个景点的游玩贴士。"""

    name: str = Field(description="景点名，必须与输入行程中的景点名完全一致（逐字复制，不要改写）")
    tip: str = Field(
        description=(
            "该景点的游玩注意事项，30~70字，必须具体可执行："
            "结合当天天气给穿戴/装备建议（雨天带伞穿防滑鞋、高温防晒补水），"
            "结合景点属性给准备建议（爬山穿运动鞋带水和干粮、寺庙注意着装、夜景注意保暖），"
            "以及该景点独有的游玩常识（如大熊猫清晨活跃建议早去、热门馆需提前预约）。"
            "禁止『祝您玩得开心』之类的空话套话。"
        )
    )


class SpotTipsResult(BaseModel):
    """Spot Tips Agent 的输出。

    字段顺序即生成顺序：先 reasoning 逐景点结合天气与属性分析，再输出 tips 结论。
    """

    reasoning: str = Field(
        description=(
            "逐景点的简要分析：当天天气如何、景点是室内还是户外/是否爬山/有无特殊游玩常识，"
            "据此决定要提醒什么。每个景点 1-2 句即可。"
        )
    )
    tips: list[SpotTipItem] = Field(
        default_factory=list,
        description="每个景点一条贴士，覆盖输入行程中的全部景点，名称逐字一致",
    )


# ─── Query Rewrite Agent Schema ───────────────────────────────

class RewrittenQuery(BaseModel):
    """Query Rewrite Agent 的结构化输出。"""
    reasoning: str = Field(default="", description="冲突解析的推理过程：逐条比对本次查询偏好与画像偏好，写出各项合并或覆盖结论；改写理由；仅用于日志")
    attraction_preference: str | None = Field(
        default=None,
        description="景点偏好摘要（冲突解析后）。将本次查询明确偏好与画像偏好合并，若有矛盾以本次查询为准；无偏好则为 null",
    )
    food_preference: str | None = Field(
        default=None,
        description="餐饮偏好摘要（冲突解析后）。同上规则；无偏好则为 null",
    )
    habit_preference: str | None = Field(
        default=None,
        description="游玩习惯/节奏摘要（冲突解析后）。同上规则；无偏好则为 null",
    )
    rewritten_query: str = Field(description="融入以上冲突解析后偏好改写的旅行查询；若无相关画像则原样返回")


# ─── Profile Update Agent Schema ──────────────────────────────

class ProfileUpdateResult(BaseModel):
    """Profile Update Agent 的冲突解析输出（不含 visited_destinations，由代码维护）。

    CoT 顺序：change_log 必须排在三个列表之前——先写明计划的每条变更，
    再输出落实了这些变更的完整列表。曾出现 change_log 声称新增但列表没加的"只说不做"问题。
    """
    change_log: list[str] = Field(default_factory=list, description="每条变更说明（先写这里，下面的列表必须落实这些变更）")
    attraction_prefs: list[str] = Field(default_factory=list, description="景点偏好完整列表（含 change_log 中的变更），最多 20 条")
    food_prefs: list[str] = Field(default_factory=list, description="餐饮偏好完整列表（含 change_log 中的变更），最多 20 条")
    habit_prefs: list[str] = Field(default_factory=list, description="游玩习惯/节奏完整列表（含 change_log 中的变更），最多 20 条")
