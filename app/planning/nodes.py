"""LangGraph 节点函数：意图识别、景点搜索、规划、评审、餐饮搜索、推荐、finalize。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Annotated, Any

from app.llm.deepseek import build_chat_deepseek, build_structured_deepseek
from app.providers.amap.poi import search_around_pois
from app.planning.schemas import (
    DayMealPick,
    IntentExtraction,
    ProfileUpdateResult,
    RewrittenQuery,
    RouteReview,
    SingleDayMealPick,
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
    WEEKDAYS,
)
from app.core.database import get_conn
from app.core.memory import search_profile_fields

from langgraph.graph import END


# ─── Query Rewrite Agent ─────────────────────────────────────

def make_query_rewrite_node(model_name: str | None, user_id: str | None):
    """ReAct Agent：自主查询用户画像字段，改写 query 注入偏好上下文。
    未登录时返回透传节点（不改写）。
    """
    if not user_id:
        return lambda state: {}

    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent

    @tool
    def search_user_profile(fields: Annotated[list[str], "要查询的画像字段列表"]) -> str:
        """查询用户偏好画像中的指定字段。fields 可选：attraction_prefs, food_prefs, habit_prefs"""
        with get_conn() as conn:
            data = search_profile_fields(user_id, fields, conn)
        if not data or not any(data.values()):
            return "（该用户暂无相关偏好画像）"
        return json.dumps(data, ensure_ascii=False, indent=2)

    react_llm    = build_chat_deepseek(model=model_name, temperature=0)
    rewrite_llm  = build_structured_deepseek(RewrittenQuery, model=model_name, temperature=0)
    react_agent  = create_react_agent(react_llm, [search_user_profile])

    def query_rewrite(state: TravelPlanState) -> dict[str, Any]:
        raw = state.query
        try:
            # Phase 1：ReAct 自主决定查哪些字段，收集画像（最多 2 轮工具调用）
            # recursion_limit=6：agent→tools→agent→tools→agent→结束，刚好覆盖 2 轮
            agent_result = react_agent.invoke(
                {
                    "messages": [
                        ("system", QUERY_REWRITE_SYSTEM),
                        ("human", f"原始查询：{raw}"),
                    ]
                },
                config={"recursion_limit": 6},
            )
            agent_summary = agent_result["messages"][-1].content

            # Phase 2：结构化提取改写结果
            rewritten: RewrittenQuery = invoke_structured(rewrite_llm, [
                ("system", "根据以下画像分析，输出改写后的旅行查询。若无需改写则原样输出原始查询。"),
                ("human", f"原始查询：{raw}\n\nAgent 分析：\n{agent_summary}"),
            ])

            note = f"[query_rewrite] {raw!r} → {rewritten.rewritten_query!r}（{rewritten.reasoning}）"
            return {
                "rewritten_query": rewritten.rewritten_query,
                "history": state.history + [note],
            }
        except Exception as exc:
            # 降级：直接用原始 query，不中断主流程
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
            missing.append("destination（目的地）")
        if not start:
            missing.append("travel_start_date（开始日期）")
        if not end:
            missing.append("travel_end_date（结束日期）")

        days = 0
        if start and end:
            if end < start:
                missing.append("travel_end_date（结束日期早于开始日期）")
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

        # 历轮沟通记录：让 Reviewer 知道自己之前提过哪些紧急问题、是否已被修复
        dialogue_block = ""
        if state.planner_reviewer_dialogue:
            dialogue_text = "\n".join(state.planner_reviewer_dialogue)
            dialogue_block = (
                f"\n\n【历轮沟通记录（检查你之前标注的【紧急必须优先改】是否已被修复；"
                f"未修复则继续标注紧急，已修复则审查新问题）】\n{dialogue_text}"
            )

        prompt = (
            f"目的地：{state.destination}，共 {state.days} 天，每天上限 {state.max_per_day}。\n"
            f"用户游玩习惯：{state.habit_preference or '无'}"
            f"{_travel_dates_block(state)}\n"
            f"{weather_block}\n"
            f"候选景点池：\n{format_spots_for_llm(state.pois)}\n\n"
            f"待评审路线：\n{json.dumps(state.route, ensure_ascii=False)}\n\n"
            f"系统客观预检（请据此判断）：\n{facts}"
            f"{dialogue_block}\n\n请评审并给出结论。"
        )
        result: RouteReview = invoke_structured(llm, [("system", REVIEWER_SYSTEM), ("human", prompt)])
        approved = result.approved and not bad_unknown
        verdict  = "✅通过" if approved else "❌打回"
        note = f"[第{state.review_round}轮] Reviewer {verdict}（{result.score}分）：{result.route_modify_opinion[:50]}"

        # 追加本轮 Reviewer 记录到共享对话
        reviewer_line = (
            f"[第{state.review_round}轮] Reviewer {'通过' if approved else '打回'}"
            f"（{result.score}分）：{result.route_modify_opinion[:100] or '(无意见)'}"
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
    """reviewer 通过时进餐搜索；否则永远把球还给 planner（出口由 route_after_planner 控制）。"""
    if state.approved:
        return "meal_search"
    return "planner"


def route_after_planner(state: TravelPlanState) -> str:
    """planner 递增 review_round 后判定：超出上限则跳餐搜索（末轮 planner 已响应过），
    否则继续送 reviewer。"""
    if state.review_round > state.max_review_rounds:
        return "meal_search"
    return "reviewer"


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
            raw   = search_around_pois(center, api_key, types="餐饮服务", radius=1500, offset=20)
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
            """子串匹配 → 取评分最高，不做精确匹配（LLM 经常改写名称后缀）。"""
            if not name:
                return None
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
        # 达最大迭代轮数仍未通过时，透传 reviewer 最后一轮问题给前端
        "route_issues": state.reviewer_issues if not state.approved else [],
        "days": days_out,
    }
    return {"final_plan": final_plan, "history": state.history + ["finalize：已组装最终计划"]}
