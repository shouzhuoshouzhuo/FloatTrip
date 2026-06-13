"""用户画像 API：查看 / 手动编辑偏好。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.core.auth import decode_token
from app.core.database import get_conn
from app.core.memory import get_user_profile, set_user_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileUpdate(BaseModel):
    attraction_prefs: list[str] = []
    food_prefs: list[str] = []
    habit_prefs: list[str] = []
    visited_destinations: list[str] = []


def _require_user(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(401, "token 无效或已过期")
    return user_id


def _profile_with_stats(user_id: str, conn) -> dict:
    profile = get_user_profile(user_id, conn)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM itineraries WHERE user_id=?", (user_id,)
    ).fetchone()
    profile["trip_count"] = row["n"] if row else 0
    return profile


@router.get("")
def get_profile(authorization: str | None = Header(default=None)):
    user_id = _require_user(authorization)
    with get_conn() as conn:
        return _profile_with_stats(user_id, conn)


@router.put("")
def update_profile(req: ProfileUpdate, authorization: str | None = Header(default=None)):
    user_id = _require_user(authorization)
    with get_conn() as conn:
        set_user_profile(user_id, req.model_dump(), conn)
        return _profile_with_stats(user_id, conn)
