"""后端应用入口。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.planner import router as planner_router


app = FastAPI(title="FloatTrip Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8088",
        "http://localhost:8088",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(planner_router)


@app.get("/health")
def health() -> dict[str, str]:
    """功能：返回后端服务健康状态，供前端、本地调试和部署探针使用。

    参数：
        无。
    返回值：
        返回包含 status 字段的健康检查字典。
    """
    return {"status": "ok"}
