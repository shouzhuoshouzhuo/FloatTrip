"""评估入口：加载 fixtures → 每例跑 k 次 planner⇄reviewer → 打分 → 聚合 → 报告。

用法：
    python -m tests.eval.run_eval                  # 全部用例，k=5
    python -m tests.eval.run_eval --k 1            # 快速冒烟
    python -m tests.eval.run_eval --only nanjing-3d-sunny --k 1
    python -m tests.eval.run_eval --no-judge       # 跳过 LLM 评委/反驳（仅代码打分，省钱）
    python -m tests.eval.run_eval --out report.md  # 报告落盘
"""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
from typing import Any

from tests.eval.graders.code_graders import grade_code
from tests.eval.graders.llm_judge import judge_plan
from tests.eval.graders.reviewer_reliability import planner_rebuttal, reviewer_reliability
from tests.eval.harness import load_fixtures, run_planner_reviewer_loop
from tests.eval.report import aggregate_case, render_report

TRANSCRIPT_DIR = Path(__file__).resolve().parent / "transcripts"


def _run_trial(fx: dict[str, Any], use_judge: bool) -> dict[str, Any]:
    state = run_planner_reviewer_loop(fx)
    code = grade_code(state, fx)
    objective_pass = code["objective_pass"]
    converged = code["results"]["g7_convergence"]["passed"]

    judge = {"scores": {}, "avg": 0.0}
    rebuttal: dict[str, Any] = {"transitions": 0, "rebuttal_rate": 0.0,
                                "ignore_rate": 0.0, "rebutted": False, "health": "n/a"}
    if use_judge:
        judge = judge_plan(state, fx)
        rebuttal = planner_rebuttal(state, objective_pass)

    reliability = reviewer_reliability(state, objective_pass)
    return {
        "code": code,
        "judge": judge,
        "reliability": reliability,
        "rebuttal": rebuttal,
        # 整体通过 = 客观全过(G1-G6) 且 已收敛(G7)
        "overall_pass": objective_pass and converged,
        "rounds": state.review_round,
        "_state": {
            "route": state.route,
            "approved": state.approved,
            "review_round": state.review_round,
            "dialogue": state.planner_reviewer_dialogue,
            "reviewer_issues": state.reviewer_issues,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Planner⇄Reviewer 评估")
    ap.add_argument("--k", type=int, default=5, help="每个用例重复次数（默认 5）")
    ap.add_argument("--only", type=str, default=None, help="只跑指定用例 id")
    ap.add_argument("--no-judge", action="store_true", help="跳过 LLM 评委与反驳分析")
    ap.add_argument("--out", type=str, default=None, help="Markdown 报告输出路径")
    args = ap.parse_args()

    fixtures = load_fixtures(only=args.only)
    if not fixtures:
        print("未找到 fixture，请先在 tests/eval/fixtures/ 放置用例 JSON。")
        return

    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    use_judge = not args.no_judge
    case_aggs: list[dict[str, Any]] = []

    for fx in fixtures:
        cid, tier = fx["id"], fx.get("tier", "capability")
        print(f"▶ {cid}（{tier}）跑 {args.k} 次…")
        trials: list[dict[str, Any]] = []
        for i in range(args.k):
            try:
                t = _run_trial(fx, use_judge)
            except Exception as exc:  # noqa: BLE001
                print(f"  trial {i + 1} 失败：{exc}")
                traceback.print_exc()
                continue
            trials.append(t)
            flag = "✅" if t["overall_pass"] else "❌"
            print(f"  trial {i + 1}: {flag} 客观={t['code']['objective_pass']} "
                  f"收敛={t['rounds']}轮 反驳率={t['rebuttal'].get('rebuttal_rate')}")
        if not trials:
            print(f"  ⚠ {cid} 全部 trial 失败，跳过")
            continue
        # 落盘最后一次 trial 的 transcript，便于人工读「失败是否公平」
        (TRANSCRIPT_DIR / f"{cid}.json").write_text(
            json.dumps([t["_state"] for t in trials], ensure_ascii=False, indent=2),
            encoding="utf-8")
        case_aggs.append(aggregate_case(cid, tier, trials))

    report = render_report(case_aggs)
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n报告已写入 {args.out}")


if __name__ == "__main__":
    main()
