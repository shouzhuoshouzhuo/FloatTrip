"""指标聚合与报告渲染。"""

from __future__ import annotations

from typing import Any

CODE_KEYS = ["g1_closed_pool", "g2_open_time", "g3_proximity",
             "g4_structure", "g5_coverage", "g6_weather", "g7_convergence"]
JUDGE_KEYS = ["preference_fit", "habit_fit", "theme_coherence",
              "route_reasonableness", "weather_adaptation"]


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def aggregate_case(case_id: str, tier: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    """把一个用例的 k 次 trial 聚合成用例级指标。

    每个 trial 形如：
      {code: {...}, judge: {...}, reliability: {...}, rebuttal: {...},
       overall_pass: bool, rounds: int}
    """
    k = len(trials)
    overall = [t["overall_pass"] for t in trials]
    passes = sum(overall)

    code_rate = {key: _mean([1.0 if t["code"]["results"][key]["passed"] else 0.0 for t in trials])
                 for key in CODE_KEYS}
    judge_avg = {key: _mean([t["judge"]["scores"][key] for t in trials
                             if key in t["judge"].get("scores", {})])
                 for key in JUDGE_KEYS}

    return {
        "id": case_id,
        "tier": tier,
        "k": k,
        "pass_rate": round(passes / k, 3) if k else 0.0,
        "pass_at_k": 1 if passes >= 1 else 0,          # 至少一次通过
        "pass_pow_k": 1 if passes == k else 0,         # k 次全过（可靠性）
        "rounds_mean": _mean([t["rounds"] for t in trials]),
        "code_pass_rate": code_rate,
        "judge_avg": judge_avg,
        "false_approval_rate": _mean([1.0 if t["reliability"]["false_approval"] else 0.0 for t in trials]),
        "false_rejection_rate": _mean([1.0 if t["reliability"]["false_rejection"] else 0.0 for t in trials]),
        "rebuttal_rate": _mean([t["rebuttal"].get("rebuttal_rate", 0.0) for t in trials]),
        "ignore_rate": _mean([t["rebuttal"].get("ignore_rate", 0.0) for t in trials]),
        "rebutted_rate": _mean([1.0 if t["rebuttal"].get("rebutted") else 0.0 for t in trials]),
        "healthy_rebut": sum(1 for t in trials if t["rebuttal"].get("health") == "healthy"),
        "harmful_rebut": sum(1 for t in trials if t["rebuttal"].get("health") == "harmful"),
    }


def render_report(cases: list[dict[str, Any]]) -> str:
    """渲染 Markdown 报告。"""
    lines: list[str] = ["# Planner⇄Reviewer 评估报告", ""]

    def section(title: str, subset: list[dict[str, Any]]):
        if not subset:
            return
        lines.append(f"## {title}（{len(subset)} 例）")
        lines.append("")
        lines.append("| 用例 | k | pass率 | pass@k | pass^k | 轮次均值 | 误放行 | 误打回 | 反驳率 | 忽略率 | 评委均分 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for c in subset:
            judge_overall = _mean([v for v in c["judge_avg"].values() if v])
            lines.append(
                f"| {c['id']} | {c['k']} | {c['pass_rate']:.0%} | {c['pass_at_k']} | "
                f"{c['pass_pow_k']} | {c['rounds_mean']} | {c['false_approval_rate']:.0%} | "
                f"{c['false_rejection_rate']:.0%} | {c['rebuttal_rate']:.2f} | "
                f"{c['ignore_rate']:.2f} | {judge_overall} |"
            )
        lines.append("")

    section("Regression（期望≈100%）", [c for c in cases if c["tier"] == "regression"])
    section("Capability（提升目标）", [c for c in cases if c["tier"] != "regression"])

    # 汇总
    n = len(cases)
    if n:
        lines.append("## 汇总")
        lines.append("")
        lines.append(f"- 用例数：{n}")
        lines.append(f"- 平均 pass 率：{_mean([c['pass_rate'] for c in cases]):.1%}")
        lines.append(f"- pass@k 比例：{_mean([c['pass_at_k'] for c in cases]):.1%}")
        lines.append(f"- pass^k 比例（全程可靠）：{_mean([c['pass_pow_k'] for c in cases]):.1%}")
        lines.append(f"- 平均收敛轮次：{_mean([c['rounds_mean'] for c in cases])}")
        lines.append(f"- reviewer 误放行率：{_mean([c['false_approval_rate'] for c in cases]):.1%}")
        lines.append(f"- reviewer 误打回率：{_mean([c['false_rejection_rate'] for c in cases]):.1%}")
        lines.append(f"- planner 平均反驳率：{_mean([c['rebuttal_rate'] for c in cases]):.2f}")
        lines.append(f"- 健康反驳 / 有害反驳：{sum(c['healthy_rebut'] for c in cases)} / "
                     f"{sum(c['harmful_rebut'] for c in cases)}（run 级启发式）")
        lines.append("")
    return "\n".join(lines)
