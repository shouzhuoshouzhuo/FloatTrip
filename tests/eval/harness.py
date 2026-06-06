"""评估 harness：从 fixture 构造状态，跑隔离的 planner⇄reviewer 循环。

设计要点：
- 冻结 planner 的输入（destination/dates/preferences/pois/weather）成 fixture，
  跳过 intent 与 attraction_search，使 planner/reviewer 的评估可复现、零外部成本。
- planner/reviewer 的 LLM 调用真实执行——它们才是被评估对象。
- mini-graph 完整复用生产的 make_planner_node / make_reviewer_node / route_after_review，
  收敛逻辑（approved 或达 max_review_rounds 即停）与线上一致。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.planning.nodes import (
    make_planner_node,
    make_reviewer_node,
    route_after_planner,
    route_after_review,
)
from app.planning.schemas import TravelPlanState

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ─── Fixture 加载 ─────────────────────────────────────────────

def load_fixtures(only: str | None = None) -> list[dict[str, Any]]:
    """加载 fixtures/ 下所有用例（按 id 排序）；only 给定时只取该 id。"""
    cases: list[dict[str, Any]] = []
    for fp in sorted(FIXTURES_DIR.glob("*.json")):
        fx = json.loads(fp.read_text(encoding="utf-8"))
        fx.setdefault("id", fp.stem)
        if only and fx["id"] != only:
            continue
        cases.append(fx)
    return cases


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def build_state_from_fixture(fx: dict[str, Any]) -> TravelPlanState:
    """用 fixture 字段直接构造 TravelPlanState（已 seed planner 所需全部输入）。

    pois 里允许携带额外的 `indoor` 真值标签——透传进 state，
    供代码打分器做天气合规判定；planner/reviewer 不读它。
    """
    return TravelPlanState(
        query=fx.get("query") or f"{fx.get('destination', '')}{fx.get('days', '')}日游",
        destination=fx.get("destination"),
        travel_start_date=_parse_date(fx.get("travel_start_date")),
        travel_end_date=_parse_date(fx.get("travel_end_date")),
        days=int(fx.get("days", 0)),
        attraction_preference=fx.get("attraction_preference"),
        food_preference=fx.get("food_preference"),
        habit_preference=fx.get("habit_preference"),
        max_per_day=int(fx.get("max_per_day", 3)),
        min_rating=float(fx.get("min_rating", 4.5)),
        max_spots=int(fx.get("max_spots", 30)),
        max_review_rounds=int(fx.get("max_review_rounds", 3)),
        model_name=fx.get("model_name"),
        pois=list(fx.get("pois", [])),
        weather_forecast=list(fx.get("weather_forecast", [])),
        weather_note=fx.get("weather_note"),
    )


# ─── mini-graph ──────────────────────────────────────────────

def build_planner_reviewer_graph(model_name: str | None = None):
    """只含 planner + reviewer 的子图，完整复用生产节点与收敛路由。

    闭环设计（与 graph.py 保持一致）：
    - route_after_planner：planner 递增 review_round 后判定是否超轮数
    - route_after_review：reviewer 通过则终止，否则还给 planner
    """
    g = StateGraph(TravelPlanState)
    g.add_node("planner", make_planner_node(model_name))
    g.add_node("reviewer", make_reviewer_node(model_name))
    g.add_edge(START, "planner")
    g.add_conditional_edges(
        "planner", route_after_planner,
        {"reviewer": "reviewer", "meal_search": END},
    )
    g.add_conditional_edges(
        "reviewer", route_after_review,
        {"planner": "planner", "meal_search": END},
    )
    return g.compile()


def run_planner_reviewer_loop(fx: dict[str, Any]) -> TravelPlanState:
    """跑一次 planner⇄reviewer 循环，返回最终 state。

    最终 state 含评估所需全部信号：route / approved / review_round /
    reviewer_issues / route_modify_opinion / planner_reviewer_dialogue。
    """
    state = build_state_from_fixture(fx)
    app = build_planner_reviewer_graph(state.model_name)
    # 与生产一致：(max+1) 轮 planner + max 轮 reviewer，留余量
    config = {"recursion_limit": 2 * (state.max_review_rounds + 1) + 10}
    result = app.invoke(state, config=config)
    return TravelPlanState(**result) if isinstance(result, dict) else result
