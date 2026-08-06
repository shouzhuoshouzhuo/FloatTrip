"""Adapter from immutable travel-plan Run snapshots to TravelPlanState."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.database import get_conn
from app.core.memory import (
    load_itinerary,
    save_itinerary,
)
from app.core.travel_memory import MemoryRepository
from app.core.planning_constraints import constraints_for_prompt
from app.planning.schemas import TravelPlanState
from app.runtime.manager import RunManager


def snapshot_to_state(snapshot: dict[str, Any]) -> TravelPlanState:
    allowed = set(TravelPlanState.model_fields)
    values = {key: value for key, value in snapshot.items() if key in allowed}
    values.setdefault("travel_start_date", snapshot.get("start_date"))
    values.setdefault("travel_end_date", snapshot.get("end_date"))
    if not values.get("query"):
        destination = values.get("destination") or snapshot.get("destination") or ""
        days = values.get("days") or snapshot.get("days") or ""
        values["query"] = f"{destination}{days}日游".strip()
    return TravelPlanState(**values)


async def planning_run_to_state(run: dict[str, Any]) -> TravelPlanState:
    facts = run["request_snapshot"].get("memory_profile_snapshot")
    if facts is None:
        _revision, facts = await asyncio.to_thread(
            MemoryRepository().snapshot, run["user_id"]
        )
    effective = run["request_snapshot"].get("effective_constraints") or []
    snapshot = {
        **run["request_snapshot"],
        "profile_hint": (
            constraints_for_prompt(effective)
            if effective else MemoryRepository.format_for_prompt(facts)
        ) or None,
    }
    return snapshot_to_state(snapshot)


async def revision_snapshot_to_state(run: dict[str, Any]) -> TravelPlanState:
    snapshot = run["request_snapshot"]
    parent_id = snapshot.get("related_itinerary_id") or snapshot.get("parent_plan_id")

    def load():
        with get_conn() as conn:
            return load_itinerary(parent_id, conn) if parent_id else None

    base = await asyncio.to_thread(load)
    if not base or not base.get("planner_state"):
        raise ValueError("基础行程缺少可修改的 planner checkpoint")
    checkpoint = base["planner_state"]
    return TravelPlanState(
        query=checkpoint.get("query", "修改行程"),
        route=checkpoint.get("route", []),
        pois=checkpoint.get("pois", []),
        planner_reviewer_dialogue=checkpoint.get("planner_reviewer_dialogue", []),
        destination=checkpoint.get("destination"),
        travel_start_date=checkpoint.get("travel_start_date"),
        travel_end_date=checkpoint.get("travel_end_date"),
        days=checkpoint.get("days", 0),
        attraction_preference=checkpoint.get("attraction_preference"),
        food_preference=checkpoint.get("food_preference"),
        habit_preference=checkpoint.get("habit_preference"),
        trip_budget=snapshot.get("trip_budget") or checkpoint.get("trip_budget"),
        effective_constraints=(
            snapshot.get("effective_constraints")
            or checkpoint.get("effective_constraints")
            or []
        ),
        constraint_coverage=(
            snapshot.get("constraint_coverage")
            or checkpoint.get("constraint_coverage")
            or []
        ),
        weather_forecast=checkpoint.get("weather_forecast", []),
        weather_note=checkpoint.get("weather_note"),
        max_per_day=checkpoint.get("max_per_day", 3),
        route_modify_opinion=f"【用户修改意见】{snapshot.get('modification_notes', '')}",
        modification_notes=snapshot.get("modification_notes"),
        parent_plan_id=parent_id,
        max_review_rounds=2,
    )


class PlanningFinalizer:
    def __init__(self, manager: RunManager):
        self.manager = manager

    async def __call__(
        self,
        run: dict[str, Any],
        updates: dict[str, Any],
        _assistant_text: str,
    ) -> dict[str, Any] | None:
        state = TravelPlanState(
            **{
                **snapshot_to_state(run["request_snapshot"]).model_dump(),
                **updates,
            }
        )
        if not state.final_plan:
            raise RuntimeError("planning graph completed without an itinerary")
        itinerary_id = await asyncio.to_thread(self._persist, run, state)
        await self.manager.publish(
            run["id"],
            "custom",
            {
                "kind": "planning.itinerary_created",
                "itinerary_id": itinerary_id,
                "destination": str(state.destination or ""),
            },
            durable=True,
        )
        return {"result_itinerary_id": itinerary_id}

    @staticmethod
    def _persist(run: dict[str, Any], state: TravelPlanState) -> str:
        checkpoint = {
            key: value
            for key, value in state.model_dump(mode="json").items()
            if key != "final_plan"
        }
        with get_conn() as conn:
            itinerary_id = save_itinerary(
                run["user_id"],
                state.final_plan,
                state.query,
                conn,
                parent_id=state.parent_plan_id,
                modification_notes=state.modification_notes,
                planner_state=checkpoint,
            )
        return itinerary_id
