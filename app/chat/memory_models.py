"""Strict structured contracts for conversation summaries and memory extraction."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictMemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SequenceRange(StrictMemoryModel):
    from_sequence: int = Field(ge=1)
    through_sequence: int = Field(ge=1)


class ConversationSummary(StrictMemoryModel):
    topics: list[str] = Field(default_factory=list, max_length=20)
    confirmed_constraints: list[str] = Field(default_factory=list, max_length=30)
    negative_constraints: list[str] = Field(default_factory=list, max_length=30)
    preferences_and_corrections: list[str] = Field(default_factory=list, max_length=30)
    open_questions: list[str] = Field(default_factory=list, max_length=20)
    decisions: list[str] = Field(default_factory=list, max_length=20)
    source_sequence_range: SequenceRange


class ExtractedMemory(StrictMemoryModel):
    action: Literal["add", "replace", "forget", "candidate", "ignore"]
    category: Literal[
        "attraction_preference",
        "food_preference",
        "dietary_requirement",
        "travel_pace",
        "budget_style",
        "transport_preference",
        "accommodation_preference",
        "schedule_preference",
        "companion_context",
        "accessibility_need",
        "destination_history",
        "other_travel_preference",
    ]
    value_text: str = Field(default="", max_length=500)
    polarity: Literal["prefer", "avoid", "require", "fact"] = "fact"
    scope_type: Literal[
        "global", "destination", "companion", "destination_companion"
    ] = "global"
    scope_key: dict[str, str] = Field(default_factory=dict)
    explicitness: Literal["explicit", "inferred"] = "inferred"
    sensitivity: Literal["normal", "protected", "prohibited"] = "normal"
    evidence_sequences: list[int] = Field(default_factory=list, max_length=20)
    supersedes_fact_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("value_text", mode="before")
    @classmethod
    def strip_value(cls, value: object) -> str:
        return str(value or "").strip()


class MemoryExtractionResult(StrictMemoryModel):
    items: list[ExtractedMemory] = Field(default_factory=list, max_length=30)
