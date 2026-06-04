"""LangGraph 图构建与流水线入口。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.planning.schemas import TravelPlanState
from app.planning.helpers import invoke_structured  # re-export for convenience
from app.planning.nodes import (
    attraction_search_node,
    finalize_node,
    make_intent_node,
    make_meal_recommend_node,
    make_planner_node,
    make_reviewer_node,
    meal_search_node,
    route_after_intent,
    route_after_review,
)


# ─── 构图 ────────────────────────────────────────────────────

def build_graph(model_name: str | None = None):
    g = StateGraph(TravelPlanState)

    g.add_node("intent",           make_intent_node(model_name))
    g.add_node("attraction_search", attraction_search_node)
    g.add_node("planner",          make_planner_node(model_name))
    g.add_node("reviewer",         make_reviewer_node(model_name))
    g.add_node("meal_search",      meal_search_node)
    g.add_node("meal_recommend",   make_meal_recommend_node(model_name))
    g.add_node("finalize",         finalize_node)

    g.add_edge(START, "intent")
    g.add_conditional_edges(
        "intent", route_after_intent,
        {"attraction_search": "attraction_search", END: END}
    )
    g.add_edge("attraction_search", "planner")
    g.add_edge("planner", "reviewer")
    g.add_conditional_edges(
        "reviewer", route_after_review,
        {"planner": "planner", "meal_search": "meal_search"}
    )
    g.add_edge("meal_search",    "meal_recommend")
    g.add_edge("meal_recommend", "finalize")
    g.add_edge("finalize",       END)

    return g.compile()


# ─── 流水线入口 ───────────────────────────────────────────────

def run(query: str, **overrides: Any) -> TravelPlanState:
    """执行完整规划流水线。

    Args:
        query: 用户一句话需求（必填）
        **overrides: max_per_day / min_rating / max_spots / max_review_rounds / model_name

    Returns:
        TravelPlanState — final_plan 已填充，或 missing_fields 非空表示需要用户补充信息
    """
    app = build_graph(overrides.get("model_name"))
    init = TravelPlanState(query=query, **overrides)
    config = {"recursion_limit": 2 * init.max_review_rounds + 10}
    result = app.invoke(init, config=config)
    return TravelPlanState(**result) if isinstance(result, dict) else result
