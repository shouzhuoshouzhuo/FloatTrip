"""用户注册 / 登录接口。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.auth import create_token, hash_password, verify_password
from app.core.database import get_conn

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(req: AuthRequest):
    if not req.username.strip() or not req.password:
        raise HTTPException(400, "用户名和密码不能为空")
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?,?,?,?)",
                (user_id, req.username.strip(), hash_password(req.password), now),
            )
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(409, "用户名已存在")
        raise HTTPException(500, "注册失败")
    return {"user_id": user_id, "token": create_token(user_id), "username": req.username.strip()}


@router.post("/login")
def login(req: AuthRequest):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username=?",
            (req.username.strip(),),
        ).fetchone()
    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    return {"user_id": row["id"], "token": create_token(row["id"]), "username": req.username.strip()}
