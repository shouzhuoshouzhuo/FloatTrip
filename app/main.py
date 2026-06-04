"""FastAPI 应用入口。

路由：
  POST /api/plan    — 调用 LangGraph 旅游规划流水线
  GET  /api/health  — 健康检查
  GET  /            — 前端首页
  /*               — 前端静态文件
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.planning.graph import run as run_plan


# ─── 应用 ────────────────────────────────────────────────────

app = FastAPI(title="AI 旅游规划助手", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── API 路由 ─────────────────────────────────────────────────

class PlanRequest(BaseModel):
    query: str
    max_per_day: int = 3
    min_rating: float = 4.5
    max_spots: int = 30
    max_review_rounds: int = 3


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/plan")
def create_plan(req: PlanRequest):
    """调用 LangGraph 多 Agent 规划流水线（同步路由，FastAPI 自动放线程池）。"""
    state = run_plan(
        req.query,
        max_per_day=req.max_per_day,
        min_rating=req.min_rating,
        max_spots=req.max_spots,
        max_review_rounds=req.max_review_rounds,
    )
    success = not bool(state.missing_fields) and state.final_plan is not None
    return {
        "success": success,
        "missing_fields": state.missing_fields,
        "history": state.history,
        "plan": state.final_plan if success else None,
    }


# ─── 静态文件（前端）—— 必须在 API 路由之后挂载 ─────────────

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
def index():
    return FileResponse(_FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR)), name="frontend")
