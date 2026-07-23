"""Shared PlanningBrief readiness rules.

The chat graph and persistence layer both use these pure helpers so a brief
cannot be presented as ready when the formal planning graph would immediately
interrupt for missing calendar dates.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def required_brief_fields(data: dict[str, Any]) -> list[str]:
    """Return missing or invalid fields required before formal planning."""
    missing: list[str] = []
    if not str(data.get("destination") or "").strip():
        missing.append("destination")

    start = _iso_date(data.get("start_date"))
    end = _iso_date(data.get("end_date"))
    if start is None:
        missing.append("start_date")
    if end is None:
        missing.append("end_date")
    if start is not None and end is not None and end < start:
        missing.append("date_range")
    return missing


def merged_brief_data(
    brief: dict[str, Any] | None,
    patch: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge the persisted brief data with fields extracted in this Chat turn."""
    data = dict((brief or {}).get("data") or {})
    data.update(
        {
            key: value
            for key, value in (patch or {}).items()
            if value is not None
        }
    )
    return data
