"""Structured contract for the LLM-powered conversation understanding layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningBriefPatch(_StrictModel):
    destination: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    days: int | None = Field(default=None, ge=1, le=30)
    budget: str | None = None
    attraction_preference: str | None = None
    food_preference: str | None = None
    habit_preference: str | None = None

    @field_validator(
        "destination",
        "start_date",
        "end_date",
        "budget",
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
