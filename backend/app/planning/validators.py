"""路线计划数据校验工具。"""

from __future__ import annotations

from typing import Any

from backend.app.planning.day_clustering import candidate_location


def validate_candidates_have_locations(candidates: list[dict[str, Any]]) -> list[str]:
    """检查候选景点是否带坐标，并返回非致命告警列表。"""
    warnings: list[str] = []
    for candidate in candidates:
        try:
            candidate_location(candidate)
        except ValueError as exc:
            warnings.append(str(exc))
    return warnings
