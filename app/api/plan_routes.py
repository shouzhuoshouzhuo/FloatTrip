"""规划相关的辅助路由（confirm_modification、optimize_day 等）。"""

from __future__ import annotations

import json
from itertools import permutations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.auth import decode_token
from app.core.cache import POI_TTL, get_cached, poi_cache_key, set_cached
from app.core.database import get_conn
from app.core.memory import (
    delete_pending_modification,
    extract_and_update_preferences,
    load_itinerary,
    load_pending_modification,
    save_itinerary,
    update_plan_json,
)
from app.planning.graph import run_confirm_stream
from app.planning.helpers import amap_key, haversine_km, restaurant_to_dict
from app.providers.amap.poi import (
    ATTRACTION_TYPE,
    normalize_address,
    poi_to_spot,
    search_city_pois,
)
from pydantic import BaseModel

router = APIRouter()


# ─── 路线优化（暴力枚举最短路径）────────────────────────────


def _path_km(spots: list[dict]) -> float:
    """按顺序计算景点列表的总行驶路程（km）。"""
    total = 0.0
    for i in range(len(spots) - 1):
        a = spots[i].get("location")
        b = spots[i + 1].get("location")
        if a and b:
            total += haversine_km(a, b)
    return total


def _optimize_day_timeline(timeline: list[dict]) -> tuple[list[dict], float, float]:
    """
    对单天 timeline 做路线优化：
    - 暴力枚举 daytime attractions 的全排列（evening 景点固定末位）
    - meals 保持原始相对位置（排在第几个 daytime 景点之后）并参与路程计算
      → 原始排列是候选项之一，保证 best_km ≤ original_km，不会越优化越差
    - 重算 dist_from_prev_km
    返回 (optimized_timeline, original_km, optimized_km)
    """
    daytime = [t for t in timeline if t["type"] == "attraction" and t.get("period") != "evening"]
    evening = [t for t in timeline if t["type"] == "attraction" and t.get("period") == "evening"]
    lunch   = next((t for t in timeline if t["type"] == "lunch"), None)
    dinner  = next((t for t in timeline if t["type"] == "dinner"), None)

    # 景点不足两个，无需枚举
    if len(daytime) < 2:
        return timeline, _path_km(timeline), _path_km(timeline)

    # ── 记录午/晚餐在原始 timeline 中的相对位置 ─────────────────
    # lunch_after = 在它之前已出现的 daytime 景点数（0 = 排在第 1 个景点之前）
    lunch_after = dinner_after = len(daytime)   # 默认：排在所有 daytime 景点之后
    daytime_seen = 0
    for item in timeline:
        if item["type"] == "attraction" and item.get("period") != "evening":
            daytime_seen += 1
        elif item["type"] == "lunch" and lunch_after == len(daytime):
            lunch_after = daytime_seen
        elif item["type"] == "dinner" and dinner_after == len(daytime):
            dinner_after = daytime_seen

    def build_sequence(perm: list[dict]) -> list[dict]:
        """按原始相对位置插入 lunch/dinner，构建完整序列（含 evening）。"""
        seq: list[dict] = []
        lunch_inserted = dinner_inserted = False

        # 餐厅排在第 1 个景点之前（*_after == 0）
        if lunch and lunch_after == 0:
            seq.append(lunch)
            lunch_inserted = True
        if dinner and dinner_after == 0:
            seq.append(dinner)
            dinner_inserted = True

        for i, spot in enumerate(perm):
            seq.append(spot)
            if lunch and not lunch_inserted and i + 1 == lunch_after:
                seq.append(lunch)
                lunch_inserted = True
            if dinner and not dinner_inserted and i + 1 == dinner_after:
                seq.append(dinner)
                dinner_inserted = True

        seq.extend(evening)

        # 未插入的餐厅补到末尾
        if lunch and not lunch_inserted:
            seq.append(lunch)
        if dinner and not dinner_inserted:
            seq.append(dinner)

        return seq

    # 原始路程（含餐厅地理位置）
    original_km = _path_km(build_sequence(daytime))

    # 暴力枚举 daytime 全排列，以含餐厅的完整序列计算路程
    # 原始排列也在候选内，故 best_km ≤ original_km 恒成立
    best_perm = list(daytime)
    best_km   = original_km
    for perm in permutations(daytime):
        km = _path_km(build_sequence(list(perm)))
        if km < best_km - 1e-9:
            best_km = km
            best_perm = list(perm)

    # 按最优排列构建结果 timeline（各项做浅拷贝）
    result: list[dict] = [dict(item) for item in build_sequence(best_perm)]

    # ── 重算 dist_from_prev_km ──────────────────────────────────
    for i in range(len(result)):
        if i == 0:
            result[i].pop("dist_from_prev_km", None)
        else:
            prev_loc = result[i - 1].get("location")
            cur_loc  = result[i].get("location")
            if prev_loc and cur_loc:
                result[i]["dist_from_prev_km"] = round(haversine_km(prev_loc, cur_loc), 2)
            else:
                result[i].pop("dist_from_prev_km", None)

    # ── 按位置交换时段：原 daytime 第 i 个时段赋给优化后第 i 个 daytime 景点 ──
    # evening 景点和 meals 保留原始时间不动
    time_slots = [
        {"start_time": t.get("start_time"), "end_time": t.get("end_time"), "period": t.get("period")}
        for t in timeline
        if t["type"] == "attraction" and t.get("period") != "evening"
    ]
    slot_idx = 0
    for item in result:
        if item["type"] == "attraction" and item.get("period") != "evening":
            if slot_idx < len(time_slots):
                item["start_time"] = time_slots[slot_idx]["start_time"]
                item["end_time"]   = time_slots[slot_idx]["end_time"]
                item["period"]     = time_slots[slot_idx]["period"]
                slot_idx += 1

    return result, original_km, best_km


