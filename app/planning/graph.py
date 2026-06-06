"""LangGraph 图构建与流水线入口。"""

from __future__ import annotations

from typing import Any, AsyncIterator

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
    route_after_planner,
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
    # planner 递增 review_round 后决定：是继续送 reviewer 还是已超轮数直接进餐搜索
    g.add_conditional_edges(
        "planner", route_after_planner,
        {"reviewer": "reviewer", "meal_search": "meal_search"},
    )
    # reviewer 通过则进餐搜索；打回则给 planner 一次响应机会（出口在 planner 侧）
    g.add_conditional_edges(
        "reviewer", route_after_review,
        {"planner": "planner", "meal_search": "meal_search"},
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
    # max_review_rounds 轮 reviewer + (max_review_rounds+1) 轮 planner，再留余量
    config = {"recursion_limit": 2 * (init.max_review_rounds + 1) + 10}
    result = app.invoke(init, config=config)
    return TravelPlanState(**result) if isinstance(result, dict) else result


# ─── 分阶段流式入口（SSE 事件源）───────────────────────────────

# 节点名 → 进度文案。同时充当“哪些事件需要透出”的过滤白名单。
# planner/reviewer 文案在运行时按轮次/通过位动态拼接，这里留占位。
_NODE_LABELS: dict[str, str] = {
    "intent":            "🧭 正在理解出行意图（目的地 / 日期 / 偏好）",
    "attraction_search": "🗺 正在调用高德搜索景点池",
    "planner":           "✍️ 正在规划逐日行程",
    "reviewer":          "🔍 正在评审行程",
    "meal_search":       "🍽 正在搜索周边餐厅",
    "meal_recommend":    "🍴 正在为每天挑选餐厅",
    "finalize":          "📦 正在收敛生成最终行程",
}


def _stage_event(node: str, acc: dict[str, Any], upd: dict[str, Any]) -> dict[str, Any]:
    """据节点名与累积状态构造一条 stage 进度事件。"""
    label = _NODE_LABELS[node]
    ev: dict[str, Any] = {"type": "stage", "node": node, "label": label}
    if node == "planner":
        rnd = acc.get("review_round") or 1
        ev["round"] = rnd
        ev["label"] = f"{label}（第 {rnd} 轮）"
    elif node == "reviewer":
        rnd = acc.get("review_round") or 1
        approved = bool(upd.get("approved"))
        ev["round"] = rnd
        ev["approved"] = approved
        verdict = "✅ 通过" if approved else "⚠️ 打回"
        ev["label"] = f"{label}：第 {rnd} 轮 {verdict}"
    return ev


async def run_stream(query: str, **overrides: Any) -> AsyncIterator[dict[str, Any]]:
    """分阶段流式执行流水线，逐节点 yield 进度事件，末尾 yield 最终结果。

    事件类型：
      {"type": "stage",  "node", "label", ...}   每个节点完成时
      {"type": "result", "success", "missing_fields", "history", "plan"}  全部结束

    与 `run()` 共用 build_graph / config，仅改为 astream_events 事件源；
    旧 invoke 路径不受影响。
    """
    app = build_graph(overrides.get("model_name"))
    init = TravelPlanState(query=query, **overrides)
    config = {"recursion_limit": 2 * (init.max_review_rounds + 1) + 10}

    acc: dict[str, Any] = init.model_dump()
    async for event in app.astream_events(init, config=config, version="v2"):
        if event.get("event") != "on_chain_end":
            continue
        node = event.get("name")
        if node not in _NODE_LABELS:
            continue
        upd = (event.get("data") or {}).get("output")
        if not isinstance(upd, dict):
            continue
        acc.update(upd)
        yield _stage_event(node, acc, upd)

    final = TravelPlanState(**acc)
    success = not bool(final.missing_fields) and final.final_plan is not None
    yield {
        "type": "result",
        "success": success,
        "missing_fields": final.missing_fields,
        "history": final.history,
        "plan": final.final_plan if success else None,
    }
