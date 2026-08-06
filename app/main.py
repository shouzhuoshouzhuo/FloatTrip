"""FastAPI 应用入口。

路由：
  POST /api/plan/stream — SSE 流式规划（含多轮续接、修改规划、记忆注入）
  POST /api/plan        — 同步规划（向后兼容）
  POST /api/auth/*      — 注册 / 登录
  GET  /api/history     — 历史行程列表
  GET  /api/history/:id — 历史行程详情
  GET  /api/health      — 健康检查
  GET  /api/config      — 前端高德 JS Key
  GET  /                — 前端首页
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core.auth import decode_token
from app.core.database import get_conn, init_db
from app.core.env import load_local_env
from app.core.memory import (
    load_itinerary,
    save_itinerary,
    save_pending_modification,
)
from app.core.travel_memory import MemoryRepository
from app.core.thread_store import thread_store
from app.planning.graph import run_modification_stream
from app.planning.graph import run_stream as run_plan_stream
from app.api.auth_routes import router as auth_router
from app.api.history_routes import router as history_router
from app.api.profile_routes import router as profile_router
from app.api.plan_routes import router as plan_router
from app.api.sweep_routes import router as sweep_router
from app.api.runtime_routes import router as runtime_router
from app.runtime.container import start_runtime, stop_runtime, chat_service
from app.runtime.container import manager as runtime_manager
from app.runtime.container import scheduler as runtime_scheduler
from app.runtime.compat import (
    create_legacy_run, legacy_events, legacy_parent_constraint_snapshot,
    resume_legacy_run,
)

load_local_env()
init_db()

# ─── 应用 ────────────────────────────────────────────────────

app = FastAPI(title="AI 旅游规划助手", version="0.1.0")

app.include_router(auth_router)
app.include_router(history_router)
app.include_router(profile_router)
app.include_router(plan_router)
app.include_router(sweep_router)
app.include_router(runtime_router)


@app.on_event("startup")
async def start_agent_runtime():
    await start_runtime()


@app.on_event("shutdown")
async def stop_agent_runtime():
    await stop_runtime()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 辅助：从 Authorization header 提取 user_id（强制登录）────

def _get_required_user_id(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录后再使用规划功能")
    user_id = decode_token(auth[7:])
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user_id


# ─── API 路由 ─────────────────────────────────────────────────

class PlanRequest(BaseModel):
    query: str
    max_per_day: int = 5
    min_rating: float = 4.5
    max_spots: int = 30
    max_review_rounds: int = 3
    # 多轮续接
    thread_id: Optional[str] = None
    # 修改规划
    plan_id: Optional[str] = None
    modification_notes: Optional[str] = None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    """暴露前端地图所需的高德 JS API 密钥（不含敏感 REST Key）。"""
    return {
        "amap_js_key":           os.getenv("AMAP_JS_KEY", ""),
        "amap_js_security_code": os.getenv("AMAP_JS_SECURITY_CODE", ""),
    }




@app.post("/api/plan/stream")
async def create_plan_stream(req: PlanRequest, request: Request):
    """分阶段 SSE：逐节点推送进度，末帧推送完整 plan。

    扩展能力：
    - thread_id: 多轮续接（missing_fields 后补充信息）
    - plan_id + modification_notes: 修改已有行程（走 checkpoint 迷你图）
    - Authorization: 登录用户自动保存行程 + 记忆提取 + checkpoint 存储
    """
    user_id = _get_required_user_id(request)

    overrides = dict(
        max_per_day=req.max_per_day,
        min_rating=req.min_rating,
        max_spots=req.max_spots,
        max_review_rounds=req.max_review_rounds,
    )

    try:
        if req.thread_id:
            run = await resume_legacy_run(
                runtime_manager,
                runtime_scheduler,
                user_id=user_id,
                run_id=req.thread_id,
                value=req.query,
            )
        else:
            inherited = (
                await asyncio.to_thread(
                    legacy_parent_constraint_snapshot,
                    runtime_manager,
                    user_id,
                    req.plan_id,
                )
                if req.plan_id and req.modification_notes else None
            )
            if inherited:
                projected_snapshot = {**inherited, "constraint_snapshot_source": "parent_run"}
            else:
                revision, facts = await asyncio.to_thread(MemoryRepository().snapshot, user_id)
                projected_snapshot = await chat_service.planning_memory.project_snapshot(
                    {"query": req.query},
                    revision=revision,
                    facts=facts,
                    fallback_source=("latest_profile_for_legacy_itinerary" if req.plan_id else "latest_profile"),
                )
                projected_snapshot["memory_profile_revision"] = revision
                projected_snapshot["memory_profile_snapshot"] = facts
            run = await asyncio.to_thread(
                create_legacy_run,
                runtime_manager,
                user_id=user_id,
                query=req.query,
                overrides=overrides,
                plan_id=req.plan_id,
                modification_notes=req.modification_notes,
                projected_snapshot=projected_snapshot,
            )
            runtime_scheduler.notify()

        async def runtime_compat_stream():
            async for event in legacy_events(runtime_manager, run["id"]):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            runtime_compat_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    except (ValueError, LookupError):
        # Compatibility fallback for pre-Runtime thread/pending records.
        pass

    # ── 1. 多轮续接：合并原始 query ──────────────────────────
    if req.thread_id:
        original = thread_store.get(req.thread_id)
        if original:
            query = f"{original}，{req.query}"
            thread_store.delete(req.thread_id)
        else:
            query = req.query
    else:
        query = req.query

    # ── 2. 基础 overrides ────────────────────────────────────
    parent_plan_id = req.plan_id
    # ── 3. memory_writer closure（供 finalize 节点写入） ──────
    saved_plan_id: list[str] = []  # 用列表传引用

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
                user_id, final_plan, query, conn,
                parent_id=parent_plan_id,
                modification_notes=req.modification_notes,
                planner_state=planner_checkpoint,
            )
        saved_plan_id.append(pid)

    # ── 4. 修改模式：走 checkpoint 迷你图 ────────────────────
    if req.plan_id and req.modification_notes:
        with get_conn() as conn:
            data = load_itinerary(req.plan_id, conn)
        checkpoint = data["planner_state"] if data else None

        if checkpoint:
            async def gen_modification():
                try:
                    async for ev in run_modification_stream(
                        checkpoint,
                        req.modification_notes,
                        memory_writer=memory_writer,
                        **overrides,
                    ):
                        if ev.get("type") == "modification_warning":
                            # 存 pending 状态到 DB，用 pending_id 替换 pending_state
                            pending_state = ev.pop("pending_state", {})
                            if user_id:
                                with get_conn() as conn:
                                    pid = save_pending_modification(user_id, pending_state, conn)
                                ev["pending_id"] = pid
                            ev["parent_plan_id"] = parent_plan_id
                        elif ev.get("type") == "result" and ev.get("success") and saved_plan_id:
                            ev["plan_id"] = saved_plan_id[0]
                        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except Exception as e:  # noqa: BLE001
                    err = {"type": "error", "message": str(e)}
                    yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                gen_modification(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
            )
        # 无 checkpoint（旧数据）→ 降级走普通流程，带 modification_notes
        overrides["modification_notes"] = req.modification_notes
        if parent_plan_id:
            overrides["parent_plan_id"] = parent_plan_id

    # ── 5. 记忆注入：读取用户历史偏好 ────────────────────────
    profile_hint = ""
    if user_id:
        _revision, facts = MemoryRepository().snapshot(user_id)
        profile_hint = MemoryRepository.format_for_prompt(facts)

    # ── 6. 普通规划流 ─────────────────────────────────────────
    async def gen():
        try:
            async for ev in run_plan_stream(
                query,
                profile_hint=profile_hint,
                memory_writer=memory_writer,
                user_id=user_id,
                **overrides,
            ):
                # missing_fields 时追加 thread_id 供前端续接
                if ev.get("type") == "result" and not ev.get("success") and ev.get("missing_fields"):
                    ev["thread_id"] = thread_store.create(query)
                # 成功时追加 plan_id，并触发异步画像更新（只看 raw query，不看改写后的）
                if ev.get("type") == "result" and ev.get("success") and saved_plan_id:
                    ev["plan_id"] = saved_plan_id[0]
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
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


# ─── 静态文件（前端）—— 必须在 API 路由之后挂载 ─────────────

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _frontend_index_response() -> FileResponse:
    # 前端没有构建产物指纹；HTML 必须每次取新版本，否则它会继续引用旧的
    # ChatState/pages 脚本并静默丢弃服务端新增的 PlanningBrief 字段。
    return FileResponse(
        _FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


class RevalidatingStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


@app.get("/")
def index():
    return _frontend_index_response()


@app.get("/history")
def history_page():
    return _frontend_index_response()


@app.get("/profile")
def profile_page():
    return _frontend_index_response()


app.mount("/", RevalidatingStaticFiles(directory=str(_FRONTEND_DIR)), name="frontend")
