from __future__ import annotations

import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path

from app.core.database import get_conn, init_db
from app.runtime.models import RunKind, RunStatus, concurrency_key
from app.runtime.repositories import (
    ConversationRepository,
    OwnedResourceNotFound,
    PlanningBriefRepository,
    RunEventRepository,
    RunRepository,
)


class RepositoryTestCase(unittest.TestCase):
    def setUp(self):
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
        self.conversations = ConversationRepository(self.db_path)
        self.briefs = PlanningBriefRepository(self.db_path)
        self.runs = RunRepository(self.db_path)
        self.events = RunEventRepository(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def create_run(self, user_id="user-a", conversation_id=None):
        run_id = f"run-{id(self)}-{conversation_id or 'none'}"
        with get_conn(self.db_path) as conn:
            return self.runs.insert(
                conn,
                run_id=run_id,
                user_id=user_id,
                kind=RunKind.CHAT if conversation_id else RunKind.TRAVEL_PLAN,
                concurrency_key=(
                    concurrency_key(RunKind.CHAT, conversation_id=conversation_id)
                    if conversation_id
                    else concurrency_key(RunKind.TRAVEL_PLAN, run_id=run_id)
                ),
                request_snapshot={"query": "test"},
                conversation_id=conversation_id,
            )

    def test_owner_isolation_and_cursor_ordering(self):
        conversation = self.conversations.create("user-a", "测试")
        first = self.conversations.add_message(
            "user-a", conversation["id"], "user", "第一条"
        )
        second = self.conversations.add_message(
            "user-a", conversation["id"], "assistant", "第二条"
        )
        self.assertEqual((first["sequence"], second["sequence"]), (1, 2))
        self.assertEqual(
            [item["content"] for item in self.conversations.messages(
                "user-a", conversation["id"], after_sequence=1
            )],
            ["第二条"],
        )
        with self.assertRaises(OwnedResourceNotFound):
            self.conversations.get("user-b", conversation["id"])

    def test_first_message_replaces_placeholder_conversation_title(self):
        conversation = self.conversations.create("user-a", "新的旅行对话")
        self.conversations.add_message(
            "user-a", conversation["id"], "user",
            "更偏美食和古城，那就泉州吧。10月12日到15日",
        )
        updated = self.conversations.get("user-a", conversation["id"])
        self.assertEqual(updated["title"], "更偏美食和古城，那就泉州吧。10月12日到15日")

    def test_active_brief_is_reused_and_submission_snapshot_is_immutable(self):
        conversation = self.conversations.create("user-a")
        first = self.briefs.upsert_active(
            "user-a", conversation["id"], {"destination": "云南"}
        )
        second = self.briefs.upsert_active(
            "user-a", conversation["id"], {"days": 5}
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "collecting")
        self.assertEqual(
            second["missing_fields"],
            ["start_date", "end_date"],
        )
        second = self.briefs.upsert_active(
            "user-a",
            conversation["id"],
            {"start_date": "2026-10-01", "end_date": "2026-10-05"},
        )
        self.assertEqual(second["status"], "ready")

        def create_run(conn, snapshot, conversation_id):
            return self.runs.insert(
                conn,
                run_id="brief-run",
                user_id="user-a",
                kind=RunKind.TRAVEL_PLAN,
                concurrency_key="plan:brief-run",
                request_snapshot=snapshot,
                conversation_id=conversation_id,
            )

        submitted, run = self.briefs.submit("user-a", second["id"], create_run)
        submitted_again, same_run = self.briefs.submit(
            "user-a", second["id"], create_run
        )
        self.assertEqual(run["id"], same_run["id"])
        self.assertEqual(
            submitted["submission_snapshot"],
            {
                "destination": "云南",
                "days": 5,
                "start_date": "2026-10-01",
                "end_date": "2026-10-05",
            },
        )
        self.assertEqual(
            submitted_again["submission_snapshot"],
            submitted["submission_snapshot"],
        )

    def test_brief_rejects_invalid_or_reversed_date_ranges(self):
        conversation = self.conversations.create("user-a")
        invalid = self.briefs.upsert_active(
            "user-a",
            conversation["id"],
            {
                "destination": "南京",
                "start_date": "不是日期",
                "end_date": "2026-08-03",
            },
        )
        self.assertEqual(invalid["status"], "collecting")
        self.assertIn("start_date", invalid["missing_fields"])

        reversed_range = self.briefs.upsert_active(
            "user-a",
            conversation["id"],
            {
                "start_date": "2026-08-05",
                "end_date": "2026-08-03",
            },
        )
        self.assertEqual(reversed_range["status"], "collecting")
        self.assertEqual(reversed_range["missing_fields"], ["date_range"])

    def test_run_transitions_and_failed_transaction_rollback(self):
        run = self.create_run()
        running = self.runs.transition(run["id"], RunStatus.RUNNING)
        self.assertEqual(running["status"], "running")
        with self.assertRaises(ValueError):
            self.runs.transition(run["id"], RunStatus.QUEUED)
        self.assertEqual(self.runs.get_internal(run["id"])["status"], "running")

    def test_concurrent_event_sequences_are_monotonic(self):
        run = self.create_run()

        def append(index):
            return self.events.append(run["id"], "custom", {"index": index})

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append, range(30)))
        events = self.events.after(run["id"])
        self.assertEqual([event["sequence"] for event in events], list(range(1, 31)))
        self.assertEqual(len({event["payload"]["index"] for event in events}), 30)

    def test_wal_mode_and_indexes(self):
        with get_conn(self.db_path) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            indexes = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        self.assertIn("idx_runs_queue", indexes)
        self.assertIn("idx_run_events_replay", indexes)
