"""历史行程 API。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.core.auth import decode_token
from app.core.database import get_conn
from app.core.memory import list_itineraries, load_itinerary

router = APIRouter(prefix="/api/history", tags=["history"])


def _require_user(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(401, "token 无效或已过期")
    return user_id


@router.get("")
def get_history(authorization: str | None = Header(default=None)):
    user_id = _require_user(authorization)
    with get_conn() as conn:
        items = list_itineraries(user_id, conn)
    return items


@router.get("/{plan_id}")
def get_itinerary(plan_id: str, authorization: str | None = Header(default=None)):
    user_id = _require_user(authorization)
    with get_conn() as conn:
        # 验证该行程属于该用户
        row = conn.execute(
            "SELECT user_id FROM itineraries WHERE id=?", (plan_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "行程不存在")
        if row["user_id"] != user_id:
            raise HTTPException(403, "无权访问")
        data = load_itinerary(plan_id, conn)
    return data
