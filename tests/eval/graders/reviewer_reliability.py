"""Reviewer 可靠性 + Planner 反驳率。

直接评估 reviewer 与 planner 的协作行为：
1. reviewer 决策 vs 代码打分客观真值 → 误放行 / 误打回
2. planner 对 reviewer 意见的回应 → 采纳 / 反驳坚持 / 忽略（反驳率为核心新增指标）

反驳是当前 prompt 未设计的『涌现行为』，故用 LLM 评委对历轮对话逐轮分类。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.llm.deepseek import build_structured_deepseek
from app.planning.helpers import invoke_structured

_ROUND_RE = re.compile(r"^\[第(\d+)轮\]\s*(Planner|Reviewer)")


# ─── reviewer 可靠性（确定性，对比代码打分真值）─────────────

def reviewer_reliability(state: Any, objective_pass: bool) -> dict[str, Any]:
    """对比 reviewer 最终决策与代码打分客观真值。

    - false_approval: reviewer 通过但客观未过（放过坏方案，最危险）
    - false_rejection: reviewer 未通过但客观已合格（误打回，浪费轮次）
    - agree: 两者一致
    """
    approved = bool(state.approved)
    return {
        "reviewer_approved": approved,
        "objective_pass": objective_pass,
        "false_approval": approved and not objective_pass,
        "false_rejection": (not approved) and objective_pass,
        "agree": approved == objective_pass,
    }


# ─── planner 反驳分类（LLM）──────────────────────────────────

class RebuttalLabel(BaseModel):
    round_from: int = Field(description="提出意见的 reviewer 轮次")
    stance: str = Field(description="planner 的回应：adopt（采纳改正）/ rebut（反驳并坚持原方案）/ ignore（既不改也不解释）")
    reason: str = Field(default="", description="一句话依据")


class RebuttalAnalysis(BaseModel):
    labels: list[RebuttalLabel] = Field(default_factory=list, description="每个『reviewer 打回 → 下一轮 planner 回应』转移一个标签")


REBUTTAL_SYSTEM = (
    "你分析旅游规划中 Planner 与 Reviewer 的多轮对话。对每一次"
    "『Reviewer 打回 → 下一轮 Planner 回应』，判断 Planner 的态度：\n"
    "- adopt：接受意见并据此修改\n"
    "- rebut：不认同，明确为原方案辩护/坚持\n"
    "- ignore：既未修改也未回应该意见（默默跳过）\n"
    "只依据对话文本判断，给出结构化标签。"
)


def _pair_rounds(dialogue: list[str]) -> list[tuple[int, str, str]]:
    """配对 (reviewer 打回轮次, reviewer 文本, 下一轮 planner 文本)。"""
    by_round: dict[int, dict[str, str]] = {}
    for line in dialogue or []:
        m = _ROUND_RE.match(line)
        if not m:
            continue
        rnd, role = int(m.group(1)), m.group(2)
        by_round.setdefault(rnd, {})[role] = line
    pairs: list[tuple[int, str, str]] = []
    for rnd in sorted(by_round):
        rev = by_round[rnd].get("Reviewer", "")
        nxt = by_round.get(rnd + 1, {}).get("Planner", "")
        if rev and "打回" in rev and nxt:
            pairs.append((rnd, rev, nxt))
    return pairs


def planner_rebuttal(state: Any, objective_pass: bool, model_name: str | None = None) -> dict[str, Any]:
    """分析 planner 对 reviewer 意见的回应分布。

    Returns:
        {
          transitions: int,                 # 可分析的『打回→回应』次数
          adopt/rebut/ignore: int,          # 各态度计数
          rebuttal_rate: float,             # rebut / transitions
          ignore_rate: float,
          rebutted: bool,                   # 本 run 是否出现过 ≥1 次反驳
          health: "healthy"|"harmful"|"n/a" # 运行级启发式（见下）
        }

    health 启发式（per-round 客观真值不可得，故用 run 级近似，并在报告中标注为启发式）：
      - 出现反驳且最终客观通过 → healthy（反驳未损害结果，甚至纠正了误打回）
      - 出现反驳但最终客观未过 → harmful（坚持了错误方案）
    """
    pairs = _pair_rounds(state.planner_reviewer_dialogue)
    base = {"transitions": len(pairs), "adopt": 0, "rebut": 0, "ignore": 0,
            "rebuttal_rate": 0.0, "ignore_rate": 0.0, "rebutted": False, "health": "n/a"}
    if not pairs:
        return base

    convo = "\n".join(state.planner_reviewer_dialogue)
    prompt = (
        "完整历轮对话：\n" + convo + "\n\n"
        "需要分类的转移（每条给一个标签，round_from 为打回的 Reviewer 轮次）：\n" +
        "\n".join(f"- 第{r}轮 Reviewer 打回 → 第{r + 1}轮 Planner 回应" for r, _, _ in pairs)
    )
    llm = build_structured_deepseek(RebuttalAnalysis, model=model_name, temperature=0)
    try:
        res: RebuttalAnalysis = invoke_structured(llm, [("system", REBUTTAL_SYSTEM), ("human", prompt)])
    except Exception as exc:  # noqa: BLE001
        base["error"] = str(exc)
        return base

    for lab in res.labels:
        stance = (lab.stance or "").strip().lower()
        if stance in base:
            base[stance] += 1
    n = max(base["transitions"], 1)
    base["rebuttal_rate"] = round(base["rebut"] / n, 3)
    base["ignore_rate"] = round(base["ignore"] / n, 3)
    base["rebutted"] = base["rebut"] > 0
    if base["rebutted"]:
        base["health"] = "healthy" if objective_pass else "harmful"
    return base
