"""确定性代码打分器 G1–G8（直接复用 app/planning/helpers.py）。

每个 grader 返回 (passed: bool, detail: str)。
- G1 封闭池、G3 地理跨度、G4 结构合法、G5 覆盖、G6 天气合规：客观质量
- G2 time_check 干净：最终 state 中 time_violations 为空（开放时间由 time_check 负责，reviewer 不管）
- G7 收敛：approved + time_check_done（纳入 time_check 结果）
- G8 time_check 效率：time_check_round ≤ 1

「整体客观通过」objective_pass = G1–G6 全过（不含 G7/G8）。
"""

from __future__ import annotations

import re
from typing import Any

from app.planning.helpers import (
    day_proximity_report,
    haversine_km,
    open_time_violations,
    spot_location_map,
    unknown_spots,
)

_PERIOD_ORDER = {"morning": 0, "afternoon": 1, "evening": 2}
_TIME_RANGE_RE = re.compile(r"(\d{1,2})[:：](\d{2})\s*[-~—至]\s*(\d{1,2})[:：](\d{2})")


def _to_min(hhmm: str) -> int | None:
    m = re.match(r"\s*(\d{1,2})[:：](\d{2})", hhmm or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


# ─── G1 封闭池（硬性）────────────────────────────────────────

def g1_closed_pool(route: list[dict], pois: list[dict]) -> tuple[bool, str]:
    bad = unknown_spots(route, pois)
    return (not bad, "无越界景点" if not bad else f"越界景点：{'；'.join(bad)}")


# ─── G2 time_check 干净 ──────────────────────────────────────
# 开放时间核查已移交 time_check 专项 Agent；此处验证最终 state 无残留违规。
# 兼容旧 fixture-based eval（state 无 time_violations 字段时视为通过）。

def g2_time_check_clean(time_violations: list[dict]) -> tuple[bool, str]:
    viols = time_violations or []
    if not viols:
        return True, "time_check 无违规"
    detail = "；".join(f"Day{v.get('day')} {v.get('spot_name')}" for v in viols)
    return False, f"{len(viols)} 处时间违规未修复：{detail}"


# ─── G3 地理跨度 ─────────────────────────────────────────────

def g3_proximity(route: list[dict], pois: list[dict], max_span_km: float = 15.0) -> tuple[bool, str]:
    loc_map = spot_location_map(pois)
    over: list[str] = []
    for day in route:
        coords = [loc_map[s["name"]] for s in day.get("spots", []) if s["name"] in loc_map]
        if len(coords) < 2:
            continue
        span = max(
            haversine_km(coords[i], coords[j])
            for i in range(len(coords)) for j in range(i + 1, len(coords))
        )
        if span > max_span_km:
            over.append(f"Day{day.get('day')} 跨度 {span:.1f}km")
    return (not over, f"各天跨度 ≤ {max_span_km}km" if not over else "；".join(over))


# ─── G4 结构合法 ─────────────────────────────────────────────

def g4_structure(route: list[dict], pois: list[dict], max_per_day: int) -> tuple[bool, str]:
    """每天 ≤ max_per_day；时段按 morning→afternoon→evening 有序且不重叠；
    evening 景点关闭时间须 ≥ 20:00。"""
    close_map = {}
    for s in pois:
        rng = _TIME_RANGE_RE.search(s.get("open_time") or "")
        if rng:
            close_map[s["name"]] = int(rng.group(3)) * 60 + int(rng.group(4))
    errs: list[str] = []
    for day in route:
        spots = day.get("spots", [])
        d = day.get("day")
        if len(spots) > max_per_day:
            errs.append(f"Day{d} 景点数 {len(spots)}>{max_per_day}")
        prev_end = -1
        prev_period = -1
        for sp in spots:
            period = sp.get("period", "")
            porder = _PERIOD_ORDER.get(period, -1)
            if porder < 0:
                errs.append(f"Day{d} {sp.get('name')} 非法时段 '{period}'")
            elif porder < prev_period:
                errs.append(f"Day{d} {sp.get('name')} 时段逆序")
            prev_period = max(prev_period, porder)
            st, en = _to_min(sp.get("start_time", "")), _to_min(sp.get("end_time", ""))
            if st is None or en is None:
                errs.append(f"Day{d} {sp.get('name')} 时间缺失")
            else:
                if en <= st:
                    errs.append(f"Day{d} {sp.get('name')} 起止时间异常")
                if st < prev_end:
                    errs.append(f"Day{d} {sp.get('name')} 时段重叠")
                prev_end = max(prev_end, en)
            if period == "evening" and close_map.get(sp.get("name"), 24 * 60) < 20 * 60:
                errs.append(f"Day{d} {sp.get('name')} 夜间不开放")
    return (not errs, "结构合法" if not errs else "；".join(errs))


# ─── G5 覆盖 ─────────────────────────────────────────────────

def g5_coverage(route: list[dict], expected_days: int) -> tuple[bool, str]:
    if len(route) != expected_days:
        return False, f"天数 {len(route)}≠期望 {expected_days}"
    empty = [f"Day{d.get('day')}" for d in route if not d.get("spots")]
    return (not empty, "每天均有景点" if not empty else f"空白天：{'、'.join(empty)}")


# ─── G6 天气合规 ─────────────────────────────────────────────

def g6_weather(
    route: list[dict], pois: list[dict], weather_forecast: list[dict],
    outdoor_on_bad_day_max: int = 0,
) -> tuple[bool, str]:
    """雨雪天（is_bad）的露天景点数 ≤ 阈值。依赖 fixture POI 的 `indoor` 真值标签；
    无该标签则跳过（视为通过并说明）。
    候选池全是露天时也跳过——planner 无室内选项可选，强行判定不公平；
    这类"全露天+雨天"的冲突交由 LLM 评委评价应对策略质量。"""
    indoor_map = {s["name"]: s.get("indoor") for s in pois}
    labeled = {k: v for k, v in indoor_map.items() if v is not None}
    if not labeled:
        return True, "POI 未标注 indoor，跳过天气合规判定"
    if all(v is False for v in labeled.values()):
        return True, "候选池无室内景点（全露天），天气合规判定跳过——由 LLM 评委评价应对策略"
    bad_dates = {w["date"] for w in weather_forecast if w.get("is_bad")}
    if not bad_dates:
        return True, "无雨雪天"
    # route 的 day 序号 → 日期：按 weather_forecast 顺序对应（第 n 天 = 第 n 条预报）
    date_by_day = {i + 1: w.get("date") for i, w in enumerate(weather_forecast)}
    viol: list[str] = []
    for day in route:
        if date_by_day.get(day.get("day")) not in bad_dates:
            continue
        outdoor = [s["name"] for s in day.get("spots", []) if indoor_map.get(s["name"]) is False]
        if len(outdoor) > outdoor_on_bad_day_max:
            viol.append(f"Day{day.get('day')} 雨天露天 {len(outdoor)} 个：{'、'.join(outdoor)}")
    return (not viol, "雨雪天合规" if not viol else "；".join(viol))


# ─── G7 收敛（核心）─────────────────────────────────────────
# 收敛定义扩展：同时要求 reviewer 通过 + time_check 已完成且无残留违规
# （或 time_check 达到上限，此时带剩余问题前进，视为尽力收敛）。

def g7_convergence(
    approved: bool,
    review_round: int,
    max_rounds: int,
    time_check_done: bool = True,
    time_violations: list | None = None,
    time_check_round: int = 0,
    max_time_check_rounds: int = 3,
) -> tuple[bool, str]:
    reviewer_ok = approved and review_round <= max_rounds
    viols = time_violations or []
    time_ok    = time_check_done and not viols
    time_limit = time_check_round >= max_time_check_rounds
    ok = reviewer_ok and (time_ok or time_limit)
    tc_status = "✅" if time_ok else ("⚠️达上限" if time_limit else "❌")
    return ok, (
        f"reviewer={'✅' if reviewer_ok else '❌'}({review_round}/{max_rounds}轮)，"
        f"time_check={tc_status}({time_check_round}轮)"
    )


# ─── G8 time_check 效率 ───────────────────────────────────────
# time_check_round=0 表示第一次核查即无违规（最佳）；
# ≥ max_rounds 表示反复修正仍有问题（需关注 planner 开放时间理解能力）。

def g8_time_check_efficiency(
    time_check_round: int,
    time_violations: list | None = None,
) -> tuple[bool, str]:
    viols = time_violations or []
    ok = time_check_round <= 1 and not viols
    return ok, f"time_check 用了 {time_check_round} 轮，残留违规 {len(viols)} 处"


# ─── 汇总 ────────────────────────────────────────────────────

def grade_code(state: Any, fx: dict[str, Any]) -> dict[str, Any]:
    """对单次 run 的最终 state 跑全部代码打分器。

    Returns: {results: {g1..g8: {passed, detail}}, objective_pass: bool}
    objective_pass = G1–G6 全过（不含 G7 收敛、G8 效率）。

    兼容性说明：
    - 旧 fixture-based eval（harness.py）：state 无 time_violations/time_check_done，
      G2 读不到违规默认通过，G7/G8 用 getattr 安全降级。
    - sweep 完整流水线：state 携带全部字段，G2/G7/G8 完整生效。
    """
    route = state.route
    pois  = state.pois
    exp   = fx.get("expectations", {}) or {}
    r: dict[str, dict[str, Any]] = {}

    def rec(key, passed, detail):
        r[key] = {"passed": bool(passed), "detail": detail}

    time_violations      = getattr(state, "time_violations", None) or []
    time_check_done      = getattr(state, "time_check_done", True)
    time_check_round     = getattr(state, "time_check_round", 0)
    max_time_check_rounds = getattr(state, "max_time_check_rounds", 3)

    rec("g1_closed_pool",  *g1_closed_pool(route, pois))
    rec("g2_time_check",   *g2_time_check_clean(time_violations))
    rec("g3_proximity",    *g3_proximity(route, pois, float(exp.get("max_day_span_km", 15))))
    rec("g4_structure",    *g4_structure(route, pois, state.max_per_day))
    rec("g5_coverage",     *g5_coverage(route, int(fx.get("days", len(route)))))
    rec("g6_weather",      *g6_weather(
        route, pois, state.weather_forecast, int(exp.get("outdoor_on_bad_day_max", 0))))
    rec("g7_convergence",  *g7_convergence(
        state.approved, state.review_round, state.max_review_rounds,
        time_check_done, time_violations, time_check_round, max_time_check_rounds))
    rec("g8_time_check_efficiency", *g8_time_check_efficiency(time_check_round, time_violations))

    objective_keys = ["g1_closed_pool", "g2_time_check", "g3_proximity",
                      "g4_structure", "g5_coverage", "g6_weather"]
    objective_pass = all(r[k]["passed"] for k in objective_keys)
    return {"results": r, "objective_pass": objective_pass}
