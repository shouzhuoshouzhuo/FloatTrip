"""LangGraph 节点函数：意图识别、景点搜索、规划、评审、餐饮搜索、推荐、finalize。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from app.llm.deepseek import build_structured_deepseek
from app.providers.amap.poi import search_around_pois
from app.planning.schemas import (
    DayMealPick,
    IntentExtraction,
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
    open_time_violations,
    parse_iso_date,
    restaurant_to_dict,
    spot_location_map,
    unknown_spots,
)
from app.planning.prompts import (
    INTENT_SYSTEM,
    MEAL_SYSTEM,
    PLANNER_SYSTEM,
    REVIEWER_SYSTEM,
    WEEKDAYS,
)

from langgraph.graph import END


# ─── 意图识别 ────────────────────────────────────────────────

def make_intent_node(model_name: str | None):
    llm = build_structured_deepseek(IntentExtraction, model=model_name, temperature=0)

    def intent(state: TravelPlanState) -> dict[str, Any]:
        today = date.today()
        system = INTENT_SYSTEM.format(today=today.isoformat(), weekday=WEEKDAYS[today.weekday()])
        result: IntentExtraction = invoke_structured(
            llm, [("system", system), ("human", state.query)]
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
    return END if state.missing_fields else "attraction_search"


# ─── 高德景点搜索 ─────────────────────────────────────────────

def attraction_search_node(state: TravelPlanState) -> dict[str, Any]:
    api_key = amap_key()
    spots = fetch_city_spots(state.destination or "", api_key, max_spots=state.max_spots)
    kept, _ = filter_by_rating(spots, state.min_rating)
    note = f"高德景点搜索：抓取 {len(spots)} 个，rating≥{state.min_rating} 保留 {len(kept)} 个"
    return {"pois": kept, "history": state.history + [note]}


# ─── Planner ─────────────────────────────────────────────────

def make_planner_node(model_name: str | None):
    llm = build_structured_deepseek(TravelRoute, model=model_name, temperature=0.3)

    def planner(state: TravelPlanState) -> dict[str, Any]:
        cand_text = format_spots_for_llm(state.pois)
        feedback = ""
        if state.route and state.route_modify_opinion:
            feedback = (
                f"\n\n上一版路线：\n{json.dumps(state.route, ensure_ascii=False)}\n\n"
                f"评审修改意见（请据此修订）：\n{state.route_modify_opinion}"
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

        prompt = (
            f"用户需求：{state.query}\n"
            f"目的地：{state.destination}\n旅行天数：{state.days} 天\n"
            f"每天景点数上限：{state.max_per_day}\n"
            f"景点偏好：{state.attraction_preference or '无'}\n"
            f"游玩习惯/节奏：{state.habit_preference or '无'}"
            f"{weather_block}\n\n"
            f"候选景点池（共 {len(state.pois)} 个）：\n{cand_text}"
            f"{feedback}"
            f"{dialogue_block}\n\n"
            f"请给出 {state.days} 天带时刻表的逐天景点安排。"
        )
        result: TravelRoute = invoke_structured(llm, [("system", PLANNER_SYSTEM), ("human", prompt)])
        route = [d.model_dump() for d in result.days]
        rnd = state.review_round + 1
        note = f"[第{rnd}轮] Planner 出稿：{result.notes or '(无说明)'}"
        planner_line = f"[第{rnd}轮] Planner：{result.notes or '(无说明)'}"
        return {
            "route": route,
            "review_round": rnd,
            "history": state.history + [note],
            "planner_reviewer_dialogue": state.planner_reviewer_dialogue + [planner_line],
        }

    return planner


# ─── Reviewer ────────────────────────────────────────────────

def make_reviewer_node(model_name: str | None):
    llm = build_structured_deepseek(RouteReview, model=model_name, temperature=0)

    def reviewer(state: TravelPlanState) -> dict[str, Any]:
        proximity  = day_proximity_report(state.route, state.pois)
        bad_open   = open_time_violations(state.route, state.pois)
        bad_unknown = unknown_spots(state.route, state.pois)

        facts = (
            f"每天地理跨度：\n{proximity}\n\n"
            f"开放时间冲突：{('；'.join(bad_open)) or '无'}\n"
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
        issues_str = "；".join(result.issues[:3]) if result.issues else result.route_modify_opinion[:80]
        reviewer_line = (
            f"[第{state.review_round}轮] Reviewer {'通过' if approved else '打回'}"
            f"（{result.score}分）：{issues_str or '(无意见)'}"
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
    if state.approved or state.review_round >= state.max_review_rounds:
        return "meal_search"
    return "planner"


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
            raw   = search_around_pois("餐厅", center, api_key, radius=1500, offset=20)
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

        pick_map = {p.day: p for p in day_picks}
        meals: list[dict[str, Any]] = []
        for entry in state.meal_candidates:
            pick         = pick_map.get(entry["day"])
            lunch_cands  = {c["name"]: c for c in entry["lunch"].get("candidates", [])}
            dinner_cands = {c["name"]: c for c in entry["dinner"].get("candidates", [])}
            lunch_info   = lunch_cands.get(pick.lunch_name)  if pick else None
            dinner_info  = dinner_cands.get(pick.dinner_name) if pick else None

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

def finalize_node(state: TravelPlanState) -> dict[str, Any]:
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
