"""LangGraph 节点函数：意图识别、景点搜索、规划、评审、餐饮搜索、推荐、finalize。"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Annotated, Any

logger = logging.getLogger(__name__)

from app.llm.deepseek import build_structured_deepseek
from app.providers.amap.poi import search_around_pois
from app.planning.schemas import (
    DayMealPick,
    IntentExtraction,
    ProfileUpdateResult,
    RewrittenQuery,
    RouteReview,
    SingleDayMealPick,
    SpotTipsResult,
    TimeCheckResult,
    TravelPlanState,
    TravelRoute,
)
from app.planning.helpers import (
    amap_key,
    day_proximity_report,
    dinner_anchor_spot,
    fetch_city_spots,
    fetch_weather_for_dates,
    filter_by_rating,
    format_spots_for_llm,
    format_weather_for_llm,
    haversine_km,
    invoke_structured,
    last_spot_of_period,
    parse_iso_date,
    restaurant_to_dict,
    spot_location_map,
    unknown_spots,
)
from app.planning.prompts import (
    INTENT_SYSTEM,
    MEAL_SYSTEM,
    PLANNER_SYSTEM,
    QUERY_REWRITE_SYSTEM,
    REVIEWER_SYSTEM,
    SPOT_TIPS_SYSTEM,
    TIME_CHECK_SYSTEM,
    WEEKDAYS,
)
from app.core.database import get_conn
from app.core.memory import search_profile_fields

from langgraph.graph import END


# ─── Query Rewrite Agent ─────────────────────────────────────

def make_query_rewrite_node(model_name: str | None, user_id: str | None):
    """固定工作流：直接读取用户画像，单次结构化 LLM 调用改写 query 并输出冲突解析后的偏好字段。"""
    rewrite_llm = build_structured_deepseek(RewrittenQuery, model=model_name, temperature=0)

    def query_rewrite(state: TravelPlanState) -> dict[str, Any]:
        raw = state.query
        try:
            # Step 1：直接读画像（固定查全部三字段，不走 ReAct tool）
            profile_text = "（该用户暂无历史画像）"
            if user_id:
                with get_conn() as conn:
                    data = search_profile_fields(
                        user_id, ["attraction_prefs", "food_prefs", "habit_prefs"], conn
                    )
                if data and any(data.values()):
                    parts = []
                    if data.get("attraction_prefs"):
                        parts.append("景点偏好：" + "、".join(data["attraction_prefs"]))
                    if data.get("food_prefs"):
                        parts.append("餐饮偏好：" + "、".join(data["food_prefs"]))
                    if data.get("habit_prefs"):
                        parts.append("游玩习惯：" + "、".join(data["habit_prefs"]))
                    profile_text = "\n".join(parts)

            # Step 2：单次结构化 LLM 调用（改写 + 冲突解析 + 输出偏好字段）
            intent_prefs = (
                f"本次查询提取的偏好：景点={state.attraction_preference or '无'}，"
                f"餐饮={state.food_preference or '无'}，习惯={state.habit_preference or '无'}"
            )
            rewritten: RewrittenQuery = invoke_structured(rewrite_llm, [
                ("system", QUERY_REWRITE_SYSTEM),
                ("human", f"原始查询：{raw}\n\n{intent_prefs}\n\n用户历史画像：\n{profile_text}"),
            ])

            note = f"[query_rewrite] {raw!r} → {rewritten.rewritten_query!r}（{rewritten.reasoning}）"
            return {
                "rewritten_query": rewritten.rewritten_query,
                "attraction_preference": rewritten.attraction_preference or state.attraction_preference,
                "food_preference":       rewritten.food_preference       or state.food_preference,
                "habit_preference":      rewritten.habit_preference      or state.habit_preference,
                "history": state.history + [note],
            }
        except Exception as exc:
            # 降级：直接用原始 query，不中断主流程；偏好字段保持 intent 提取值
            return {
                "history": state.history + [f"[query_rewrite] 失败降级（{exc}），使用原始查询"],
            }

    return query_rewrite


# ─── 意图识别 ────────────────────────────────────────────────

def make_intent_node(model_name: str | None, profile_hint: str = ""):
    llm = build_structured_deepseek(IntentExtraction, model=model_name, temperature=0)

    def intent(state: TravelPlanState) -> dict[str, Any]:
        today = date.today()
        system = INTENT_SYSTEM.format(today=today.isoformat(), weekday=WEEKDAYS[today.weekday()])
        # 注入用户历史偏好作为默认值参考
        hint = profile_hint or state.profile_hint or ""
        if hint:
            system += f"\n\n用户历史偏好（仅供参考，以用户本次输入为准，用户未说的字段才用历史默认值）：\n{hint}"
        effective_query = state.query
        result: IntentExtraction = invoke_structured(
            llm, [("system", system), ("human", effective_query)]
        )

        start = parse_iso_date(result.travel_start_date)
        end   = parse_iso_date(result.travel_end_date)
        destination = result.destination.strip() or None

        # travel_days 兜底：有出发日期 + 天数时，推算结束日期
        if start and not end and result.travel_days > 0:
            end = start + timedelta(days=result.travel_days - 1)

        missing: list[str] = []
        if not destination:
            missing.append("目的地")
        if not start:
            missing.append("出行开始日期")
        if not end:
            missing.append("出行结束日期")

        days = 0
        if start and end:
            if end < start:
                missing.append("结束日期早于开始日期")
            else:
                days = (end - start).days + 1

        # 天气预报（仅当目的地和日期均已确定时拉取）
        forecast: list[dict[str, Any]] = []
        w_note: str | None = None
        if not missing and destination and start and end:
            forecast, w_note = fetch_weather_for_dates(destination, start, end, amap_key())

        def opt(v: str) -> str | None:
            return v.strip() or None

        weather_log = f"，天气预报={len(forecast)}天" if forecast else ("，天气获取失败/超出范围" if not missing else "")
        note = (
            f"意图识别：destination={destination}，{start}~{end}（{days}天）"
            f"，景点偏好={opt(result.attraction_preference)}"
            f"，餐饮偏好={opt(result.food_preference)}"
            f"，习惯={opt(result.habit_preference)}"
            f"{weather_log}"
        )
        return {
            "destination": destination,
            "travel_start_date": start,
            "travel_end_date": end,
            "attraction_preference": opt(result.attraction_preference),
            "food_preference": opt(result.food_preference),
            "habit_preference": opt(result.habit_preference),
            "days": days,
            "missing_fields": missing,
            "weather_forecast": forecast,
            "weather_note": w_note,
            "history": state.history + [note],
        }

    return intent


def route_after_intent(state: TravelPlanState) -> str:
    return END if state.missing_fields else "query_rewrite"


# ─── 高德景点搜索 ─────────────────────────────────────────────

def attraction_search_node(state: TravelPlanState) -> dict[str, Any]:
    api_key = amap_key()
    spots = fetch_city_spots(state.destination or "", api_key, max_spots=state.max_spots)
    kept, _ = filter_by_rating(spots, state.min_rating)
    note = f"高德景点搜索：抓取 {len(spots)} 个，rating≥{state.min_rating} 保留 {len(kept)} 个"
    return {"pois": kept, "history": state.history + [note]}


# ─── Planner ─────────────────────────────────────────────────

def _travel_dates_block(state: TravelPlanState) -> str:
    """逐天『日期（星期）』块，供 planner/reviewer 判断景点当天是否开放
    （闭馆日/限定开放日，如『周一闭馆』『周三至周日开放』）。无出发日期时返回空串。"""
    if not state.travel_start_date or not state.days:
        return ""
    lines = [
        f"  Day{i + 1} = {(state.travel_start_date + timedelta(days=i)).isoformat()}"
        f"（{WEEKDAYS[(state.travel_start_date + timedelta(days=i)).weekday()]}）"
        for i in range(state.days)
    ]
    return (
        "\n\n出行日期与星期（请据此判断景点当天是否开放，"
        "勿把有闭馆日/限定开放日的景点排在其不开放的星期）：\n" + "\n".join(lines)
    )


def make_planner_node(model_name: str | None):
    llm = build_structured_deepseek(TravelRoute, model=model_name, temperature=0.3)

    def planner(state: TravelPlanState) -> dict[str, Any]:
        # ① 上一轮景点集合（用于 spot diff，检测"notes 说改但 JSON 未变"）
        old_spots = {s["name"] for day in (state.route or []) for s in day.get("spots", [])}
        # ② 是否最终修订轮（review_round 尚未 +1 时检测）
        is_final = (state.review_round >= state.max_review_rounds
                    and bool(state.route_modify_opinion))

        cand_text = format_spots_for_llm(state.pois)
        feedback = ""
        if state.route_modify_opinion:
            is_user_opinion = "【用户修改意见】" in state.route_modify_opinion
            opinion_label = (
                "用户直接修改意见（最高优先级，必须全部响应）"
                if is_user_opinion else
                "评审修改意见（请据此修订）"
            )
            feedback = (
                f"\n\n上一版路线：\n{json.dumps(state.route, ensure_ascii=False)}\n\n"
                f"{opinion_label}：\n{state.route_modify_opinion}\n\n"
                f"⚠️ 重要：你在 notes 中描述的所有改动必须在 days 字段的景点列表中真实体现。"
                f"Reviewer 直接读取 route JSON，不读 notes 文字——notes 说改了但 JSON 未变 = 没改。"
            )

        weather_text = format_weather_for_llm(state.weather_forecast)
        weather_block = (
            f"\n\n出行天气预报（请严格依据此安排景点，雨雪天优先室内）：\n{weather_text}"
            if weather_text else "\n\n（无天气信息，按晴天规划）"
        )

        # 历轮沟通记录：让 Planner 知道自己已响应了哪些意见
        dialogue_block = ""
        if state.planner_reviewer_dialogue:
            dialogue_text = "\n".join(state.planner_reviewer_dialogue)
            dialogue_block = (
                f"\n\n【历轮沟通记录（请对照，确认哪些意见已响应、哪些【紧急必须优先改】仍未修复）】\n"
                f"{dialogue_text}"
            )

        # ③ 最终修订提示（末轮告知 planner 这是最后机会）
        final_note = (
            "\n\n【最终修订】此轮是最后一次修订机会，之后不再评审。"
            "你要站在产品的角度，给出不会影响产品体验，不会让用户流失的路线，无需逐条解释修改原因。"
            if is_final else ""
        )

        prompt = (
            f"用户需求：{state.rewritten_query or state.query}\n"
            f"目的地：{state.destination}\n旅行天数：{state.days} 天\n"
            f"每天景点数上限：{state.max_per_day}\n"
            f"景点偏好：{state.attraction_preference or '无'}\n"
            f"游玩习惯/节奏：{state.habit_preference or '无'}"
            f"{_travel_dates_block(state)}"
            f"{weather_block}\n\n"
            f"候选景点池（共 {len(state.pois)} 个）：\n{cand_text}"
            f"{feedback}"
            f"{dialogue_block}"
            f"{final_note}\n\n"
            f"请给出 {state.days} 天带时刻表的逐天景点安排。"
        )
        result: TravelRoute = invoke_structured(llm, [("system", PLANNER_SYSTEM), ("human", prompt)])
        route = [d.model_dump() for d in result.days]
        rnd = state.review_round + 1

        # ④ spot diff：检测实际是否有景点变化，透明化"说改但没改"
        new_spots = {s["name"] for day in route for s in day.get("spots", [])}
        added   = new_spots - old_spots
        removed = old_spots - new_spots
        change_summary = ""
        if old_spots and (added or removed):
            parts = []
            if added:   parts.append(f"新增：{'、'.join(sorted(added))}")
            if removed: parts.append(f"移除：{'、'.join(sorted(removed))}")
            change_summary = f"（{' | '.join(parts)}）"

        note         = f"[第{rnd}轮] Planner 出稿：{result.notes or '(无说明)'}"
        planner_line = f"[第{rnd}轮] Planner：{result.notes or '(无说明)'}{change_summary}"

        # ⑤ route 与上一轮完全相同时写 warning（比较完整 JSON，时间/顺序改动不误报）
        history = state.history
        old_route_json = json.dumps(state.route, ensure_ascii=False, sort_keys=True)
        new_route_json = json.dumps(route, ensure_ascii=False, sort_keys=True)
        if state.route_modify_opinion and state.route and old_route_json == new_route_json:
            history = history + [
                f"⚠️ [第{rnd}轮] Planner route 与上一轮完全相同，未作任何修改",
            ]
        history = history + [note]

        return {
            "route": route,
            "review_round": rnd,
            "history": history,
            "planner_reviewer_dialogue": state.planner_reviewer_dialogue + [planner_line],
            "modification_concern": result.modification_concern or None,
        }

    return planner


# ─── Reviewer ────────────────────────────────────────────────

def make_reviewer_node(model_name: str | None):
    llm = build_structured_deepseek(RouteReview, model=model_name, temperature=0)

    def reviewer(state: TravelPlanState) -> dict[str, Any]:
        proximity  = day_proximity_report(state.route, state.pois)
        bad_unknown = unknown_spots(state.route, state.pois)

        facts = (
            f"每天地理跨度：\n{proximity}\n\n"
            f"非候选池景点：{('；'.join(bad_unknown)) or '无'}"
        )

        weather_text = format_weather_for_llm(state.weather_forecast)
        weather_block = (
            f"\n出行天气预报：\n{weather_text}\n"
            if weather_text else "\n（无天气信息）\n"
        )

        # 历轮沟通记录：让 Reviewer 知道自己之前提过哪些非时间类问题、是否已被修复
        dialogue_block = ""
        if state.planner_reviewer_dialogue:
            # 过滤掉 time_check 相关的对话，避免 reviewer 看到时间冲突信息
            non_time_lines = [
                line for line in state.planner_reviewer_dialogue
                if "[time_check" not in line
            ]
            if non_time_lines:
                dialogue_text = "\n".join(non_time_lines)
                dialogue_block = (
                    f"\n\n【历轮沟通记录（检查你之前标注的问题是否已被修复；"
                    f"未修复则继续指出，已修复则审查新问题）】\n{dialogue_text}"
                )

        prompt = (
            f"目的地：{state.destination}，共 {state.days} 天，每天上限 {state.max_per_day}。\n"
            f"用户游玩习惯：{state.habit_preference or '无'}"
            f"{_travel_dates_block(state)}\n"
            f"{weather_block}\n"
            f"候选景点池：\n{format_spots_for_llm(state.pois)}\n\n"
            f"待评审路线：\n{json.dumps(state.route, ensure_ascii=False)}\n\n"
            f"系统客观预检（请据此判断）：\n{facts}"
            f"{dialogue_block}\n\n"
            f"请评审并给出结论。⚠️ 开放时间和闭馆日由 time_check 专项 Agent 单独核查，"
            f"你不要评审开放时间相关问题。"
        )
        result: RouteReview = invoke_structured(llm, [("system", REVIEWER_SYSTEM), ("human", prompt)])
        approved = result.approved and not bad_unknown
        verdict  = "✅通过" if approved else "❌打回"

        # ── 后端日志：推理过程 + 审查结论（不进 history / planner_reviewer_dialogue）──
        logger.debug(
            "[Reviewer 第%d轮] 推理过程：\n%s",
            state.review_round, result.reasoning,
        )
        logger.info(
            "[Reviewer 第%d轮] %s（%d分）opinion=%r  issues=%r",
            state.review_round, verdict, result.score,
            result.route_modify_opinion or "(无)", result.issues,
        )

        # 完整写入 reviewer 意见，不截断，让用户在规划日志里看到完整评审过程
        opinion_full = result.route_modify_opinion or "(无意见)"
        issues_full  = ("；".join(result.issues)) if result.issues else ""
        note = (
            f"[第{state.review_round}轮] Reviewer {verdict}（{result.score}分）：{opinion_full}"
            + (f"\n  → 问题列表：{issues_full}" if issues_full else "")
        )

        # 追加本轮 Reviewer 记录到共享对话
        reviewer_line = (
            f"[第{state.review_round}轮] Reviewer {'通过' if approved else '打回'}"
            f"（{result.score}分）：{result.route_modify_opinion or '(无意见)'}"
        )
        return {
            "approved": approved,
            "need_modify_route": not approved,
            "route_modify_opinion": result.route_modify_opinion,
            "reviewer_issues": result.issues,
            "history": state.history + [note],
            "planner_reviewer_dialogue": state.planner_reviewer_dialogue + [reviewer_line],
        }

    return reviewer


def route_after_review(state: TravelPlanState) -> str:
    """主循环结束（通过 或 达最大轮数）→ time_check；否则还给 planner。

    终止循环的判断从 route_after_planner 移到这里，确保每一份最终路线都经过 reviewer 评估。
    然后进入 time_check 阶段独立核查开放时间，reviewer 不再处理时间问题。
    """
    if state.approved or state.review_round > state.max_review_rounds:
        return "time_check"
    return "planner"


def route_after_planner(state: TravelPlanState) -> str:
    """planner 输出的下一跳：

    - 已进入 time_check 阶段（time_check_done=True）：回 time_check 重新核查时间
    - 否则：进 reviewer 走主循环

    设计：time_check_done 是单向门——一旦置 True，planner 永远不再回 reviewer。
    """
    if state.time_check_done:
        return "time_check"
    return "reviewer"


def route_after_time_check(state: TravelPlanState) -> str:
    """time_check 输出的下一跳：

    - 无违规 → meal_search（时间合法）
    - 达 max_time_check_rounds 上限 → meal_search（带剩余问题前进，由 finalize 透传给前端）
    - 否则 → planner 修正
    """
    if not state.time_violations:
        return "meal_search"
    if state.time_check_round >= state.max_time_check_rounds:
        return "meal_search"
    return "planner"


# ─── time_check 专项 Agent ──────────────────────────────────

def make_time_check_node(model_name: str | None):
    """开放时间核查专家 Agent：CoT 推理 + 仅输出违规。

    职责单一——只判断每个景点的 start_time/end_time 是否符合开放时间和闭馆日；
    其他维度（地理、习惯、天气、合法性）一概不管。
    """
    llm = build_structured_deepseek(TimeCheckResult, model=model_name, temperature=0)

    def time_check(state: TravelPlanState) -> dict[str, Any]:
        rnd = state.time_check_round + 1

        # 拼当天日期/星期 + 每个景点的 安排时段 + 开放原文
        open_map = {s["name"]: (s.get("open_time") or "未知") for s in state.pois}
        lines: list[str] = []
        for day in state.route:
            day_no = day.get("day")
            for spot in day.get("spots", []):
                lines.append(
                    f"  Day{day_no} {spot.get('name')} 安排 "
                    f"{spot.get('start_time')}-{spot.get('end_time')} | "
                    f"开放原文：{open_map.get(spot.get('name'), '未知')}"
                )
        route_block = "\n".join(lines) if lines else "  （路线为空）"

        prompt = (
            f"目的地：{state.destination}"
            f"{_travel_dates_block(state)}\n\n"
            f"待核查的景点安排（每行格式：Day N 景点名 安排 start-end | 开放原文：...）：\n"
            f"{route_block}\n\n"
            f"请按 schema 字段顺序输出：先 reasoning 逐景点推理，再 violations 仅写确认违规的项。"
        )

        try:
            result: TimeCheckResult = invoke_structured(
                llm, [("system", TIME_CHECK_SYSTEM), ("human", prompt)], retries=3
            )
        except RuntimeError:
            # 静默降级：不阻塞主流程，让用户能拿到行程
            logger.warning("[time_check 第%d轮] LLM 调用失败，跳过时间核查", rnd)
            return {
                "time_violations": [],
                "time_check_done": True,
                "time_check_round": rnd,
                "history": state.history + [f"[time_check 第{rnd}轮] LLM 调用失败，跳过时间核查"],
            }

        # ── 后端日志：推理过程 + 审查结论 ──────────────────────────
        logger.debug(
            "[time_check 第%d轮] 推理过程：\n%s",
            rnd, result.reasoning,
        )
        if result.violations:
            violation_lines = "\n".join(
                f"  Day{v.day} {v.spot_name}：{v.detail}" for v in result.violations
            )
            logger.info(
                "[time_check 第%d轮] ❌ 发现 %d 处违规：\n%s",
                rnd, len(result.violations), violation_lines,
            )
        else:
            logger.info("[time_check 第%d轮] ✅ 无违规，时间安排全部合法", rnd)

        violations_dicts = [v.model_dump() for v in result.violations]
        if not violations_dicts:
            return {
                "time_violations": [],
                "time_check_done": True,
                "time_check_round": rnd,
                "history": state.history + [f"[time_check 第{rnd}轮] ✅ 无违规"],
                "planner_reviewer_dialogue": state.planner_reviewer_dialogue
                    + [f"[time_check 第{rnd}轮] 无违规"],
            }

        # 有违规：组装定向修正指令给 planner
        detail_lines = "\n".join(
            f"- Day{v.day} {v.spot_name}：{v.detail}" for v in result.violations
        )
        opinion = (
            f"【开放时间修正（第{rnd}轮）】仅修正以下时段冲突，其余安排保持不变：\n{detail_lines}"
        )
        note = f"[time_check 第{rnd}轮] 发现 {len(violations_dicts)} 处冲突：\n{detail_lines}"

        return {
            "time_violations": violations_dicts,
            "time_check_done": True,
            "time_check_round": rnd,
            "route_modify_opinion": opinion,
            "approved": False,  # 有时间问题就视为未通过
            "history": state.history + [note],
            "planner_reviewer_dialogue": state.planner_reviewer_dialogue + [note],
        }

    return time_check


# ─── 餐饮搜索 ────────────────────────────────────────────────

def meal_search_node(state: TravelPlanState) -> dict[str, Any]:
    api_key  = amap_key()
    loc_map  = spot_location_map(state.pois)
    meal_candidates: list[dict[str, Any]] = []
    warnings: list[str] = []

    for day in state.route:
        day_no = day.get("day")
        entry: dict[str, Any] = {"day": day_no, "lunch": {}, "dinner": {}}

        lunch_anchor  = last_spot_of_period(day, "morning")
        dinner_anchor = dinner_anchor_spot(day)

        for meal, anchor in (("lunch", lunch_anchor), ("dinner", dinner_anchor)):
            center = loc_map.get(anchor["name"]) if anchor else None
            if not center:
                warnings.append(f"Day{day_no} {meal} 无中心景点坐标")
                entry[meal] = {"anchor": anchor["name"] if anchor else None, "candidates": []}
                continue
            raw   = search_around_pois(center, api_key, types="餐饮服务", radius=1000, offset=20)
            cands = [r for r in (restaurant_to_dict(p) for p in raw) if r][:20]
            if not cands:
                warnings.append(f"Day{day_no} {meal}（{anchor['name']} 周边）无餐饮")
            entry[meal] = {"anchor": anchor["name"], "center": center, "candidates": cands}
        meal_candidates.append(entry)

    note = "周边餐饮搜索完成" + (f"（提醒：{'; '.join(warnings)}）" if warnings else "")
    return {"meal_candidates": meal_candidates, "history": state.history + [note]}


# ─── 餐厅推荐 ────────────────────────────────────────────────

def make_meal_recommend_node(model_name: str | None):
    from concurrent.futures import ThreadPoolExecutor

    llm = build_structured_deepseek(SingleDayMealPick, model=model_name, temperature=0)

    def meal_recommend(state: TravelPlanState) -> dict[str, Any]:

        def _top(cands: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
            """按评分降序取前 n 家，减少喂给 LLM 的 token。"""
            return sorted(cands, key=lambda c: -(c.get("rating") or 0))[:n]

        def _fmt(cands: list[dict[str, Any]]) -> str:
            if not cands:
                return "（无候选）"
            return "\n".join(
                f"  · {c['name']}（评分 {c['rating'] or '无'}，人均 {c['cost'] or '无'}，"
                f"标签 {c['keytag'] or '无'}）"
                for c in cands
            )

        def _recommend_day(entry: dict[str, Any]) -> DayMealPick:
            """单天 LLM 调用；失败时取评分最高的餐厅降级兜底。"""
            lunch_cands  = _top(entry["lunch"].get("candidates", []))
            dinner_cands = _top(entry["dinner"].get("candidates", []))
            prompt = (
                f"第 {entry['day']} 天 | 用户用餐偏好：{state.food_preference or '无特别偏好'}\n\n"
                f"午餐候选（{entry['lunch'].get('anchor')} 周边）：\n{_fmt(lunch_cands)}\n\n"
                f"晚餐候选（{entry['dinner'].get('anchor')} 周边）：\n{_fmt(dinner_cands)}\n\n"
                "请选出今天的午餐和晚餐。"
            )
            try:
                r: SingleDayMealPick = invoke_structured(
                    llm, [("system", MEAL_SYSTEM), ("human", prompt)], retries=5
                )
                return DayMealPick(day=entry["day"], **r.model_dump())
            except RuntimeError:
                def best(cands: list) -> str:
                    return cands[0]["name"] if cands else ""
                return DayMealPick(
                    day=entry["day"],
                    lunch_name=best(lunch_cands),
                    lunch_reason="（系统自动选取评分最高餐厅）",
                    dinner_name=best(dinner_cands),
                    dinner_reason="（系统自动选取评分最高餐厅）",
                )

        # 不同天并行调用 LLM
        with ThreadPoolExecutor(max_workers=max(1, len(state.meal_candidates))) as ex:
            day_picks: list[DayMealPick] = list(
                ex.map(_recommend_day, state.meal_candidates)
            )

        def _lookup(name: str, cands_dict: dict[str, Any], cands_list: list[dict]) -> dict | None:
            """子串匹配候选餐厅；LLM 名称改写时宽松匹配（含子串即算）。

            name 为空字符串代表"LLM 认为无偏好匹配而主动放弃"，不等于候选列表为空。
            ⚠️ 不能在 name 为空时提前 return None——那会让有 20 家候选的餐次也显示"暂无"。
            正确语义：只要 cands_list 非空就必有返回，None 只意味着候选列表确实为空。
            """
            if name:
                for key, val in cands_dict.items():
                    if name in key or key in name:
                        return val
            return cands_list[0] if cands_list else None

        pick_map = {p.day: p for p in day_picks}
        meals: list[dict[str, Any]] = []
        for entry in state.meal_candidates:
            pick              = pick_map.get(entry["day"])
            lunch_cands_list  = sorted(entry["lunch"].get("candidates", []),  key=lambda c: -(c.get("rating") or 0))
            dinner_cands_list = sorted(entry["dinner"].get("candidates", []), key=lambda c: -(c.get("rating") or 0))
            lunch_cands       = {c["name"]: c for c in lunch_cands_list}
            dinner_cands      = {c["name"]: c for c in dinner_cands_list}
            lunch_info   = _lookup(pick.lunch_name,  lunch_cands,  lunch_cands_list)  if pick else None
            dinner_info  = _lookup(pick.dinner_name, dinner_cands, dinner_cands_list) if pick else None

            if lunch_info is not None:
                lunch_info  = {**lunch_info,  "reason": pick.lunch_reason}
            if dinner_info is not None:
                dinner_info = {**dinner_info, "reason": pick.dinner_reason}

            # 确定性兜底：午/晚餐重复时换评分次高的一家
            if (lunch_info is not None and dinner_info is not None
                    and pick and pick.lunch_name == pick.dinner_name):
                alt = next(
                    (c for c in sorted(
                        entry["dinner"].get("candidates", []),
                        key=lambda c: -(c.get("rating") or 0),
                    ) if c["name"] != pick.lunch_name),
                    None,
                )
                if alt:
                    dinner_info = {**alt, "reason": f"（系统调整：避免与午餐重复，改选 {alt['name']}）"}
                else:
                    dinner_info = {**dinner_info,
                                   "reason": (dinner_info.get("reason") or "")
                                   + " ⚠️ 该区域仅此一家餐厅，午晚餐相同，出行前请确认周边餐饮。"}

            meals.append({"day": entry["day"], "lunch": lunch_info, "dinner": dinner_info})

        note = "餐厅推荐完成：" + "，".join(
            f"Day{m['day']} 午={m['lunch']['name'] if m['lunch'] else '无'}"
            f"/晚={m['dinner']['name'] if m['dinner'] else '无'}"
            for m in meals
        )
        return {"meals": meals, "history": state.history + [note]}

    return meal_recommend


# ─── finalize ────────────────────────────────────────────────

# ─── 景点游玩贴士 ─────────────────────────────────────────────

def make_spot_tips_node(model_name: str | None):
    """为行程中每个景点生成游玩注意事项（结合当天天气 + 景点属性 + 独有常识）。

    非关键路径：LLM 失败时降级为无贴士，不阻塞行程生成。
    """
    llm = build_structured_deepseek(SpotTipsResult, model=model_name, temperature=0)

    def spot_tips_node(state: TravelPlanState) -> dict[str, Any]:
        spot_names: list[str] = []
        lines: list[str] = []
        for day in state.route:
            day_no = day.get("day")
            the_date = ""
            if state.travel_start_date and day_no:
                d = state.travel_start_date + timedelta(days=day_no - 1)
                the_date = f"{d.isoformat()} {WEEKDAYS[d.weekday()]}"
            lines.append(f"第 {day_no} 天（{the_date or '日期未知'}）：")
            for spot in day.get("spots", []):
                spot_names.append(spot["name"])
                lines.append(
                    f"  · {spot['name']}（{spot.get('period')} {spot.get('start_time')}–{spot.get('end_time')}）"
                )
        if not spot_names:
            return {}

        weather_text = format_weather_for_llm(state.weather_forecast) or "（无可用天气预报）"
        prompt = (
            f"目的地：{state.destination}\n\n"
            "行程：\n" + "\n".join(lines) + "\n\n"
            f"逐天天气预报：\n{weather_text}"
        )
        try:
            result: SpotTipsResult = invoke_structured(
                llm, [("system", SPOT_TIPS_SYSTEM), ("human", prompt)]
            )
        except RuntimeError:
            return {"history": state.history + ["spot_tips：贴士生成失败，已跳过"]}

        # 名称匹配：先精确，再子串宽松兜底（LLM 偶发轻微改写名称）
        valid = set(spot_names)
        tips = {t.name: t.tip.strip() for t in result.tips if t.name in valid and t.tip.strip()}
        for t in result.tips:
            if t.name not in valid and t.tip.strip():
                for name in valid:
                    if name not in tips and (t.name in name or name in t.name):
                        tips[name] = t.tip.strip()
                        break

        note = f"spot_tips：为 {len(tips)}/{len(valid)} 个景点生成游玩贴士"
        return {"spot_tips": tips, "history": state.history + [note]}

    return spot_tips_node


def make_finalize_node(memory_writer=None):
    def finalize_node(state: TravelPlanState) -> dict[str, Any]:
        result = _finalize_impl(state)
        if memory_writer and result.get("final_plan"):
            try:
                memory_writer(result["final_plan"], state)
            except Exception:
                pass  # 记忆写入失败不影响主流程
        return result
    return finalize_node


def finalize_node(state: TravelPlanState) -> dict[str, Any]:
    return _finalize_impl(state)


def _finalize_impl(state: TravelPlanState) -> dict[str, Any]:
    """组装 final_plan：逐天时刻表 + 午晚餐 + 图片url + haversine 距离。"""
    spot_info    = {s["name"]: s for s in state.pois}
    meals_by_day = {m["day"]: m for m in state.meals}

    days_out: list[dict[str, Any]] = []
    for day in state.route:
        day_no   = day.get("day")
        the_date = None
        if state.travel_start_date:
            the_date = (state.travel_start_date + timedelta(days=day_no - 1)).isoformat()

        meal     = meals_by_day.get(day_no, {})
        timeline: list[dict[str, Any]] = []

        # 用名称相等（非 `is`）避免 LangGraph 序列化/反序列化后身份比较失效
        morning_anchor_name   = (last_spot_of_period(day, "morning") or {}).get("name")
        afternoon_anchor_name = (last_spot_of_period(day, "afternoon") or {}).get("name")
        lunch_inserted  = False
        dinner_inserted = False

        for spot in day.get("spots", []):
            info = spot_info.get(spot["name"], {})
            timeline.append({
                "type": "attraction",
                "name": spot["name"],
                "start_time": spot.get("start_time"),
                "end_time": spot.get("end_time"),
                "period": spot.get("period"),
                "rating": info.get("rating"),
                "open_time": info.get("open_time"),
                "photo": info.get("photo"),
                "location": info.get("location"),
                "tip": state.spot_tips.get(spot["name"]),
            })
            if spot.get("name") == morning_anchor_name and not lunch_inserted:
                lunch_inserted = True
                if meal.get("lunch"):
                    timeline.append({"type": "lunch", **meal["lunch"]})
                else:
                    timeline.append({"type": "lunch", "name": None, "no_restaurant": True})
            if spot.get("name") == afternoon_anchor_name and not dinner_inserted:
                dinner_inserted = True
                if meal.get("dinner"):
                    timeline.append({"type": "dinner", **meal["dinner"]})
                else:
                    timeline.append({"type": "dinner", "name": None, "no_restaurant": True})

        # 相邻地点 haversine 距离
        for i in range(1, len(timeline)):
            prev_loc = timeline[i - 1].get("location")
            cur_loc  = timeline[i].get("location")
            if prev_loc and cur_loc:
                timeline[i]["dist_from_prev_km"] = round(haversine_km(prev_loc, cur_loc), 2)

        days_out.append({"day": day_no, "date": the_date, "theme": day.get("theme"), "timeline": timeline})

    final_plan = {
        "query": state.query,
        "destination": state.destination,
        "start_date": state.travel_start_date.isoformat() if state.travel_start_date else None,
        "end_date": state.travel_end_date.isoformat() if state.travel_end_date else None,
        "days_count": state.days,
        "preferences": {
            "attraction": state.attraction_preference,
            "food": state.food_preference,
            "habit": state.habit_preference,
        },
        "approved": state.approved,
        "review_rounds": state.review_round,
        "weather_forecast": state.weather_forecast,
        "weather_note": state.weather_note,
        # 透传给前端的"出行注意事项"：来自 reviewer 最后一轮的 issues，
        # 已是给用户看的友好出行提醒。time_check 的 violations 不属于注意事项——
        # 它要么被 planner 修完（time_violations 清空），要么属于极端兜底情况（达轮数上限未清完），
        # 不是给用户的常规提醒。
        "route_issues": list(state.reviewer_issues or []),
        "days": days_out,
    }
    history = state.history + ["finalize：已组装最终计划"]
    # 规划过程日志随 plan 一起落库，历史详情页回看时可还原完整规划过程
    final_plan["history"] = history
    return {"final_plan": final_plan, "history": history}
