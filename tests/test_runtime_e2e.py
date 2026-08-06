from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.chat.service import ChatService
from app.chat.models import DialogueDecision, DialogueTarget
from app.core.database import get_conn, init_db
from app.core.memory import save_itinerary
from app.runtime.manager import RunManager
from app.runtime.models import RunKind
from app.runtime.repositories import ConversationRepository
from app.runtime.scheduler import RuntimeScheduler


class RuntimeEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "e2e.db"
        init_db(self.db_path)
        with get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                ("owner", "owner", "hash", "2026-01-01"),
            )
        self.manager = RunManager(self.db_path)
        self.scheduler = RuntimeScheduler(
            self.manager,
            planning_limit=2,
            planning_per_user=2,
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def _wait_terminal(self, run_id: str):
        for _ in range(100):
            run = self.manager.runs.get_internal(run_id)
            if run["status"] in {"succeeded", "failed", "cancelled"}:
                return run
            await asyncio.sleep(0.01)
        self.fail(f"run {run_id} did not finish")

    async def test_chat_to_brief_confirmation_to_itinerary(self):
        conversations = ConversationRepository(self.db_path)
        conversation = conversations.create("owner", "云南")
        service = ChatService(self.manager, self.db_path)
        _message, chat_run = await service.submit_message(
            "owner", conversation["id"], "帮我规划云南五日游"
        )
        brief = await service.apply_brief_patch(
            chat_run,
            {
                "destination": "云南",
                "days": 5,
                "start_date": "2026-10-01",
                "end_date": "2026-10-05",
            },
        )
        self.assertEqual(brief["status"], "ready")
        submitted, planning_run = await service.submit_brief("owner", brief["id"])
        self.assertEqual(submitted["status"], "submitted")

        async def planning_handler(run, _cancel):
            with get_conn(self.db_path) as conn:
                itinerary_id = save_itinerary(
                    run["user_id"],
                    {"destination": "云南", "days": []},
                    run["request_snapshot"]["query"],
                    conn,
                )
            return {"result_itinerary_id": itinerary_id}

        self.scheduler.register(RunKind.TRAVEL_PLAN, planning_handler)
        await self.scheduler.start()
        finished = await self._wait_terminal(planning_run["id"])
        await self.scheduler.stop()
        self.assertEqual(finished["status"], "succeeded")
        self.assertTrue(finished["result_itinerary_id"])
        self.assertEqual(submitted["submission_snapshot"]["destination"], "云南")
        self.assertEqual(submitted["submission_snapshot"]["days"], 5)
        self.assertEqual(submitted["submission_snapshot"]["effective_constraints"], [])
        self.assertEqual(submitted["submission_snapshot"]["constraint_coverage"], [])

    async def test_targeted_message_is_understood_then_creates_a_real_revision_run(self):
        conversations = ConversationRepository(self.db_path)
        conversation = conversations.create("owner", "泉州")
        with get_conn(self.db_path) as conn:
            itinerary_id = save_itinerary(
                "owner",
                {"destination": "泉州", "days": []},
                "泉州四日游",
                conn,
                planner_state={"query": "泉州四日游", "route": [], "pois": []},
            )
        service = ChatService(self.manager, self.db_path)

        message, run = await service.submit_message(
            "owner",
            conversation["id"],
            "第三天下午不要安排景点，留给我休息；其余不变。",
            related_itinerary_id=itinerary_id,
        )

        self.assertEqual(message["related_itinerary_id"], itinerary_id)
        self.assertEqual(run["kind"], "chat")
        self.assertEqual(run["conversation_id"], conversation["id"])
        self.assertEqual(
            run["request_snapshot"]["related_itinerary_id"],
            itinerary_id,
        )
        self.assertEqual(run["request_snapshot"]["text"], "第三天下午不要安排景点，留给我休息；其余不变。")

        result = await service.actions.execute(
            run,
            DialogueDecision(
                intent="modify_itinerary",
                reply="我会为第三天下午留出休息时间。",
                target=DialogueTarget(itinerary_id=itinerary_id),
                modification_notes="第三天下午不要安排景点，留给我休息；其余不变。",
            ),
        )
        revision = self.manager.runs.get_internal(result["created_run_id"])
        self.assertEqual(revision["kind"], "revision")
        self.assertEqual(revision["request_snapshot"]["destination"], "泉州")
        self.assertEqual(
            revision["request_snapshot"]["modification_notes"],
            "第三天下午不要安排景点，留给我休息；其余不变。",
        )

    async def test_two_plans_execute_concurrently_without_merging(self):
        active = 0
        maximum = 0
        snapshots = []

        async def planning_handler(run, _cancel):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            snapshots.append(run["request_snapshot"]["destination"])
            await asyncio.sleep(0.03)
            active -= 1
            return {}

        self.scheduler.register(RunKind.TRAVEL_PLAN, planning_handler)
        first = self.manager.create(
            user_id="owner",
            kind=RunKind.TRAVEL_PLAN,
            request_snapshot={"destination": "云南", "days": 5},
        )
        second = self.manager.create(
            user_id="owner",
            kind=RunKind.TRAVEL_PLAN,
            request_snapshot={"destination": "新疆", "days": 7},
        )
        await self.scheduler.start()
        await asyncio.gather(
            self._wait_terminal(first["id"]),
            self._wait_terminal(second["id"]),
        )
        await self.scheduler.stop()
        self.assertEqual(maximum, 2)
        self.assertCountEqual(snapshots, ["云南", "新疆"])
