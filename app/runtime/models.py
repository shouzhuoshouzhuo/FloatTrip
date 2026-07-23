"""Validated public models and lifecycle rules for Agent runs."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunKind(StrEnum):
    CHAT = "chat"
    TRAVEL_PLAN = "travel_plan"
    REVISION = "revision"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DisconnectPolicy(StrEnum):
    CONTINUE = "continue"
    CANCEL = "cancel"


TERMINAL_STATUSES = {
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}

ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.RUNNING: {
        RunStatus.WAITING_USER,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.WAITING_USER: {
        RunStatus.RUNNING,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


class PublicError(BaseModel):
    code: str = "run_failed"
    message: str = "任务执行失败，请稍后重试"
    retryable: bool = True


class PublicEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    sequence: int | None = None
    kind: Literal["messages", "custom", "error", "heartbeat", "end"]
    payload: dict[str, Any] = Field(default_factory=dict)
    durable: bool = False


class PlanningBriefEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "planning_brief.updated",
        "planning_brief.ready",
        "planning_brief.submitted",
        "planning_brief.discarded",
    ]
    brief_id: str
    status: Literal["collecting", "ready", "submitted", "discarded"]
    summary: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)


class PlanningProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["planning_run.progress"]
    stage: str
    label: str
    round: int | None = None


class WaitingUserEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["run.waiting_user"]
    interaction_id: str
    question: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ItineraryCreatedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["planning.itinerary_created"]
    itinerary_id: str
    destination: str = ""


CUSTOM_EVENT_TYPES = (
    PlanningBriefEvent
    | PlanningProgressEvent
    | WaitingUserEvent
    | ItineraryCreatedEvent
)


def validate_transition(current: RunStatus | str, target: RunStatus | str) -> None:
    source = RunStatus(current)
    destination = RunStatus(target)
    if source == destination:
        return
    if destination not in ALLOWED_TRANSITIONS[source]:
        raise ValueError(f"invalid run transition: {source.value} -> {destination.value}")


def concurrency_key(
    kind: RunKind | str,
    *,
    conversation_id: str | None = None,
    run_id: str | None = None,
    itinerary_id: str | None = None,
) -> str:
    parsed = RunKind(kind)
    if parsed is RunKind.CHAT:
        if not conversation_id:
            raise ValueError("chat runs require conversation_id")
        return f"chat:{conversation_id}"
    if parsed is RunKind.REVISION:
        if not itinerary_id:
            raise ValueError("revision runs require itinerary_id")
        return f"revision:{itinerary_id}"
    if not run_id:
        raise ValueError("travel plan runs require run_id")
    return f"plan:{run_id}"
