from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.chat.planning_memory import PlanningMemoryMatcher
from app.core.database import get_conn, init_db
from app.core.travel_memory import MemoryRepository
from app.runtime.repositories import ConversationRepository, PlanningBriefRepository


class FakeLlm:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class PlanningMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "planning-memory.db"
        init_db(self.db_path)
        with get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES('u','u','h','2026')"
            )
        self.facts = MemoryRepository(self.db_path)
        self.japan = self.facts.create(
            "u", category="attraction_preference", value_text="去日本时喜欢温泉",
            polarity="prefer", scope_type="destination", scope_key={"destination": "日本"},
        )
        self.allergy = self.facts.create(
            "u", category="dietary_requirement", value_text="需要避开花生",
            polarity="require", sensitivity="protected", status="active",
        )
        self.facts.create(
            "u", category="travel_pace", value_text="可能喜欢赶景点",
            polarity="prefer", status="candidate",
        )
        self.conversation = ConversationRepository(self.db_path).create("u")
        ConversationRepository(self.db_path).add_message(
            "u", self.conversation["id"], "user", "东京三日游"
        )
        self.brief = PlanningBriefRepository(self.db_path).upsert_active(
            "u", self.conversation["id"], {"destination": "东京"}
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def decisions(self):
        return {
            "decisions": [
                {
                    "fact_id": self.japan["id"], "decision": "apply",
                    "application_level": "preference", "reason_code": "scope_match",
                },
                {
                    "fact_id": self.allergy["id"], "decision": "apply",
                    "application_level": "hard", "reason_code": "supports_current_trip",
                },
            ]
        }

    async def test_semantic_match_uses_only_frozen_active_facts_and_marks_hard_unverified(self):
        llm = FakeLlm([self.decisions()])
        matcher = PlanningMemoryMatcher(self.db_path, llm=llm)
        result = await matcher.refresh("u", self.brief["id"])
        self.assertEqual(result["memory_context"]["status"], "succeeded")
        self.assertEqual(
            {item["fact_id"] for item in result["memory_context"]["applied_facts"]},
            {self.japan["id"], self.allergy["id"]},
        )
        allergy_coverage = next(
            item for item in result["constraint_coverage"]
            if item.get("fact_id") == self.allergy["id"]
        )
        self.assertEqual(allergy_coverage["status"], "unverified")
        self.assertNotIn("可能喜欢赶景点", str(llm.calls))

        reloaded = PlanningBriefRepository(self.db_path).active_for_conversation(
            "u", self.conversation["id"]
        )
        self.assertEqual(reloaded["memory_context"]["status"], "succeeded")
        self.assertEqual(
            {item["fact_id"] for item in reloaded["memory_context"]["applied_facts"]},
            {self.japan["id"], self.allergy["id"]},
        )
        self.assertEqual(len(reloaded["effective_constraints"]), 2)

    async def test_trip_exclusion_does_not_change_fact_or_revision(self):
        matcher = PlanningMemoryMatcher(self.db_path, llm=FakeLlm([self.decisions(), self.decisions()]))
        await matcher.refresh("u", self.brief["id"])
        before = self.facts.revision("u")
        PlanningBriefRepository(self.db_path).upsert_active(
            "u", self.conversation["id"],
            {"excluded_memory_fact_ids": [self.japan["id"]]},
        )
        result = await matcher.refresh("u", self.brief["id"])
        self.assertEqual(self.facts.revision("u"), before)
        self.assertNotIn(
            self.japan["id"],
            {item["fact_id"] for item in result["memory_context"]["applied_facts"]},
        )
        self.assertEqual(self.facts.get("u", self.japan["id"])["status"], "active")

    async def test_invalid_model_ids_fail_safely_and_stale_fingerprint_cannot_commit(self):
        matcher = PlanningMemoryMatcher(
            self.db_path,
            llm=FakeLlm([{"decisions": [{
                "fact_id": "other-user", "decision": "apply",
                "application_level": "preference", "reason_code": "scope_match",
            }]}]),
        )
        result = await matcher.refresh("u", self.brief["id"])
        self.assertEqual(result["memory_context"]["status"], "failed")
        self.assertEqual(result["memory_context"]["applied_facts"], [])
        self.assertFalse(
            PlanningBriefRepository(self.db_path).complete_memory_match(
                "u", self.brief["id"], "stale", {"decisions": []}
            )
        )


if __name__ == "__main__":
    unittest.main()
