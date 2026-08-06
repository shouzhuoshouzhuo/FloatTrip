"""Structured contract for the LLM-powered conversation understanding layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TripConstraintPatch(_StrictModel):
    id: str | None = None
    category: Literal[
        "attraction_preference", "food_preference", "dietary_requirement",
        "travel_pace", "budget_style", "transport_preference",
        "accommodation_preference", "schedule_preference", "companion_context",
        "accessibility_need", "other_travel_preference",
    ]
    value_text: str = Field(min_length=1, max_length=500)
    polarity: Literal["prefer", "avoid", "require", "fact"] = "fact"
    evidence_sequences: list[int] | None = Field(default=None, max_length=20)


class PlanningBriefPatch(_StrictModel):
    destination: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    days: int | None = Field(default=None, ge=1, le=30)
    budget: str | None = None
    trip_budget: str | None = None
    attraction_preference: str | None = None
    food_preference: str | None = None
    habit_preference: str | None = None
    trip_constraints: list[TripConstraintPatch] | None = Field(default=None, max_length=30)
    remove_trip_constraint_ids: list[str] | None = Field(default=None, max_length=30)
    excluded_memory_fact_ids: list[str] | None = Field(default=None, max_length=100)
    restored_memory_fact_ids: list[str] | None = Field(default=None, max_length=100)

    @field_validator(
        "destination",
        "start_date",
        "end_date",
        "budget",
        "trip_budget",
        "attraction_preference",
        "food_preference",
        "habit_preference",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DialogueTarget(_StrictModel):
    run_id: str | None = None
    itinerary_id: str | None = None


class DialogueClarification(_StrictModel):
    field: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=8)


class DialogueDecision(_StrictModel):
    """The only model output that can influence chat business actions."""

    intent: Literal[
        "travel_qa",
        "general_chat",
        "create_plan",
        "update_brief",
        "confirm_plan",
        "modify_itinerary",
        "run_control",
        "unclear",
    ]
    reply: str = Field(min_length=1, max_length=2_000)
    brief_patch: PlanningBriefPatch = Field(default_factory=PlanningBriefPatch)
    target: DialogueTarget = Field(default_factory=DialogueTarget)
    run_action: Literal["none", "cancel", "retry"] = "none"
    modification_notes: str | None = Field(default=None, max_length=2_000)
    clarification: DialogueClarification | None = None
    requires_confirmation: bool = False

    @field_validator("reply", "modification_notes", mode="before")
    @classmethod
    def normalize_reply_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DialogueUnderstandingError(RuntimeError):
    """Safe failure surfaced by the scheduler without exposing model internals."""

    public_code = "dialogue_understanding_failed"
    public_message = "这条消息暂时没有理解成功，请重试"

    def __init__(self, message: str | None = None, *, code: str | None = None):
        super().__init__(message or self.public_message)
        if message:
            self.public_message = message
        if code:
            self.public_code = code