class OptimizeDayRequest(BaseModel):
    plan_id: str
    day: int   # 1-based，第几天


@router.post("/api/plan/optimize_day")
def optimize_day(req: OptimizeDayRequest, authorization: str | None = Header(default=None)):
    """对行程中某一天的景点顺序做暴力枚举最优化（最短路程），evening 景点固定末位。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效或已过期")

    with get_conn() as conn:
        # 校验所有权
        row = conn.execute(
            "SELECT user_id FROM itineraries WHERE id=?", (req.plan_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="行程不存在")
        if row["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="无权访问")

        data = load_itinerary(req.plan_id, conn)

    plan = data["plan"]
    days = plan.get("days", [])

    # 找对应天（day 字段 1-based）
    day_obj = next((d for d in days if d.get("day") == req.day), None)
    if not day_obj:
        raise HTTPException(status_code=400, detail=f"第 {req.day} 天不存在")

    timeline = day_obj.get("timeline", [])
    optimized_timeline, original_km, optimized_km = _optimize_day_timeline(timeline)

    # 原地更新 plan 并写回 DB
    day_obj["timeline"] = optimized_timeline
    with get_conn() as conn:
        ok = update_plan_json(req.plan_id, user_id, plan, conn)
    if not ok:
        raise HTTPException(status_code=500, detail="保存失败")

    return {
        "optimized_day": day_obj,
        "original_km":   round(original_km, 2),
        "optimized_km":  round(optimized_km, 2),
        "improved":      optimized_km < original_km - 0.05,
    }


class RevertDayRequest(BaseModel):
    plan_id: str
    day: int            # 1-based
    original_timeline: list[dict]


@router.post("/api/plan/revert_day")
def revert_day(req: RevertDayRequest, authorization: str | None = Header(default=None)):
    """将某天路线回退到优化前的顺序（前端传入原始 timeline）。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效或已过期")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM itineraries WHERE id=?", (req.plan_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="行程不存在")
        if row["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="无权访问")

        data = load_itinerary(req.plan_id, conn)

    plan = data["plan"]
    day_obj = next((d for d in plan.get("days", []) if d.get("day") == req.day), None)
    if not day_obj:
        raise HTTPException(status_code=400, detail=f"第 {req.day} 天不存在")

    day_obj["timeline"] = req.original_timeline
    with get_conn() as conn:
        ok = update_plan_json(req.plan_id, user_id, plan, conn)
    if not ok:
        raise HTTPException(status_code=500, detail="保存失败")

    return {"reverted_day": day_obj}


def _get_user_id(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return decode_token(auth[7:])


class ConfirmModificationRequest(BaseModel):
    pending_id: str
    parent_plan_id: str | None = None


@router.post("/api/plan/confirm_modification")
async def confirm_modification(req: ConfirmModificationRequest, request: Request):
    """用户确认有顾虑的修改意见后，续跑 meal_search → finalize 并返回 SSE。"""
    user_id = _get_user_id(request)
    if not user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="需要登录")

    # 加载 pending 状态
    with get_conn() as conn:
        pending = load_pending_modification(req.pending_id, conn)

    if not pending or pending["user_id"] != user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="修改状态不存在或已过期")

    pending_state = pending["state"]
    saved_plan_id: list[str] = []
    parent_plan_id = req.parent_plan_id

    def memory_writer(final_plan: dict, state) -> None:
        planner_checkpoint = {
            "route": state.route,
            "pois":  state.pois,
            "planner_reviewer_dialogue": state.planner_reviewer_dialogue,
            "destination": str(state.destination or ""),
            "travel_start_date": str(state.travel_start_date or ""),
            "travel_end_date":   str(state.travel_end_date or ""),
            "days": state.days,
            "attraction_preference": state.attraction_preference,
            "food_preference":       state.food_preference,
            "habit_preference":      state.habit_preference,
            "weather_forecast": state.weather_forecast,
            "weather_note":     state.weather_note,
            "max_per_day":      state.max_per_day,
            "query":            state.query,
        }
        with get_conn() as conn:
            pid = save_itinerary(
                user_id, final_plan, pending_state.get("query", ""),
                conn,
                parent_id=parent_plan_id,
                planner_state=planner_checkpoint,
            )
            extract_and_update_preferences(user_id, final_plan, conn)
            # 确认后删除 pending 记录
            delete_pending_modification(req.pending_id, conn)
        saved_plan_id.append(pid)

    async def gen():
        try:
            async for ev in run_confirm_stream(
                pending_state,
                memory_writer=memory_writer,
            ):
                if ev.get("type") == "result" and ev.get("success") and saved_plan_id:
                    ev["plan_id"] = saved_plan_id[0]
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─── 手动编辑：POI 搜索代理 ──────────────────────────────────


