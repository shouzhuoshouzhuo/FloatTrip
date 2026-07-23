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
from app.core.memory import get_user_profile, set_user_profile
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
        def create_run(conn, snapshot, conversation_id):
            run_id = str(uuid.uuid4())
            request = dict(snapshot)
            request.setdefault("query", self._snapshot_query(request))
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
            },
            durable=True,
        )
        return brief

    async def merge_profile_from_brief_patch(
        self, user_id: str, patch: dict[str, Any]
    ) -> None:
        """Persist explicit structured preferences without interpreting chat text.

        A profile is append-only here: a newly stated preference enriches the
        user's durable memory while absent fields never erase unrelated facts.
        """
        updates = {
            "attraction_prefs": patch.get("attraction_preference"),
            "food_prefs": patch.get("food_preference"),
            "habit_prefs": patch.get("habit_preference"),
        }
        if not any(isinstance(value, str) and value.strip() for value in updates.values()):
            return

        def merge() -> None:
            with get_conn(self.manager.db_path) as conn:
                profile = get_user_profile(user_id, conn)
                merged = {key: list(profile.get(key, [])) for key in profile}
                for key, value in updates.items():
                    normalized = value.strip() if isinstance(value, str) else ""
                    if normalized and normalized not in merged[key]:
                        merged[key].append(normalized)
                set_user_profile(user_id, merged, conn)

        await asyncio.to_thread(merge)

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
        messages = await asyncio.to_thread(
            self.conversations.messages,
            run["user_id"],
            run["conversation_id"],
            # The repository returns chronological rows.  Fetch a bounded
            # envelope and retain only its newest turns below, rather than
            # accidentally feeding the beginning of a long conversation.
            limit=200,
        )
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
        profile = await asyncio.to_thread(self._user_profile_context, run["user_id"])
        snapshot = run["request_snapshot"]
        itinerary_id = snapshot.get("related_itinerary_id")
        itinerary = (
            await asyncio.to_thread(
                self._owned_itinerary_summary, run["user_id"], itinerary_id
            )
            if itinerary_id
            else None
        )
        current_id = snapshot.get("message_id")
        history = [
            {
                "role": item["role"],
                "content": item["content"],
                "sequence": item["sequence"],
            }
            for item in messages
            if item["id"] != current_id
        ][-12:]
        context = {
            "today": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "timezone": "Asia/Shanghai",
            "current_message": snapshot.get("text", ""),
            "history": history,
            "planning_brief": self._brief_context(active),
            "user_profile": profile,
            "available_targets": targets,
            "explicit_target": {
                "run_id": snapshot.get("related_run_id"),
                "itinerary_id": itinerary_id,
                "itinerary": itinerary,
            },
        }
        return {"dialogue_context": context}

    def _user_profile_context(self, user_id: str) -> dict[str, list[str]]:
        """Return only user-owned, durable preference facts for the prompt."""
        with get_conn(self.manager.db_path) as conn:
            profile = get_user_profile(user_id, conn)
        return {
            key: [str(value) for value in profile.get(key, [])[:20] if str(value).strip()]
            for key in (
                "attraction_prefs",
                "food_prefs",
                "habit_prefs",
                "visited_destinations",
            )
        }

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
        }

    @staticmethod
    def _snapshot_query(snapshot: dict[str, Any]) -> str:
        parts = [str(snapshot.get("destination") or "").strip()]
        if snapshot.get("start_date") and snapshot.get("end_date"):
            parts.append(f"{snapshot['start_date']}至{snapshot['end_date']}")
        elif snapshot.get("days"):
            parts.append(f"{snapshot['days']}日游")
        for key in ("attraction_preference", "food_preference", "habit_preference"):
            if snapshot.get(key):
                parts.append(str(snapshot[key]))
        return "，".join(part for part in parts if part)
