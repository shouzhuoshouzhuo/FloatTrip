"""Sweep 评测结果预览接口（只读）。

GET /api/sweep/list  — 列出 sweep_results/ 下所有 JSONL 文件及其 trial 摘要
GET /api/sweep/trial — 返回指定文件第 idx 条 trial 的完整数据
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

SWEEP_DIR = (Path(__file__).resolve().parent.parent.parent
             / "tests" / "eval" / "sweep_results")

router = APIRouter(prefix="/api/sweep", tags=["sweep"])


@router.get("/list")
def list_sweep_files():
    """列出所有 sweep JSONL 文件，按时间倒序，附带各条 trial 摘要。"""
    if not SWEEP_DIR.exists():
        return []
    files = []
    for f in sorted(SWEEP_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        trials: list[dict] = []
        try:
            with f.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    r = json.loads(line)
                    trials.append({
                        "idx":       i,
                        "dest":      r.get("dest", "?"),
                        "pref":      r.get("pref", "?"),
                        "pass":      bool(r.get("overall_pass")),
                        "crash":     bool(r.get("crash")),
                        "elapsed_s": r.get("elapsed_s"),
                    })
        except Exception:
            pass
        files.append({"file": f.name, "trials": trials})
    return files


@router.get("/trial")
def get_sweep_trial(file: str = Query(...), idx: int = Query(0)):
    """返回指定 JSONL 文件第 idx 条 trial 的完整数据。"""
    # 路径穿越防护
    safe = (SWEEP_DIR / file).resolve()
    if not str(safe).startswith(str(SWEEP_DIR.resolve())):
        raise HTTPException(status_code=400, detail="invalid file path")
    if not safe.exists():
        raise HTTPException(status_code=404, detail="file not found")

    trials: list[dict] = []
    with safe.open(encoding="utf-8") as fh:
        for line in fh:
            trials.append(json.loads(line))

    if idx >= len(trials):
        raise HTTPException(status_code=404, detail=f"trial {idx} not found")

    r = trials[idx]
    return {
        "dest":              r.get("dest"),
        "pref":              r.get("pref"),
        "days":              r.get("days"),
        "query":             r.get("query"),
        "crash":             bool(r.get("crash")),
        "crash_reason":      r.get("crash_reason"),
        "crash_detail":      r.get("crash_detail"),
        "overall_pass":      bool(r.get("overall_pass")),
        "review_rounds":     r.get("review_rounds", 0),
        "time_check_rounds": r.get("time_check_rounds", 0),
        "elapsed_s":         r.get("elapsed_s"),
        "has_weather":       bool(r.get("has_weather")),
        "code":              r.get("code"),
        "profile_update":    r.get("profile_update"),
        "transcript":        r.get("transcript"),
        "final_plan":        r.get("final_plan"),
    }
