"""
query_rewrite 评估入口。

用法：
    python -m tests.eval_query_rewrite.run_eval
    python -m tests.eval_query_rewrite.run_eval --only conflict-food-query-wins
    python -m tests.eval_query_rewrite.run_eval --k 3
    python -m tests.eval_query_rewrite.run_eval --k 3 --out qr_eval_report.md
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

# 加载项目根路径（兼容 python -m 和直接运行两种方式）
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.eval_query_rewrite.fixtures import FIXTURES, FIXTURE_INDEX
from tests.eval_query_rewrite.harness import run_single


# ─── 格式化辅助 ────────────────────────────────────────────────────────────────

def _fmt_profile(profile: dict) -> str:
    parts = []
    if profile.get("attraction_prefs"):
        parts.append("景点=" + "/".join(profile["attraction_prefs"]))
    if profile.get("food_prefs"):
        parts.append("餐饮=" + "/".join(profile["food_prefs"]))
    if profile.get("habit_prefs"):
        parts.append("习惯=" + "/".join(profile["habit_prefs"]))
    return "  ".join(parts) if parts else "（空）"


def _fmt_prefs_output(output: dict) -> str:
    parts = []
    for label, key in [("景点", "attraction_preference"), ("餐饮", "food_preference"), ("习惯", "habit_preference")]:
        v = output.get(key)
        parts.append(f"{label}={v or 'None'}")
    return "  ".join(parts)


def _grade_icon(val) -> str:
    if val is True:
        return "✅"
    if val is False:
        return "❌"
    return "─"   # N/A


def _print_result(result: dict, trial: int | None = None) -> list[str]:
    """打印单次运行结果，返回行列表（同时用于 Markdown 落盘）。"""
    lines: list[str] = []
    fx_id = result["fixture_id"]
    desc  = result["description"]
    trial_label = f" [trial {trial}]" if trial is not None else ""

    lines.append(f"\n[{fx_id}]{trial_label}  {desc}")
    lines.append(f"  raw_query      : {result['raw_query']}")
    lines.append(f"  profile        : {_fmt_profile(result['profile_from_db'])}")
    lines.append(f"  intent_prefs   : {result['intent_prefs_string']}")

    # 传给 LLM 的画像文本
    profile_text = result["profile_text"]
    lines.append(f"  profile_text   : {textwrap.shorten(profile_text, width=100, placeholder='…')}")

    # LLM 输出
    out = result["output"]
    lines.append(f"  rewritten_query: {textwrap.shorten(out['rewritten_query'], 100, placeholder='…')}")
    lines.append(f"  reasoning      : {textwrap.shorten(out.get('reasoning') or '', 80, placeholder='…')}")
    lines.append(f"  prefs_output   : {_fmt_prefs_output(out)}")

    # 打分
    g = result["grading"]
    lines.append("")
    if g.get("g_supplement") is not None:
        detail = g.get("g_supplement_detail", "")
        lines.append(f"  {_grade_icon(g['g_supplement'])} g_supplement     {detail}")
    if g.get("g_conflict") is not None:
        detail = g.get("g_conflict_detail", "")
        lines.append(f"  {_grade_icon(g['g_conflict'])} g_conflict       {detail}")
    if g.get("g_no_invention") is not None:
        detail = g.get("g_no_invention_detail", "")
        lines.append(f"  {_grade_icon(g['g_no_invention'])} g_no_invention   {detail}")

    overall = g.get("overall_pass", False)
    lines.append(f"  {'─ PASS' if overall else '✗ FAIL'}")
    return lines


def _summarize(all_results: list[list[dict]]) -> list[str]:
    """生成汇总（all_results[i] = fixture i 的 k 次 trial 列表）。"""
    lines = ["\n" + "═" * 50, "汇总", "═" * 50]

    total_fx = len(all_results)
    pass_fx  = 0   # 至少 1 次 pass 的 fixture 数
    g_counters: dict[str, list[bool]] = {
        "g_supplement": [], "g_conflict": [], "g_no_invention": [],
    }

    for trials in all_results:
        fx_passes = any(r["grading"]["overall_pass"] for r in trials)
        if fx_passes:
            pass_fx += 1
        for r in trials:
            g = r["grading"]
            for key in g_counters:
                if isinstance(g.get(key), bool):
                    g_counters[key].append(g[key])

    lines.append(f"{total_fx} 个用例  pass@k(≥1次) = {pass_fx}/{total_fx}")
    for key, vals in g_counters.items():
        if vals:
            lines.append(f"  {key:20s}: {sum(vals)}/{len(vals)}")
    return lines


# ─── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="query_rewrite eval")
    parser.add_argument("--only", help="只跑指定 fixture id")
    parser.add_argument("--k", type=int, default=1, help="每个用例重复次数（默认 1）")
    parser.add_argument("--model", default=None, help="DeepSeek 模型名（默认用环境变量）")
    parser.add_argument("--out", default=None, help="报告输出路径（.md）")
    args = parser.parse_args()

    fixtures = [FIXTURE_INDEX[args.only]] if args.only else FIXTURES

    header = ["", "═" * 60, "eval_query_rewrite", "═" * 60]
    all_lines: list[str] = list(header)

    all_results: list[list[dict]] = []

    for fx in fixtures:
        fx_trials: list[dict] = []
        for trial in range(args.k):
            print(f"\n>>> 运行 [{fx['id']}] trial {trial + 1}/{args.k} …", flush=True)
            result = run_single(fx, model_name=args.model)
            fx_trials.append(result)
            trial_label = trial + 1 if args.k > 1 else None
            lines = _print_result(result, trial=trial_label)
            for line in lines:
                print(line)
            all_lines.extend(lines)
        all_results.append(fx_trials)

    summary_lines = _summarize(all_results)
    for line in summary_lines:
        print(line)
    all_lines.extend(summary_lines)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text("\n".join(all_lines), encoding="utf-8")
        print(f"\n报告已写入 {out_path}")


if __name__ == "__main__":
    main()
