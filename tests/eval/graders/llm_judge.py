"""LLM-as-judge：对最终 route+notes 的主观质量打分（代码打分器覆盖不到的维度）。

只看产物（route + notes），不看中间路径。temperature=0，结构化输出走 invoke_structured。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.llm.deepseek import build_structured_deepseek
from app.planning.helpers import (
    format_spots_for_llm,
    format_weather_for_llm,
    invoke_structured,
)

JUDGE_SYSTEM = (
    "你是严格的旅游行程质量评审专家。只依据给定的『最终行程』『候选景点池』"
    "『用户偏好』『天气』打分，不臆测未提供的信息。每个维度 1-5 分"
    "（1=很差，3=合格，5=优秀），并给一句中文理由。务必客观、可复现。"
)


class JudgeScores(BaseModel):
    preference_fit: int = Field(description="景点是否贴合用户『景点偏好』，1-5")
    habit_fit: int = Field(description="节奏/起止时间是否契合用户『游玩习惯』（如不早起/慢节奏），1-5")
    theme_coherence: int = Field(description="每天主题是否连贯、当天景点是否成主题，1-5")
    route_reasonableness: int = Field(description="动线是否顺、时间编排是否合理，1-5")
    weather_adaptation: int = Field(description="是否适配天气且 notes 有解释相关调整，1-5")
    comment: str = Field(default="", description="一句话总评")


def judge_plan(state: Any, fx: dict[str, Any], model_name: str | None = None) -> dict[str, Any]:
    """对最终行程做 LLM 评委打分。返回 {scores: {...}, avg: float} 或 {error: ...}。"""
    notes = ""
    # route 各天无 notes 字段；planner 的版本说明落在对话最后一条 Planner 行里
    for line in reversed(state.planner_reviewer_dialogue or []):
        if "Planner" in line:
            notes = line
            break

    prompt = (
        f"用户需求：{state.query}\n"
        f"目的地：{state.destination}，{fx.get('days')} 天\n"
        f"景点偏好：{state.attraction_preference or '无'}\n"
        f"游玩习惯：{state.habit_preference or '无'}\n"
        f"天气：\n{format_weather_for_llm(state.weather_forecast) or '无'}\n\n"
        f"候选景点池：\n{format_spots_for_llm(state.pois)}\n\n"
        f"最终行程（逐天时刻表）：\n{json.dumps(state.route, ensure_ascii=False)}\n\n"
        f"Planner 版本说明：{notes or '无'}\n\n请逐维度打分。"
    )
    llm = build_structured_deepseek(JudgeScores, model=model_name, temperature=0)
    try:
        res: JudgeScores = invoke_structured(llm, [("system", JUDGE_SYSTEM), ("human", prompt)])
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    scores = {
        "preference_fit": res.preference_fit,
        "habit_fit": res.habit_fit,
        "theme_coherence": res.theme_coherence,
        "route_reasonableness": res.route_reasonableness,
        "weather_adaptation": res.weather_adaptation,
    }
    avg = round(sum(scores.values()) / len(scores), 2)
    return {"scores": scores, "avg": avg, "comment": res.comment}
