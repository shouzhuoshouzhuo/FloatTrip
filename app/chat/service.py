"""Application service for persistent LLM-understood travel conversations."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.chat.models import DialogueDecision
from app.core.database import get_conn
from app.chat.memory_service import ChatMemoryService
from app.chat.planning_memory import PlanningMemoryMatcher
from app.core.planning_constraints import compatibility_preferences
from app.core.travel_memory import ConversationMemoryRepository
from app.runtime.manager import RunManager
from app.runtime.models import RunKind, concurrency_key
from app.runtime.repositories import (
    ConversationRepository,
    OwnedResourceNotFound,
    PlanningBriefRepository,
    RunRepository,
)


class ChatService:
    def __init__(self, manager: RunManager, db_path: str | Path | None = None):
        self.manager = manager
        self.conversations = ConversationRepository(db_path)
        self.briefs = PlanningBriefRepository(db_path)
        self.runs = RunRepository(db_path)
        self.memory_context = ChatMemoryService(db_path)
        self.planning_memory = PlanningMemoryMatcher(db_path)
        # Local import avoids a service/executor import cycle during module loading.
        from app.chat.executor import DialogueActionExecutor

        self.actions = DialogueActionExecutor(self)

    async def submit_message(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        *,
        related_run_id: str | None = None,
        related_itinerary_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist a message and queue understanding; never infer text semantics here."""
        self.memory_context.validate_message(content)
        if related_run_id:
            await asyncio.to_thread(self.runs.get, user_id, related_run_id)
        if related_itinerary_id:
            await asyncio.to_thread(
                self._owned_itinerary_summary, user_id, related_itinerary_id
            )
        message = await asyncio.to_thread(
            self.conversations.add_message,
            user_id,
            conversation_id,
            "user",
            content,
            related_run_id=related_run_id,
            related_itinerary_id=related_itinerary_id,
        )
        run = await asyncio.to_thread(
            self.manager.create,
            user_id=user_id,
            kind=RunKind.CHAT,
            conversation_id=conversation_id,
            request_snapshot={
                "message_id": message["id"],
                "text": content,
                "related_run_id": related_run_id,
                "related_itinerary_id": related_itinerary_id,
            },
        )
        return message, run

    async def submit_brief(
        self, user_id: str, brief_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current = await asyncio.to_thread(self.briefs.get, user_id, brief_id)
        if current["status"] in self.briefs.ACTIVE:
            current = await self.planning_memory.refresh(user_id, brief_id)

        def create_run(conn, snapshot, conversation_id):
            run_id = str(uuid.uuid4())
            request = dict(snapshot)
            request.update(compatibility_preferences(request.get("effective_constraints") or []))
            request.setdefault("query", self._snapshot_query(request))
            memory = ConversationMemoryRepository(self.manager.db_path).ensure_snapshot(
                user_id, conversation_id, conn
            )
            request["memory_profile_revision"] = memory["profile_revision"]
            request["memory_profile_snapshot"] = memory["profile_snapshot"]
            return self.runs.insert(
                conn,
                run_id=run_id,
                user_id=user_id,
                kind=RunKind.TRAVEL_PLAN,
                concurrency_key=concurrency_key(RunKind.TRAVEL_PLAN, run_id=run_id),
                request_snapshot=request,
                conversation_id=conversation_id,
            )

        return await asyncio.to_thread(
            self.briefs.submit, user_id, brief_id, create_run
        )

    async def apply_brief_patch(
        self,
        run: dict[str, Any],
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        brief = await asyncio.to_thread(
            self.briefs.upsert_active,
            run["user_id"],
            run["conversation_id"],
            patch,
        )
        brief = await self.planning_memory.refresh(run["user_id"], brief["id"])
        event_kind = (
            "planning_brief.ready"
            if brief["status"] == "ready"
            else "planning_brief.updated"
        )
        await self.manager.publish(
            run["id"],
            "custom",
            {
                "kind": event_kind,
                "brief_id": brief["id"],
                "status": brief["status"],
                "summary": brief["data"],
                "missing_fields": brief["missing_fields"],
                "memory_context": brief["memory_context"],
                "effective_constraints": brief["effective_constraints"],
                "constraint_coverage": brief["constraint_coverage"],
            },
            durable=True,
        )
        return brief

    async def update_brief(
        self, user_id: str, brief_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        current = await asyncio.to_thread(self.briefs.get, user_id, brief_id)
        brief = await asyncio.to_thread(
            self.briefs.upsert_active,
            user_id,
            current["conversation_id"],
            patch,
        )
        return await self.planning_memory.refresh(user_id, brief["id"])

    async def refresh_brief_memory(
        self, user_id: str, brief_id: str
    ) -> dict[str, Any]:
        return await self.planning_memory.refresh(user_id, brief_id)

    async def publish_assistant_message(
        self, run: dict[str, Any], content: str
    ) -> dict[str, Any]:
        message = await asyncio.to_thread(
            self.conversations.add_message,
            run["user_id"],
            run["conversation_id"],
            "assistant",
            content,
            related_run_id=run["id"],
        )
        await self.manager.publish(
            run["id"],
            "custom",
            {
                "kind": "chat.message.completed",
                "message_id": message["id"],
                "content": message["content"],
                "sequence": message["sequence"],
                "created_at": message["created_at"],
            },
            durable=True,
            validate_custom=False,
        )
        return message

    async def finalize_chat(
        self,
        run: dict[str, Any],
        updates: dict[str, Any],
        _assistant_text: str,
    ) -> dict[str, Any] | None:
        decision = DialogueDecision.model_validate(updates.get("decision") or {})
        return await self.actions.execute(run, decision)

    async def chat_input(self, run: dict[str, Any]) -> dict[str, Any]:
        """Build the bounded, owner-scoped facts available to the dialogue LLM.

        The current message is deliberately kept separate from history.  This
        prevents a retried Chat Run from presenting the same user turn twice
        and keeps the agent's short-term memory stable as a conversation grows.
        """
        active = await asyncio.to_thread(
            self.briefs.active_for_conversation,
            run["user_id"],
            run["conversation_id"],
        )
        targets = await asyncio.to_thread(
            self._conversation_targets,
            run["user_id"],
            run["conversation_id"],
        )
        snapshot = run["request_snapshot"]
        itinerary_id = snapshot.get("related_itinerary_id")
        itinerary = (
            await asyncio.to_thread(
                self._owned_itinerary_summary, run["user_id"], itinerary_id
            )
            if itinerary_id
            else None
        )
        application_state = {
            "today": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "timezone": "Asia/Shanghai",
            "planning_brief": self._brief_context(active),
            "available_targets": targets,
            "explicit_target": {
                "run_id": snapshot.get("related_run_id"),
                "itinerary_id": itinerary_id,
                "itinerary": itinerary,
            },
        }
        context = await self.memory_context.prepare(
            run, application_state=application_state
        )
        return {"dialogue_context": context}

    def _conversation_targets(
        self, user_id: str, conversation_id: str
    ) -> list[dict[str, Any]]:
        runs = self.runs.list(user_id, conversation_id=conversation_id, limit=20)
        targets: list[dict[str, Any]] = []
        for item in runs:
            if item["kind"] not in {RunKind.TRAVEL_PLAN.value, RunKind.REVISION.value}:
                continue
            snapshot = item["request_snapshot"]
            itinerary_id = item.get("result_itinerary_id") or snapshot.get(
                "related_itinerary_id"
            )
            targets.append(
                {
                    "run_id": item["id"],
                    "itinerary_id": itinerary_id,
                    "kind": item["kind"],
                    "status": item["status"],
                    "destination": snapshot.get("destination", ""),
                }
            )
        return targets

    def _owned_itinerary_summary(
        self, user_id: str, itinerary_id: str | None
    ) -> dict[str, Any]:
        if not itinerary_id:
            raise OwnedResourceNotFound("base itinerary not found")
        with get_conn(self.manager.db_path) as conn:
            row = conn.execute(
                "SELECT id,destination,start_date,end_date,version,query "
                "FROM itineraries WHERE id=? AND user_id=?",
                (itinerary_id, user_id),
            ).fetchone()
        if not row:
            raise OwnedResourceNotFound("base itinerary not found")
        return dict(row)

    def _itinerary_is_modifiable(self, user_id: str, itinerary_id: str) -> bool:
        """Check the private checkpoint without ever placing it in LLM context."""
        with get_conn(self.manager.db_path) as conn:
            row = conn.execute(
                "SELECT planner_state_json FROM itineraries WHERE id=? AND user_id=?",
                (itinerary_id, user_id),
            ).fetchone()
        return bool(row and row["planner_state_json"])

    @staticmethod
    def _brief_context(brief: dict[str, Any] | None) -> dict[str, Any] | None:
        if not brief:
            return None
        return {
            "id": brief["id"],
            "status": brief["status"],
            "data": brief["data"],
            "missing_fields": brief["missing_fields"],
            "memory_context": brief.get("memory_context"),
            "effective_constraints": brief.get("effective_constraints") or [],
        }

    @staticmethod
    def _snapshot_query(snapshot: dict[str, Any]) -> str:
        parts = [str(snapshot.get("destination") or "").strip()]
        if snapshot.get("start_date") and snapshot.get("end_date"):
            parts.append(f"{snapshot['start_date']}至{snapshot['end_date']}")
        elif snapshot.get("days"):
            parts.append(f"{snapshot['days']}日游")
        if snapshot.get("trip_budget"):
            parts.append(f"本次预算：{snapshot['trip_budget']}")
        for item in snapshot.get("effective_constraints") or []:
            if item.get("value_text"):
                parts.append(str(item["value_text"]))
        return "，".join(part for part in parts if part)
