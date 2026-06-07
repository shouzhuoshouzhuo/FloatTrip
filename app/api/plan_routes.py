"""规划相关的辅助路由（confirm_modification 等）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.auth import decode_token
from app.core.database import get_conn
from app.core.memory import (
    delete_pending_modification,
    extract_and_update_preferences,
    load_pending_modification,
    save_itinerary,
)
from app.planning.graph import run_confirm_stream
from pydantic import BaseModel

router = APIRouter()


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
