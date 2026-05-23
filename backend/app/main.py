"""后端应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.planner import router as planner_router


app = FastAPI(title="FloatTrip Backend", version="0.1.0")
app.include_router(planner_router)


@app.get("/health")
def health() -> dict[str, str]:
    """返回后端服务健康状态，供前端、本地调试和部署探针使用。"""
    return {"status": "ok"}