@router.get("/api/poi/search")
def poi_search(
    city: str,
    kw: str,
    kind: str = "attraction",
    authorization: str | None = Header(default=None),
):
    """手动换点/加点的搜索代理：高德 Key 不出服务端，结果走 Redis 缓存。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    if not decode_token(authorization[7:]):
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    if kind not in ("attraction", "restaurant"):
        raise HTTPException(status_code=400, detail="kind 须为 attraction 或 restaurant")

    # 输入防御：清洗 city/kw 并检查长度
    city = city.strip()
    kw = kw.strip().replace("\n", "").replace("\r", "").replace("\x00", "")
    if not city or not kw:
        raise HTTPException(status_code=400, detail="city 和 kw 不能为空")
    if len(city) > 50 or len(kw) > 100:
        raise HTTPException(status_code=400, detail="搜索词过长")

    cache_key = poi_cache_key(city, f"manual:{kind}:{kw}")
    cached = get_cached(cache_key)
    if cached is not None:
        return {"results": cached}

    types = ATTRACTION_TYPE if kind == "attraction" else "餐饮服务"
    try:
        raw = search_city_pois(city, amap_key(), keywords=kw, types=types, offset=8)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    results: list[dict] = []
    for poi in raw:
        parsed = poi_to_spot(poi) if kind == "attraction" else restaurant_to_dict(poi)
        if not parsed:
            continue
        if kind == "attraction":
            # poi_to_spot 不含地址，搜索结果需要地址帮用户分辨同名地点
            parsed["address"] = normalize_address(poi.get("address"))
        results.append(parsed)

    set_cached(cache_key, results, POI_TTL)
    return {"results": results}


# ─── 手动编辑：保存逐天 timeline ─────────────────────────────────


def _valid_location(loc) -> bool:
    """location 必须是含数值 lat/lng 的 dict，残缺对象不参与距离计算。"""
    return (
        isinstance(loc, dict)
        and isinstance(loc.get("lat"), (int, float))
        and isinstance(loc.get("lng"), (int, float))
    )


def _recalc_dists(timeline: list[dict]) -> None:
    """服务端重算相邻条目距离，不信任前端传入的 dist_from_prev_km。"""
    for i, item in enumerate(timeline):
        if i == 0:
            item.pop("dist_from_prev_km", None)
            continue
        prev_loc = timeline[i - 1].get("location")
        cur_loc = item.get("location")
        if _valid_location(prev_loc) and _valid_location(cur_loc):
            item["dist_from_prev_km"] = round(haversine_km(prev_loc, cur_loc), 2)
        else:
            item.pop("dist_from_prev_km", None)


class TimelineDayPayload(BaseModel):
    day: int                  # 1-based
    timeline: list[dict]


class SaveTimelineRequest(BaseModel):
    days: list[TimelineDayPayload]


@router.put("/api/plan/{plan_id}/timeline")
def save_timeline(
    plan_id: str,
    req: SaveTimelineRequest,
    authorization: str | None = Header(default=None),
):
    """保存手动编辑后的逐天 timeline。只合并 timeline，不允许前端覆盖 plan 其他字段。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效或已过期")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM itineraries WHERE id=?", (plan_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="行程不存在")
        if row["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="无权访问")
        data = load_itinerary(plan_id, conn)

    plan = data["plan"]
    day_by_no = {d.get("day"): d for d in plan.get("days", [])}
    for payload in req.days:
        day_obj = day_by_no.get(payload.day)
        if not day_obj:
            raise HTTPException(status_code=400, detail=f"第 {payload.day} 天不存在")
        for item in payload.timeline:
            if not isinstance(item, dict) or not item.get("type"):
                raise HTTPException(status_code=422, detail="timeline 条目缺少 type")
            if item["type"] == "attraction" and not item.get("name"):
                raise HTTPException(status_code=422, detail="景点条目缺少 name")
        _recalc_dists(payload.timeline)
        day_obj["timeline"] = payload.timeline

    with get_conn() as conn:
        ok = update_plan_json(plan_id, user_id, plan, conn)
    if not ok:
        raise HTTPException(status_code=500, detail="保存失败")

    return {"plan": plan}
