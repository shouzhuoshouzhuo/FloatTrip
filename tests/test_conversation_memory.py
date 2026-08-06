from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.chat.memory_models import MemoryExtractionResult
from app.chat.memory_service import ChatMemoryService, MemoryExtractionWorker
from app.chat.prompts import dialogue_messages
from app.core.database import get_conn, init_db
from app.core.travel_memory import (
    ArchivedConversationError,
    ConversationMemoryRepository,
    MemoryJobRepository,
    MemoryRepository,
)
from app.runtime.repositories import ConversationRepository


class FakeAsyncLlm:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ConversationMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "memory.db"
        init_db(self.db_path)
        with get_conn(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                [
                    ("owner", "owner", "hash", "2026-01-01"),
                    ("other", "other", "hash", "2026-01-01"),
                ],
            )
        self.conversations = ConversationRepository(self.db_path)
        self.facts = MemoryRepository(self.db_path)
        self.states = ConversationMemoryRepository(self.db_path)
        self.jobs = MemoryJobRepository(self.db_path)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_latest_query_keeps_the_true_newest_rows_after_201_messages(self):
        conversation = self.conversations.create("owner")
        for sequence in range(1, 206):
            self.conversations.add_message(
                "owner", conversation["id"],
                "user" if sequence % 2 else "assistant",
                f"消息 {sequence}",
            )
        rows = self.conversations.recent_messages(
            "owner", conversation["id"], limit=200
        )
        self.assertEqual(len(rows), 200)
        self.assertEqual(rows[0]["sequence"], 6)
        self.assertEqual(rows[-1]["sequence"], 205)
        self.assertEqual(rows[-1]["content"], "消息 205")
        context_rows = self.conversations.context_messages(
            "owner", conversation["id"], oldest_limit=20, recent_limit=13
        )
        self.assertEqual(context_rows[0]["sequence"], 1)
        self.assertEqual(context_rows[-1]["sequence"], 205)

    def test_first_message_freezes_profile_and_new_conversation_gets_new_revision(self):
        initial = self.facts.create(
            "owner", category="travel_pace", value_text="喜欢慢节奏",
            polarity="prefer",
        )
        first_conversation = self.conversations.create("owner")
        with self.assertRaises(Exception):
            self.states.get("owner", first_conversation["id"])
        self.conversations.add_message(
            "owner", first_conversation["id"], "user", "帮我看看苏州"
        )
        frozen = self.states.get("owner", first_conversation["id"])
        self.assertEqual([fact["id"] for fact in frozen["profile_snapshot"]], [initial["id"]])

        self.facts.create(
            "owner", category="food_preference", value_text="偏爱清淡",
            polarity="prefer",
        )
        unchanged = self.states.get("owner", first_conversation["id"])
        self.assertEqual(unchanged["profile_revision"], frozen["profile_revision"])
        self.assertEqual(len(unchanged["profile_snapshot"]), 1)

        next_conversation = self.conversations.create("owner")
        self.conversations.add_message(
            "owner", next_conversation["id"], "user", "再聊聊杭州"
        )
        latest = self.states.get("owner", next_conversation["id"])
        self.assertGreater(latest["profile_revision"], frozen["profile_revision"])
        self.assertEqual(len(latest["profile_snapshot"]), 2)

    def test_fact_lifecycle_keeps_edit_history_and_increments_revision(self):
        start_revision = self.facts.revision("owner")
        candidate = self.facts.create(
            "owner", category="companion_context", value_text="通常带孩子出行",
            status="candidate", source_kind="inferred_chat",
        )
        self.assertEqual(self.facts.revision("owner"), start_revision)
        approved = self.facts.approve("owner", candidate["id"])
        after_approve = self.facts.revision("owner")
        self.assertEqual(approved["status"], "active")
        self.assertGreater(after_approve, start_revision)

        replacement = self.facts.replace(
            "owner", approved["id"], value_text="通常和孩子一起旅行",
            scope_type="companion", scope_key={"companion": "child"},
        )
        self.assertEqual(replacement["supersedes_id"], approved["id"])
        self.assertEqual(self.facts.get("owner", approved["id"])["status"], "superseded")
        self.assertGreater(self.facts.revision("owner"), after_approve)

        before_delete = self.facts.revision("owner")
        deleted = self.facts.delete("owner", replacement["id"])
        self.assertEqual(deleted["status"], "deleted")
        self.assertGreater(self.facts.revision("owner"), before_delete)
        with self.assertRaises(Exception):
            self.facts.get("other", replacement["id"])

    def test_replayed_extraction_cannot_resurrect_a_forgotten_fact(self):
        fact = self.facts.create(
            "owner", category="food_preference", value_text="喜欢甜食",
            polarity="prefer", source_kind="explicit_chat",
        )
        self.facts.delete("owner", fact["id"])
        revision = self.facts.revision("owner")
        replayed = self.facts.create(
            "owner", category="food_preference", value_text="喜欢甜食",
            polarity="prefer", source_kind="explicit_chat",
        )
        self.assertEqual(replayed["status"], "deleted")
        self.assertEqual(self.facts.revision("owner"), revision)

    async def test_compression_enqueues_extraction_and_keeps_six_complete_turns(self):
        conversation = self.conversations.create("owner")
        for turn in range(10):
            self.conversations.add_message(
                "owner", conversation["id"], "user", f"第 {turn} 轮用户要求 " + "古城" * 20
            )
            self.conversations.add_message(
                "owner", conversation["id"], "assistant", f"第 {turn} 轮助手回复 " + "收到" * 20
            )
        current = self.conversations.add_message(
            "owner", conversation["id"], "user", "当前只想纠正为不要夜游"
        )
        llm = FakeAsyncLlm([
            {
                "topics": ["古城旅行"],
                "confirmed_constraints": [],
                "negative_constraints": ["不要夜游"],
                "preferences_and_corrections": [],
                "open_questions": ["日期未定"],
                "decisions": [],
                "source_sequence_range": {"from_sequence": 1, "through_sequence": 8},
            }
        ])
        service = ChatMemoryService(self.db_path, summary_llm=llm)
        service.summary_trigger = 600
        service.context_budget = 1800
        context = await service.prepare(
            {
                "user_id": "owner",
                "conversation_id": conversation["id"],
                "request_snapshot": {"message_id": current["id"], "text": current["content"]},
            },
            application_state={
                "today": "2026-08-06", "timezone": "Asia/Shanghai",
                "planning_brief": None, "available_targets": [], "explicit_target": {},
            },
        )
        self.assertEqual(context["current_message"], current["content"])
        self.assertNotIn(current["id"], {row.get("id") for row in context["history"]})
        self.assertEqual(len(context["history"]), 12)
        self.assertEqual(context["history"][0]["content"], "第 4 轮用户要求 " + "古城" * 20)
        state = self.states.get("owner", conversation["id"])
        self.assertEqual(state["summarized_through_sequence"], 8)
        self.assertEqual(state["summary_count"], 1)
        with get_conn(self.db_path) as conn:
            job = conn.execute(
                "SELECT * FROM memory_extraction_jobs WHERE conversation_id=? AND kind='pre_summary'",
                (conversation["id"],),
            ).fetchone()
        self.assertIsNotNone(job)
        self.assertEqual((job["from_sequence"], job["through_sequence"]), (1, 8))

    async def test_summary_failure_keeps_old_state_and_uses_latest_budgeted_history(self):
        conversation = self.conversations.create("owner")
        for turn in range(10):
            self.conversations.add_message(
                "owner", conversation["id"], "user", f"用户 {turn} " + "景点" * 30
            )
            self.conversations.add_message(
                "owner", conversation["id"], "assistant", f"助手 {turn} " + "回答" * 30
            )
        current = self.conversations.add_message("owner", conversation["id"], "user", "当前消息")
        service = ChatMemoryService(
            self.db_path, summary_llm=FakeAsyncLlm([RuntimeError("summary down")])
        )
        service.summary_trigger = 600
        service.context_budget = 1000
        context = await service.prepare(
            {
                "user_id": "owner", "conversation_id": conversation["id"],
                "request_snapshot": {"message_id": current["id"], "text": current["content"]},
            },
            application_state={
                "today": "2026-08-06", "timezone": "Asia/Shanghai",
                "planning_brief": None, "available_targets": [], "explicit_target": {},
            },
        )
        state = self.states.get("owner", conversation["id"])
        self.assertEqual(state["summary_count"], 0)
        self.assertIsNone(state["summary"])
        self.assertEqual(context["history"][-1]["content"], "助手 9 " + "回答" * 30)
        self.assertLess(len(context["history"]), 20)

    async def test_extraction_validates_sensitivity_evidence_and_idempotency(self):
        old = self.facts.create(
            "owner", category="travel_pace", value_text="喜欢赶行程", polarity="prefer"
        )
        conversation = self.conversations.create("owner")
        first = self.conversations.add_message(
            "owner", conversation["id"], "user",
            "我更喜欢慢慢玩，也喜欢博物馆；我对花生过敏。"
        )
        second = self.conversations.add_message(
            "owner", conversation["id"], "assistant", "收到。"
        )
        result = {
            "items": [
                {
                    "action": "replace", "category": "travel_pace",
                    "value_text": "喜欢慢节奏", "polarity": "prefer",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "explicit", "sensitivity": "normal",
                    "evidence_sequences": [first["sequence"]],
                    "supersedes_fact_ids": [old["id"]],
                },
                {
                    "action": "add", "category": "attraction_preference",
                    "value_text": "喜欢博物馆", "polarity": "prefer",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "explicit", "sensitivity": "normal",
                    "evidence_sequences": [first["sequence"]], "supersedes_fact_ids": [],
                },
                {
                    "action": "add", "category": "dietary_requirement",
                    "value_text": "花生过敏", "polarity": "require",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "explicit", "sensitivity": "protected",
                    "evidence_sequences": [first["sequence"]], "supersedes_fact_ids": [],
                },
                {
                    "action": "candidate", "category": "companion_context",
                    "value_text": "可能经常带孩子", "polarity": "fact",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "inferred", "sensitivity": "normal",
                    "evidence_sequences": [first["sequence"]], "supersedes_fact_ids": [],
                },
                {
                    "action": "add", "category": "other_travel_preference",
                    "value_text": "邮箱 test@example.com", "polarity": "fact",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "explicit", "sensitivity": "normal",
                    "evidence_sequences": [first["sequence"]], "supersedes_fact_ids": [],
                },
                {
                    "action": "add", "category": "transport_preference",
                    "value_text": "喜欢高铁", "polarity": "prefer",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "explicit", "sensitivity": "normal",
                    "evidence_sequences": [999], "supersedes_fact_ids": [],
                },
                {
                    "action": "add", "category": "budget_style",
                    "value_text": "这次预算3000元", "polarity": "fact",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "explicit", "sensitivity": "normal",
                    "evidence_sequences": [first["sequence"]], "supersedes_fact_ids": [],
                },
                {
                    "action": "add", "category": "companion_context",
                    "value_text": "同行孩子叫做小明，8岁", "polarity": "fact",
                    "scope_type": "global", "scope_key": {},
                    "explicitness": "explicit", "sensitivity": "normal",
                    "evidence_sequences": [first["sequence"]], "supersedes_fact_ids": [],
                },
            ]
        }
        job = self.jobs.enqueue(
            "owner", conversation["id"], "archive", first["sequence"], second["sequence"]
        )
        worker = MemoryExtractionWorker(self.db_path, llm=FakeAsyncLlm([result, result]))
        await worker.process(job)
        await worker.process(job)
        facts = self.facts.list("owner", statuses={"active", "candidate", "superseded"})
        active_values = {fact["value_text"] for fact in facts if fact["status"] == "active"}
        candidate_values = {fact["value_text"] for fact in facts if fact["status"] == "candidate"}
        self.assertIn("喜欢慢节奏", active_values)
        self.assertIn("喜欢博物馆", active_values)
        self.assertIn("花生过敏", candidate_values)
        self.assertIn("可能经常带孩子", candidate_values)
        self.assertNotIn("邮箱 test@example.com", {fact["value_text"] for fact in facts})
        self.assertNotIn("喜欢高铁", {fact["value_text"] for fact in facts})
        self.assertNotIn("这次预算3000元", {fact["value_text"] for fact in facts})
        self.assertNotIn("同行孩子叫做小明，8岁", {fact["value_text"] for fact in facts})
        self.assertEqual(sum(fact["value_text"] == "喜欢博物馆" for fact in facts), 1)
        self.assertEqual(self.facts.get("owner", old["id"])["status"], "superseded")

    def test_archive_is_idempotent_read_only_and_creates_final_job(self):
        conversation = self.conversations.create("owner")
        self.conversations.add_message("owner", conversation["id"], "user", "喜欢自然风光")
        self.states.update_summary(
            "owner", conversation["id"],
            {
                "topics": ["自然旅行"], "confirmed_constraints": [],
                "negative_constraints": [], "preferences_and_corrections": [],
                "open_questions": [], "decisions": [],
                "source_sequence_range": {"from_sequence": 1, "through_sequence": 1},
            },
            1,
            500,
        )
        archived = self.conversations.archive("owner", conversation["id"])
        again = self.conversations.archive("owner", conversation["id"])
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(again["archived_at"], archived["archived_at"])
        self.assertEqual(archived["finalization_status"], "pending")
        with get_conn(self.db_path) as conn:
            job = conn.execute(
                "SELECT from_sequence,through_sequence FROM memory_extraction_jobs "
                "WHERE conversation_id=? AND kind='archive'",
                (conversation["id"],),
            ).fetchone()
        self.assertEqual((job["from_sequence"], job["through_sequence"]), (1, 1))
        with self.assertRaises(ArchivedConversationError):
            self.conversations.add_message(
                "owner", conversation["id"], "user", "不应写入"
            )

    def test_archive_job_retries_five_times_and_can_be_manually_requeued(self):
        conversation = self.conversations.create("owner")
        self.conversations.add_message("owner", conversation["id"], "user", "喜欢自然风光")
        self.conversations.archive("owner", conversation["id"])
        claimed = None
        for attempt in range(5):
            if attempt:
                with get_conn(self.db_path) as conn:
                    conn.execute(
                        "UPDATE memory_extraction_jobs SET next_attempt_at=NULL "
                        "WHERE conversation_id=? AND kind='archive'",
                        (conversation["id"],),
                    )
            claimed = self.jobs.claim_next()
            self.assertIsNotNone(claimed)
            self.jobs.fail(claimed["id"], "ProviderError")
        with get_conn(self.db_path) as conn:
            failed = conn.execute(
                "SELECT * FROM memory_extraction_jobs WHERE id=?", (claimed["id"],)
            ).fetchone()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 5)
        self.assertEqual(
            self.states.get("owner", conversation["id"])["finalization_status"],
            "failed",
        )
        retried = self.jobs.retry_archive("owner", conversation["id"])
        self.assertEqual(retried["status"], "pending")
        self.assertEqual(retried["attempts"], 0)

    def test_prompt_order_preserves_roles_and_marks_memory_as_data(self):
        messages = dialogue_messages(
            {
                "today": "2026-08-06", "timezone": "Asia/Shanghai",
                "profile_revision": 3,
                "profile_snapshot": [{"value_text": "喜欢早起"}],
                "conversation_summary": {"negative_constraints": ["不要早起"]},
                "application_state": {"planning_brief": {"destination": "苏州"}},
                "history": [
                    {"role": "user", "content": "其实这次不要早起"},
                    {"role": "assistant", "content": "明白"},
                ],
                "current_message": "改成下午出发",
            }
        )
        self.assertEqual([message.type for message in messages[:2]], ["system", "system"])
        self.assertEqual(messages[2].name, "long_term_memory")
        self.assertEqual(messages[3].name, "conversation_summary")
        self.assertEqual(messages[4].name, "application_state")
        self.assertEqual([message.type for message in messages[-3:]], ["human", "ai", "human"])
        self.assertIn("只读数据", messages[0].content)
        self.assertEqual(messages[-1].content, "改成下午出发")

    def test_archive_extraction_is_chunked_for_very_long_conversations(self):
        messages = [
            {"sequence": 1, "role": "user", "content": "旅" * 700},
            {"sequence": 2, "role": "assistant", "content": "答" * 700},
        ]
        with patch.dict(os.environ, {"MEMORY_EXTRACTION_INPUT_TOKENS": "1000"}):
            chunks = MemoryExtractionWorker._extraction_chunks(messages)
        self.assertEqual([[row["sequence"] for row in chunk] for chunk in chunks], [[1], [2]])


class LegacyMemoryMigrationTests(unittest.TestCase):
    def test_legacy_preferences_are_active_but_visited_destinations_are_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            init_db(db_path)
            with get_conn(db_path) as conn:
                conn.execute(
                    "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                    ("owner", "owner", "hash", "2026-01-01"),
                )
                conn.execute(
                    "INSERT INTO user_profiles(user_id,attraction_prefs,food_prefs,habit_prefs,visited_destinations,updated_at) "
                    "VALUES(?,?,?,?,?,?)",
                    ("owner", '["博物馆"]', '["清淡"]', '["慢节奏"]', '["日本"]', "2026-01-01"),
                )
            init_db(db_path)
            init_db(db_path)
            facts = MemoryRepository(db_path).list(
                "owner", statuses={"active", "candidate"}
            )
            self.assertEqual(len(facts), 4)
            visited = next(fact for fact in facts if fact["category"] == "destination_history")
            self.assertEqual(visited["status"], "candidate")
            self.assertEqual(visited["source_kind"], "legacy")
            self.assertTrue(all(
                fact["status"] == "active"
                for fact in facts if fact["category"] != "destination_history"
            ))
