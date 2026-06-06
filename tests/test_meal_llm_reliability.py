"""
DeepSeek 结构化输出可靠性压测：改造前 vs 改造后

测试三种方案，每种跑 TRIALS 次，统计成功率：
  方案 A（改造前）：旧 7 字段 schema + 20 候选 × 2 天一次调用
  方案 B（中间态）：新 4 字段 schema + 20 候选 × 单天调用
  方案 C（改造后）：新 4 字段 schema + 10 候选（top-10）× 单天调用

用法：
    python -m tests.test_meal_llm_reliability
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel, Field

from app.llm.deepseek import build_structured_deepseek
from app.planning.helpers import invoke_structured
from app.planning.prompts import MEAL_SYSTEM
from app.planning.schemas import SingleDayMealPick

# ─── 配置 ─────────────────────────────────────────────────────

TRIALS = 30          # 每种方案测试次数（建议 ≥ 30，统计显著性更好）
RETRIES = 3          # invoke_structured 重试次数（与生产一致）
FOOD_PREF = "本地特色小吃，偏好清淡"

# ─── 旧版 schema（改造前，7 字段）────────────────────────────

class _OldDayMealPick(BaseModel):
    day: int = Field(description="第几天")
    lunch_name: str = Field(description="午餐餐厅名，来自该天候选餐厅；无合适则空字符串")
    lunch_reason: str = Field(default="", description="午餐推荐理由")
    lunch_fallback_reason: str = Field(default="", description="午餐降级理由；满足偏好时返回空字符串")
    dinner_name: str = Field(description="晚餐餐厅名，来自该天候选餐厅；无合适则空字符串")
    dinner_reason: str = Field(default="", description="晚餐推荐理由")
    dinner_fallback_reason: str = Field(default="", description="晚餐降级理由；满足偏好时返回空字符串")

class _OldMealRecommendation(BaseModel):
    picks: list[_OldDayMealPick] = Field(description="逐天午/晚餐选择")

# ─── Mock 候选餐厅数据 ────────────────────────────────────────

def _make_candidates(n: int) -> list[dict[str, Any]]:
    """生成 n 家 mock 候选餐厅（模拟高德返回数据）。"""
    restaurants = [
        ("天目湖鱼头王", 4.9, "128", "淡水鱼;江浙菜"),
        ("溧阳本帮菜馆", 4.8, "88",  "本帮菜"),
        ("老街麻糕铺",   4.7, "25",  "小吃;糕点"),
        ("天目湖茶楼",   4.7, "65",  "茶餐厅"),
        ("竹林农家乐",   4.6, "75",  "农家菜"),
        ("常州蟹黄汤包", 4.6, "55",  "本地小吃"),
        ("苏锡常面馆",   4.5, "32",  "面食"),
        ("百年老灶火锅", 4.5, "95",  "火锅"),
        ("江南水乡菜",   4.4, "72",  "江浙菜"),
        ("大排档烧烤",   4.4, "60",  "烧烤"),
        ("洪泽湖大闸蟹", 4.3, "150", "海鲜;淡水蟹"),
        ("重庆小面",     4.3, "28",  "面食"),
        ("粤式早茶",     4.3, "80",  "粤菜;茶点"),
        ("韩式烤肉",     4.2, "110", "韩餐"),
        ("日式拉面",     4.2, "75",  "日料"),
        ("西式牛排馆",   4.1, "180", "西餐"),
        ("台湾卤肉饭",   4.1, "45",  "台湾菜"),
        ("新疆大盘鸡",   4.0, "68",  "新疆菜"),
        ("川味麻辣烫",   4.0, "35",  "川菜;快餐"),
        ("东北饺子馆",   3.9, "42",  "东北菜"),
    ]
    return [
        {"name": name, "rating": rating, "cost": cost, "keytag": tag}
        for name, rating, cost, tag in restaurants[:n]
    ]

def _fmt(cands: list[dict]) -> str:
    if not cands:
        return "（无候选）"
    return "\n".join(
        f"  · {c['name']}（评分 {c['rating']}，人均 {c['cost']}，标签 {c['keytag']}）"
        for c in cands
    )

# ─── 三种方案的 prompt 构建 ───────────────────────────────────

def _prompt_old_2days(n: int = 20) -> str:
    """方案 A：2 天候选全部塞入一个 prompt（改造前）。"""
    cands = _make_candidates(n)
    lines = []
    for day in [1, 2]:
        lines.append(
            f"Day {day}\n"
            f" 午餐候选（景点A 周边）：\n{_fmt(cands)}\n"
            f" 晚餐候选（景点B 周边）：\n{_fmt(cands)}"
        )
    return (
        f"用户用餐偏好：{FOOD_PREF}\n\n"
        + "\n\n".join(lines)
        + "\n\n请为每天选出午餐和晚餐。"
    )

def _prompt_new_single_day(n: int) -> str:
    """方案 B/C：单天 prompt，候选数量可配置。"""
    cands = _make_candidates(n)
    return (
        f"第 1 天 | 用户用餐偏好：{FOOD_PREF}\n\n"
        f"午餐候选（景点A 周边）：\n{_fmt(cands)}\n\n"
        f"晚餐候选（景点B 周边）：\n{_fmt(cands)}\n\n"
        "请选出今天的午餐和晚餐。"
    )

# ─── 压测执行 ─────────────────────────────────────────────────

def _run_trials(
    label: str,
    llm: Any,
    prompt_fn,
    trials: int = TRIALS,
) -> dict:
    successes = 0
    failures  = 0
    latencies = []

    print(f"\n{'='*55}")
    print(f"  {label}  ({trials} 次)")
    print(f"{'='*55}")

    for i in range(1, trials + 1):
        t0 = time.time()
        try:
            result = invoke_structured(
                llm,
                [("system", MEAL_SYSTEM), ("human", prompt_fn())],
                retries=RETRIES,
            )
            elapsed = time.time() - t0
            if result is not None:
                successes += 1
                latencies.append(elapsed)
                print(f"  [{i:>2}/{trials}] ✅ 成功  {elapsed:.1f}s")
            else:
                failures += 1
                print(f"  [{i:>2}/{trials}] ❌ None  {elapsed:.1f}s")
        except RuntimeError as e:
            elapsed = time.time() - t0
            failures += 1
            print(f"  [{i:>2}/{trials}] 💥 异常  {elapsed:.1f}s  {str(e)[:40]}")

    success_rate = successes / trials * 100
    avg_lat = sum(latencies) / len(latencies) if latencies else 0

    print(f"\n  成功 {successes}/{trials}  成功率 {success_rate:.1f}%  平均耗时 {avg_lat:.1f}s")
    return {"label": label, "success": successes, "fail": failures,
            "rate": success_rate, "avg_latency": avg_lat}


def main():
    print("\n🧪 DeepSeek 结构化输出可靠性压测")
    print(f"   每种方案 {TRIALS} 次，invoke_structured retries={RETRIES}\n")

    # 构建三种 LLM 客户端
    llm_old = build_structured_deepseek(_OldMealRecommendation, temperature=0)
    llm_new = build_structured_deepseek(SingleDayMealPick,      temperature=0)

    results = []

    # 方案 A：改造前（旧 schema + 20 候选 × 2 天）
    results.append(_run_trials(
        "方案 A｜改造前：旧7字段schema + 20候选×2天",
        llm_old,
        lambda: _prompt_old_2days(n=20),
    ))

    # 方案 B：中间态（新 schema + 20 候选 × 单天）
    results.append(_run_trials(
        "方案 B｜中间态：新4字段schema + 20候选×单天",
        llm_new,
        lambda: _prompt_new_single_day(n=20),
    ))

    # 方案 C：改造后（新 schema + top-10 × 单天）
    results.append(_run_trials(
        "方案 C｜改造后：新4字段schema + top10×单天",
        llm_new,
        lambda: _prompt_new_single_day(n=10),
    ))

    # ─── 汇总报告 ─────────────────────────────────────────────
    print(f"\n{'='*55}")
    print("  📊 汇总报告")
    print(f"{'='*55}")
    print(f"  {'方案':<40} {'成功率':>7}  {'平均耗时':>8}")
    print(f"  {'-'*40} {'-'*7}  {'-'*8}")
    for r in results:
        bar = "█" * int(r["rate"] / 5)
        print(f"  {r['label']:<40} {r['rate']:>6.1f}%  {r['avg_latency']:>6.1f}s  {bar}")

    a, b, c = results
    print(f"\n  改造前→改造后成功率提升：{a['rate']:.1f}% → {c['rate']:.1f}%"
          f"（+{c['rate']-a['rate']:.1f}pp）")
    print(f"  schema 精简贡献（A→B）：{b['rate']-a['rate']:+.1f}pp")
    print(f"  候选截断贡献（B→C）：   {c['rate']-b['rate']:+.1f}pp")
    print()


if __name__ == "__main__":
    main()
