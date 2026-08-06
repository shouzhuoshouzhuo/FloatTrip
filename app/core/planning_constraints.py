"""Canonical PlanningBrief constraints and memory projections.

This module is deliberately model-free.  It validates the durable shape shared
by the brief UI, immutable Run snapshots and the planning graph.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from app.core.travel_memory import FACT_CATEGORIES, POLARITIES


TRIP_CONSTRAINT_CATEGORIES = FACT_CATEGORIES - {"destination_history"}
LEGACY_CONSTRAINT_FIELDS = {
    "attraction_preference": "attraction_preference",
    "food_preference": "food_preference",
    "habit_preference": "travel_pace",
}


def _constraint_id(category: str, value: str, *, legacy_key: str = "") -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tripagent-brief:{legacy_key}:{category}:{value}"))


def normalize_trip_constraint(
    item: dict[str, Any], *, default_source: str = "conversation"
) -> dict[str, Any]:
    category = str(item.get("category") or "").strip()
    if category not in TRIP_CONSTRAINT_CATEGORIES:
        raise ValueError("invalid trip constraint category")
    value = str(item.get("value_text") or item.get("value") or "").strip()
    if not value or len(value) > 500:
        raise ValueError("trip constraint value must contain 1-500 characters")
    polarity = str(item.get("polarity") or "fact")
    if polarity not in POLARITIES:
        raise ValueError("invalid trip constraint polarity")
    source = str(item.get("source") or default_source)
    if source not in {"conversation", "manual"}:
        source = default_source
    evidence = sorted(
        {int(value) for value in (item.get("evidence_sequences") or []) if int(value) > 0}
    )
    return {
        "id": str(item.get("id") or uuid.uuid4()),
        "category": category,
        "value_text": value,
        "polarity": polarity,
        "source": source,
        "evidence_sequences": evidence,
    }


def normalize_brief_data(data: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(data or {})
    if "trip_budget" not in result and result.get("budget") is not None:
        result["trip_budget"] = result.get("budget")
    constraints: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in result.get("trip_constraints") or []:
        normalized = normalize_trip_constraint(dict(item))
        key = (
            normalized["category"],
            normalized["value_text"].casefold(),
            normalized["polarity"],
        )
        if key not in seen:
            seen.add(key)
            constraints.append(normalized)
    for field, category in LEGACY_CONSTRAINT_FIELDS.items():
        value = str(result.get(field) or "").strip()
        key = (category, value.casefold(), "prefer")
        if value and key not in seen:
            seen.add(key)
            constraints.append(
                {
                    "id": _constraint_id(category, value, legacy_key=field),
                    "category": category,
                    "value_text": value,
                    "polarity": "prefer",
                    "source": "conversation",
                    "evidence_sequences": [],
                }
            )
    result["trip_constraints"] = constraints
    result["excluded_memory_fact_ids"] = sorted(
        {str(value) for value in result.get("excluded_memory_fact_ids") or [] if value}
    )
    return result


def matching_fingerprint(data: dict[str, Any], revision: int, facts: list[dict[str, Any]]) -> str:
    relevant = normalize_brief_data(data)
    payload = {
        "destination": relevant.get("destination"),
        "trip_budget": relevant.get("trip_budget"),
        "trip_constraints": relevant.get("trip_constraints", []),
        "excluded_memory_fact_ids": relevant.get("excluded_memory_fact_ids", []),
        "revision": int(revision),
        "fact_ids": [fact.get("id") for fact in facts if fact.get("status") == "active"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _coverage(category: str, application_level: str) -> dict[str, Any]:
    stages = {
        "attraction_preference": ["attraction_search", "planner", "reviewer"],
        "food_preference": ["meal_search", "meal_recommend"],
        "dietary_requirement": ["meal_search", "meal_recommend"],
        "budget_style": ["attraction_search", "meal_recommend"],
        "travel_pace": ["planner", "reviewer", "spot_tips"],
        "schedule_preference": ["planner", "reviewer", "spot_tips"],
        "companion_context": ["planner", "reviewer", "spot_tips"],
        "transport_preference": ["planner", "reviewer"],
        "accessibility_need": ["planner", "reviewer", "spot_tips"],
        "accommodation_preference": ["finalize"],
        "other_travel_preference": ["planner", "finalize"],
        "destination_history": ["query_context"],
    }.get(category, ["planner"])
    if category in {"dietary_requirement", "accessibility_need"}:
        status = "unverified"
    elif category in {"accommodation_preference", "destination_history"} or application_level == "context_only":
        status = "advisory"
    else:
        status = "applied"
    return {"status": status, "stages": stages}


def build_brief_projection(
    data: dict[str, Any],
    *,
    revision: int,
    frozen_facts: list[dict[str, Any]],
    projection: dict[str, Any] | None,
    match_status: str = "none",
    error_code: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_brief_data(data)
    by_id = {
        str(fact.get("id")): fact
        for fact in frozen_facts
        if fact.get("status") == "active" and fact.get("id")
    }
    excluded = set(normalized["excluded_memory_fact_ids"])
    decisions = {
        str(item.get("fact_id")): item
        for item in (projection or {}).get("decisions", [])
        if item.get("decision") == "apply"
    }
    applied_facts: list[dict[str, Any]] = []
    excluded_facts: list[dict[str, Any]] = []
    effective = [dict(item) for item in normalized["trip_constraints"]]
    coverage: list[dict[str, Any]] = []
    for item in effective:
        detail = _coverage(item["category"], "hard" if item["category"] in {"dietary_requirement", "accessibility_need"} else "preference")
        coverage.append({"constraint_id": item["id"], "source": item["source"], "category": item["category"], **detail})
    for fact_id, decision in decisions.items():
        fact = by_id.get(fact_id)
        if not fact:
            continue
        projected = {
            "fact_id": fact_id,
            "category": fact["category"],
            "value_text": fact["value_text"],
            "polarity": fact["polarity"],
            "scope_type": fact.get("scope_type", "global"),
            "scope_key": fact.get("scope_key") or {},
            "application_level": decision.get("application_level", "preference"),
            "reason_code": decision.get("reason_code", "supports_current_trip"),
            "source": "long_term_memory",
        }
        if fact_id in excluded:
            excluded_facts.append(projected)
            continue
        applied_facts.append(projected)
        constraint = {
            "id": f"memory:{fact_id}",
            "fact_id": fact_id,
            "category": fact["category"],
            "value_text": fact["value_text"],
            "polarity": fact["polarity"],
            "source": "long_term_memory",
            "application_level": projected["application_level"],
        }
        effective.append(constraint)
        detail = _coverage(fact["category"], projected["application_level"])
        coverage.append({"constraint_id": constraint["id"], "fact_id": fact_id, "source": "long_term_memory", "category": fact["category"], **detail})
    # Excluded facts remain explainable even if the latest model no longer selected them.
    for fact_id in sorted(excluded):
        if fact_id in decisions or fact_id not in by_id:
            continue
        fact = by_id[fact_id]
        excluded_facts.append({
            "fact_id": fact_id, "category": fact["category"],
            "value_text": fact["value_text"], "polarity": fact["polarity"],
            "scope_type": fact.get("scope_type", "global"),
            "scope_key": fact.get("scope_key") or {}, "source": "long_term_memory",
        })
    return {
        "data": normalized,
        "memory_context": {
            "revision": int(revision),
            "status": match_status,
            "error_code": error_code,
            "applied_facts": applied_facts,
            "excluded_facts": excluded_facts,
        },
        "effective_constraints": effective,
        "constraint_coverage": coverage,
    }


def compatibility_preferences(constraints: list[dict[str, Any]]) -> dict[str, str]:
    buckets = {"attraction_preference": [], "food_preference": [], "habit_preference": []}
    for item in constraints:
        value = constraint_directive(item)
        if not value:
            continue
        category = item.get("category")
        if category == "attraction_preference":
            buckets["attraction_preference"].append(value)
        elif category in {"food_preference", "dietary_requirement"}:
            buckets["food_preference"].append(value)
        elif category in {"travel_pace", "schedule_preference", "companion_context", "transport_preference", "accessibility_need"}:
            buckets["habit_preference"].append(value)
    return {key: "；".join(dict.fromkeys(values)) for key, values in buckets.items()}


def constraint_directive(item: dict[str, Any]) -> str:
    value = str(item.get("value_text") or "").strip()
    if not value:
        return ""
    prefix = {
        "prefer": "优先考虑",
        "avoid": "必须避开",
        "require": "必须满足",
        "fact": "仅作背景",
    }.get(str(item.get("polarity") or "prefer"), "仅作背景")
    if item.get("application_level") == "context_only":
        prefix = "仅作背景"
    return f"{prefix}：{value}"


def constraints_for_prompt(constraints: list[dict[str, Any]]) -> str:
    if not constraints:
        return "（本次没有额外旅行约束）"
    return "\n".join(
        f"- [{item.get('category')}/{item.get('polarity')}/{item.get('source')}] {constraint_directive(item)}"
        for item in constraints
    )
