"""异步画像更新 Agent：从原始 query 提取偏好，与现有画像做冲突解析，只更新冲突项。

不使用 rewritten_query——它已融合旧画像，用它更新画像会造成循环幻觉。
visited_destinations 由 memory_writer 用代码维护，不交给 LLM。
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.database import get_conn
from app.core.memory import get_user_profile, set_user_profile
from app.llm.deepseek import build_structured_deepseek
from app.planning.helpers import invoke_structured
from app.planning.prompts import PROFILE_UPDATER_SYSTEM
from app.planning.schemas import ProfileUpdateResult

logger = logging.getLogger(__name__)


def _profile_diff(existing: dict, result) -> list[str]:
    """计算三个偏好列表的真实增删，用于校验 LLM 的 change_log 是否落实。"""
    diff: list[str] = []
    for field in ("attraction_prefs", "food_prefs", "habit_prefs"):
        old = existing[field]
        new = getattr(result, field)
        added   = [x for x in new if x not in old]
        removed = [x for x in old if x not in new]
        if added:
            diff.append(f"{field} 新增 {added}")
        if removed:
            diff.append(f"{field} 移除 {removed}")
    return diff


def _sync_profile_update(user_id: str, raw_query: str, model_name: str | None) -> None:
    with get_conn() as conn:
        existing = get_user_profile(user_id, conn)

    llm = build_structured_deepseek(ProfileUpdateResult, model=model_name, temperature=0)
    result = invoke_structured(llm, [
        ("system", PROFILE_UPDATER_SYSTEM),
        ("human", (
            f"现有画像：{json.dumps({'attraction_prefs': existing['attraction_prefs'], 'food_prefs': existing['food_prefs'], 'habit_prefs': existing['habit_prefs']}, ensure_ascii=False)}\n\n"
            f"用户这次的原始出行需求：{raw_query}"
        )),
    ])

    # 守卫：change_log 与真实 diff 必须一致——LLM 偶发"只说不做"
    # （change_log 声称新增/移除，但输出的列表原样未动），此时跳过落库避免误导
    diff = _profile_diff(existing, result)
    if result.change_log and not diff:
        logger.warning(
            "[profile_updater] user=%s change_log 声称变更但列表无实际变化，跳过落库 change_log=%s",
            user_id, result.change_log,
        )
        return
    if not diff:
        logger.info("[profile_updater] user=%s 无画像变更", user_id)
        return

    with get_conn() as conn:
        # 重新读取以获取最新 visited_destinations（代码路径可能已更新）
        latest = get_user_profile(user_id, conn)
        updated = {
            "attraction_prefs":     result.attraction_prefs,
            "food_prefs":           result.food_prefs,
            "habit_prefs":          result.habit_prefs,
            "visited_destinations": latest["visited_destinations"],
        }
        set_user_profile(user_id, updated, conn)

    logger.info("[profile_updater] user=%s diff=%s changes=%s", user_id, diff, result.change_log)


async def run_profile_update_agent(user_id: str, raw_query: str, model_name: str | None = None) -> None:
    """非阻塞地在线程池中运行画像冲突解析，不影响主流程。"""
    try:
        await asyncio.to_thread(_sync_profile_update, user_id, raw_query, model_name)
    except Exception:
        logger.warning("[profile_updater] 画像更新失败 user=%s", user_id, exc_info=True)
