"""Deterministic execution of validated dialogue decisions.

This module intentionally never receives or reads the raw user message.  The
LLM's validated structured decision is the boundary between language
understanding and business-state changes.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING, Any

from app.chat.models import DialogueDecision, PlanningBriefPatch
from app.core.planning_brief import required_brief_fields
from app.runtime.models import RunKind, RunStatus
from app.runtime.repositories import OwnedResourceNotFound

if TYPE_CHECKING:
    from app.chat.service import ChatService


class DialogueActionExecutor:
    def __init__(self, service: "ChatService"):
        self.service = service

    async def execute(
        self, run: dict[str, Any], decision: DialogueDecision
    ) -> dict[str, Any]:
        """Apply a decision with no text inference or model-controlled state bypass."""
        reply = decision.clarification.question if decision.clarification else decision.reply
        result: dict[str, Any] = {}

        if decision.intent in {"create_plan", "update_brief"}:
            brief, error = await self._apply_brief(run, decision)
            if error:
                reply = error
            elif brief:
                result["brief_id"] = brief["id"]
        elif decision.intent == "confirm_plan":
            submitted, error = await self._confirm_plan(run)
            if error:
                reply = error
            elif submitted:
                brief, planning_run = submitted
                result.update(
                    brief_id=brief["id"],
                    created_run_id=planning_run["id"],
                )
                await self._publish_created_run(run, planning_run)
        elif decision.intent == "modify_itinerary":
            revision, error = await self._create_revision(run, decision)
            if error:
                reply = error
            elif revision:
                result["created_run_id"] = revision["id"]
                await self._publish_created_run(run, revision)
        elif decision.intent == "run_control":
            controlled, error = await self._control_run(run, decision)
            if error:
                reply = error
            elif controlled:
                result["controlled_run_id"] = controlled["id"]

        await self.service.publish_assistant_message(run, reply)
        return result

    async def _publish_created_run(
        self, chat_run: dict[str, Any], created_run: dict[str, Any]
    ) -> None:
        """Expose a durable, public run projection to the active conversation.

        The run is created from a Chat Run, so its card must arrive over that
        same stream; otherwise it would be invisible until the user reloads.
        """
        await self.service.manager.publish(
            chat_run["id"],
            "custom",
            {"kind": "run.created", "run": created_run},
            durable=True,
            validate_custom=False,
        )

    async def _apply_brief(
        self, run: dict[str, Any], decision: DialogueDecision
    ) -> tuple[dict[str, Any] | None, str | None]:
        patch = decision.brief_patch.model_dump(exclude_none=True, exclude_unset=True)
        if not patch:
            return None, "我还需要一点旅行信息，才能继续整理这趟行程。"
        if not self._patch_dates_valid(patch):
            return None, "日期范围看起来不正确，请补充有效的开始和结束日期。"
        active = await asyncio.to_thread(
            self.service.briefs.active_for_conversation,
            run["user_id"],
            run["conversation_id"],
        )
        combined = {
            **((active or {}).get("data") or {}),
            **patch,
        }
        existing_constraints = list(((active or {}).get("data") or {}).get("trip_constraints") or [])
        remove_ids = {str(value) for value in (patch.pop("remove_trip_constraint_ids", []) or [])}
        constraints_by_id = {
            str(item.get("id")): dict(item)
            for item in existing_constraints
            if item.get("id") and str(item.get("id")) not in remove_ids
        }
        for item in (patch.pop("trip_constraints", []) or []):
            item_id = str(item.get("id") or "")
            if item_id and item_id in constraints_by_id:
                constraints_by_id[item_id] = item
            else:
                key = (item.get("category"), str(item.get("value_text") or "").casefold(), item.get("polarity"))
                duplicate = next((current_id for current_id, current in constraints_by_id.items() if (
                    current.get("category"), str(current.get("value_text") or "").casefold(), current.get("polarity")
                ) == key), None)
                constraints_by_id[duplicate or item_id or f"new:{len(constraints_by_id)}"] = item
        excluded = set(((active or {}).get("data") or {}).get("excluded_memory_fact_ids") or [])
        excluded.update(patch.pop("excluded_memory_fact_ids", []) or [])
        excluded.difference_update(patch.pop("restored_memory_fact_ids", []) or [])
        if constraints_by_id or existing_constraints:
            combined["trip_constraints"] = list(constraints_by_id.values())
            patch["trip_constraints"] = combined["trip_constraints"]
        if excluded:
            combined["excluded_memory_fact_ids"] = sorted(excluded)
            patch["excluded_memory_fact_ids"] = sorted(excluded)
        if not self._combined_dates_valid(combined):
            return None, "结束日期不能早于开始日期，请确认日期范围。"
        self._normalize_days(combined)
        # Action-only fields never enter durable brief data.  Supplying the
        # complete canonical brief also makes list replacement deterministic.
        durable_fields = {
            "destination", "start_date", "end_date", "days", "budget",
            "trip_budget", "attraction_preference", "food_preference",
            "habit_preference", "trip_constraints", "excluded_memory_fact_ids",
        }
        patch = {key: value for key, value in combined.items() if key in durable_fields}
        brief = await self.service.apply_brief_patch(run, patch)
        return brief, None

    async def _confirm_plan(
        self, run: dict[str, Any]
    ) -> tuple[tuple[dict[str, Any], dict[str, Any]] | None, str | None]:
        brief = await asyncio.to_thread(
            self.service.briefs.active_for_conversation,
            run["user_id"],
            run["conversation_id"],
        )
        if not brief:
            brief = await asyncio.to_thread(
                self.service.briefs.latest_for_conversation,
                run["user_id"],
                run["conversation_id"],
            )
        if not brief:
            return None, "目前没有可确认的旅行需求。"
        if brief["status"] == "submitted" and brief.get("submitted_run_id"):
            return (
                brief,
                await asyncio.to_thread(
                    self.service.runs.get, run["user_id"], brief["submitted_run_id"]
                ),
            ), None
        missing = required_brief_fields(brief["data"])
        if brief["status"] != "ready" or missing:
            labels = {
                "destination": "目的地",
                "start_date": "开始日期",
                "end_date": "结束日期",
                "date_range": "有效日期范围",
            }
            needed = "、".join(labels.get(item, item) for item in missing)
            return None, f"还需要补充：{needed or '完整旅行信息'}。"
        submitted, planning_run = await self.service.submit_brief(
            run["user_id"], brief["id"]
        )
        await self.service.manager.publish(
            run["id"],
            "custom",
            {
                "kind": "planning_brief.submitted",
                "brief_id": submitted["id"],
                "status": submitted["status"],
                "summary": submitted["data"],
                "missing_fields": submitted["missing_fields"],
            },
            durable=True,
        )
        return (submitted, planning_run), None

    async def _create_revision(
        self, run: dict[str, Any], decision: DialogueDecision
    ) -> tuple[dict[str, Any] | None, str | None]:
        itinerary_id, error = await self._resolve_itinerary(run, decision)
        if error:
            return None, error
        if not decision.modification_notes:
            return None, "我还不清楚要如何调整这份行程，请补充具体改动。"
        try:
            summary = await asyncio.to_thread(
                self.service._owned_itinerary_summary, run["user_id"], itinerary_id
            )
        except OwnedResourceNotFound:
            return None, "这份行程不可用，请重新选择要修改的行程。"
        modifiable = await asyncio.to_thread(
            self.service._itinerary_is_modifiable, run["user_id"], itinerary_id
        )
        if not modifiable:
            return None, "这份行程缺少可修改的规划记录，暂时不能在原行程上调整。"
        memory = await asyncio.to_thread(
            self.service.memory_context.memories.get,
            run["user_id"],
            run["conversation_id"],
        )
        created = await asyncio.to_thread(
            self.service.manager.create,
            user_id=run["user_id"],
            kind=RunKind.REVISION,
            conversation_id=run["conversation_id"],
            itinerary_id=itinerary_id,
            request_snapshot={
                "modification_notes": decision.modification_notes,
                "parent_plan_id": itinerary_id,
                "related_itinerary_id": itinerary_id,
                "related_run_id": decision.target.run_id
                or run["request_snapshot"].get("related_run_id"),
                "destination": summary.get("destination"),
                "memory_profile_revision": memory["profile_revision"],
                "memory_profile_snapshot": memory["profile_snapshot"],
            },
        )
        return created, None

    async def _control_run(
        self, run: dict[str, Any], decision: DialogueDecision
    ) -> tuple[dict[str, Any] | None, str | None]:
        target_id, error = await self._resolve_run(run, decision)
        if error:
            return None, error
        if decision.requires_confirmation:
            return None, "请在对应任务卡片上确认这项操作，避免误影响正在进行的规划。"
        try:
            target = await asyncio.to_thread(
                self.service.runs.get, run["user_id"], target_id
            )
        except OwnedResourceNotFound:
            return None, "这个任务不可用，请重新选择。"
        if decision.run_action == "cancel":
            if target["status"] in {
                RunStatus.SUCCEEDED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
            }:
                return None, "这个任务已经结束，不能再停止。"
            return await self.service.manager.cancel(run["user_id"], target_id), None
        if decision.run_action == "retry":
            if target["status"] not in {
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
            }:
                return None, "只有已停止或未完成的任务可以重新尝试。"
            try:
                retried = await asyncio.to_thread(
                    self.service.manager.retry, run["user_id"], target_id
                )
            except ValueError:
                # The run may have changed while this Chat Run was waiting in
                # the queue.  Do not expose a race or turn it into a failure.
                return None, "这个任务当前不能重新尝试，请刷新后再查看状态。"
            return retried, None
        return None, "请说明是要停止还是重新尝试这项任务。"

    async def _resolve_itinerary(
        self, run: dict[str, Any], decision: DialogueDecision
    ) -> tuple[str | None, str | None]:
        explicit = run["request_snapshot"].get("related_itinerary_id")
        if explicit:
            if decision.target.itinerary_id and decision.target.itinerary_id != explicit:
                return None, "这条消息已绑定另一份行程，请在对应行程中继续修改。"
            return explicit, None
        targets = await asyncio.to_thread(
            self.service._conversation_targets,
            run["user_id"],
            run["conversation_id"],
        )
        candidates = {
            item["itinerary_id"]
            for item in targets
            if item.get("itinerary_id")
        }
        requested = decision.target.itinerary_id
        if requested and requested in candidates:
            return requested, None
        if not requested and len(candidates) == 1:
            return next(iter(candidates)), None
        return None, "我找到了多个可能的行程，请先选择要修改的那一份。"

    async def _resolve_run(
        self, run: dict[str, Any], decision: DialogueDecision
    ) -> tuple[str | None, str | None]:
        explicit = run["request_snapshot"].get("related_run_id")
        if explicit:
            if decision.target.run_id and decision.target.run_id != explicit:
                return None, "这条消息已绑定另一项任务，请在对应任务中操作。"
            return explicit, None
        targets = await asyncio.to_thread(
            self.service._conversation_targets,
            run["user_id"],
            run["conversation_id"],
        )
        candidates = {
            item["run_id"]
            for item in targets
            if item["status"]
            in {RunStatus.QUEUED.value, RunStatus.RUNNING.value, RunStatus.WAITING_USER.value,
                RunStatus.FAILED.value, RunStatus.CANCELLED.value}
        }
        requested = decision.target.run_id
        if requested and requested in candidates:
            return requested, None
        if not requested and len(candidates) == 1:
            return next(iter(candidates)), None
        return None, "我找到了多个可能的任务，请先选择具体任务。"

    @staticmethod
    def _parse_date(value: object) -> date | None:
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    def _patch_dates_valid(self, patch: dict[str, Any]) -> bool:
        for key in ("start_date", "end_date"):
            if key in patch and self._parse_date(patch[key]) is None:
                return False
        return True

    def _combined_dates_valid(self, data: dict[str, Any]) -> bool:
        start = self._parse_date(data.get("start_date"))
        end = self._parse_date(data.get("end_date"))
        return not (start and end and end < start)

    def _normalize_days(self, data: dict[str, Any]) -> None:
        start = self._parse_date(data.get("start_date"))
        end = self._parse_date(data.get("end_date"))
        if start and end:
            data["days"] = (end - start).days + 1
