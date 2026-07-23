from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.core.database import get_conn, init_db
from app.runtime.manager import RunManager
from app.runtime.models import RunKind, RunStatus
from app.runtime.scheduler import RuntimeScheduler
from app.runtime.stream import StreamBridge, StreamItem


class RuntimeCoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "runtime.db"
        init_db(self.db_path)
        with get_conn(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                [
                    ("user-a", "a", "hash", "2026-01-01T00:00:00Z"),
                    ("user-b", "b", "hash", "2026-01-01T00:00:00Z"),
                ],
            )
            conn.execute(
                "INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("conversation-a", "user-a", "", "2026-01-01", "2026-01-01"),
            )
        self.manager = RunManager(
            self.db_path, StreamBridge(retention=16, heartbeat_seconds=0.01)
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_durable_event_is_written_before_notification(self):
        run = self.manager.create(
            user_id="user-a",
            kind=RunKind.CHAT,
            conversation_id="conversation-a",
            request_snapshot={"text": "hi"},
        )
        async with self.manager.bridge.subscribe(run["id"]) as stream:
            await self.manager.publish(
                run["id"], "custom", {"kind": "run.status", "status": "queued"}
            )
            item = await anext(stream)
            stored = self.manager.events.after(run["id"])
        self.assertEqual(item.sequence, 1)
        self.assertEqual(stored[0]["sequence"], 1)

    async def test_stream_deduplicates_cursor_and_emits_end(self):
        bridge = StreamBridge(retention=8, heartbeat_seconds=1)
        await bridge.publish(StreamItem("r", "custom", {}, sequence=1, durable=True))
        await bridge.publish(StreamItem("r", "custom", {}, sequence=2, durable=True))
        await bridge.publish(StreamItem("r", "end", {}, sequence=3, durable=True))
        async with bridge.subscribe("r", after_sequence=1) as stream:
            result = [await anext(stream), await anext(stream)]
        self.assertEqual([item.sequence for item in result], [2, 3])

    async def test_cancel_is_idempotent(self):
        run = self.manager.create(
            user_id="user-a",
            kind=RunKind.TRAVEL_PLAN,
            request_snapshot={"query": "云南"},
        )
        first = await self.manager.cancel("user-a", run["id"])
        second = await self.manager.cancel("user-a", run["id"])
        self.assertEqual(first["status"], RunStatus.CANCELLED.value)
        self.assertEqual(second["status"], RunStatus.CANCELLED.value)

    async def test_chat_capacity_is_independent_from_planning(self):
        scheduler = RuntimeScheduler(
            self.manager, chat_limit=1, planning_limit=1, planning_per_user=1
        )
        plan_gate = asyncio.Event()
        chat_finished = asyncio.Event()

        async def plan_handler(_run, _cancel):
            await plan_gate.wait()
            return {}

        async def chat_handler(_run, _cancel):
            chat_finished.set()
            return {}

        scheduler.register(RunKind.TRAVEL_PLAN, plan_handler)
        scheduler.register(RunKind.CHAT, chat_handler)
        plan = self.manager.create(
            user_id="user-a",
            kind=RunKind.TRAVEL_PLAN,
            request_snapshot={"query": "云南"},
        )
        chat = self.manager.create(
            user_id="user-a",
            kind=RunKind.CHAT,
            conversation_id="conversation-a",
            request_snapshot={"text": "十月适合去吗"},
        )
        await scheduler.start()
        await asyncio.wait_for(chat_finished.wait(), timeout=1)
        for _ in range(50):
            if self.manager.runs.get_internal(chat["id"])["status"] == "succeeded":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(
            self.manager.runs.get_internal(chat["id"])["status"], "succeeded"
        )
        self.assertEqual(
            self.manager.runs.get_internal(plan["id"])["status"], "running"
        )
        plan_gate.set()
        await asyncio.sleep(0.05)
        await scheduler.stop()

    async def test_startup_reconciliation_marks_orphan_failed(self):
        run = self.manager.create(
            user_id="user-a",
            kind=RunKind.TRAVEL_PLAN,
            request_snapshot={"query": "云南"},
        )
        self.manager.runs.transition(run["id"], RunStatus.RUNNING)
        reconciled = await self.manager.reconcile_startup()
        self.assertEqual(reconciled, [run["id"]])
        self.assertEqual(
            self.manager.runs.get_internal(run["id"])["status"], "failed"
        )

    async def test_revisions_for_one_itinerary_are_serialized(self):
        scheduler = RuntimeScheduler(
            self.manager, planning_limit=2, planning_per_user=2
        )
        active = 0
        maximum = 0
        order = []

        async def revision_handler(run, _cancel):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            order.append(run["id"])
            await asyncio.sleep(0.02)
            active -= 1
            return {}

        scheduler.register(RunKind.REVISION, revision_handler)
        first = self.manager.create(
            user_id="user-a",
            kind=RunKind.REVISION,
            itinerary_id="itinerary-a",
            request_snapshot={"related_itinerary_id": "itinerary-a"},
        )
        second = self.manager.create(
            user_id="user-a",
            kind=RunKind.REVISION,
            itinerary_id="itinerary-a",
            request_snapshot={"related_itinerary_id": "itinerary-a"},
        )
        await scheduler.start()
        for _ in range(100):
            statuses = [
                self.manager.runs.get_internal(first["id"])["status"],
                self.manager.runs.get_internal(second["id"])["status"],
            ]
            if statuses == ["succeeded", "succeeded"]:
                break
            await asyncio.sleep(0.01)
        await scheduler.stop()
        self.assertEqual(maximum, 1)
        self.assertEqual(order, [first["id"], second["id"]])
