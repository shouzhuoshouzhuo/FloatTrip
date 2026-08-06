from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.database import get_conn, init_db
from app.core.memory import save_itinerary
from app.runtime.compat import (
    create_legacy_run, legacy_events, legacy_parent_constraint_snapshot,
)
from app.runtime.manager import RunManager


class RuntimeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "compat.db"
        init_db(self.db_path)
        with get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                ("owner", "owner", "hash", "2026-01-01"),
            )
        self.manager = RunManager(self.db_path)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_progress_and_result_keep_legacy_shape(self):
        run = create_legacy_run(
            self.manager,
            user_id="owner",
            query="云南五日游",
            overrides={"max_per_day": 3},
        )
        with get_conn(self.db_path) as conn:
            itinerary_id = save_itinerary(
                "owner",
                {
                    "destination": "云南",
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-05",
                    "days": [],
                },
                "云南五日游",
                conn,
            )
        self.manager.events.append(
            run["id"],
            "custom",
            {
                "kind": "planning_run.progress",
                "stage": "planner",
                "label": "正在规划逐日行程",
            },
        )
        self.manager.events.append(
            run["id"],
            "custom",
            {
                "kind": "planning.itinerary_created",
                "itinerary_id": itinerary_id,
                "destination": "云南",
            },
        )
        self.manager.runs.transition(
            run["id"], "running"
        )
        self.manager.runs.transition(
            run["id"], "succeeded", result_itinerary_id=itinerary_id
        )
        events = [event async for event in legacy_events(self.manager, run["id"])]
        self.assertEqual(events[0]["type"], "stage")
        self.assertEqual(events[0]["node"], "planner")
        self.assertTrue(events[1]["success"])
        self.assertEqual(events[1]["plan_id"], itinerary_id)

    async def test_revision_request_creates_distinct_revision_run(self):
        with get_conn(self.db_path) as conn:
            base_id = save_itinerary(
                "owner",
                {"destination": "成都", "days": []},
                "成都两日游",
                conn,
                planner_state={"query": "成都两日游", "route": [], "pois": []},
            )
        run = create_legacy_run(
            self.manager,
            user_id="owner",
            query="第三天松一点",
            overrides={},
            plan_id=base_id,
            modification_notes="第三天松一点",
        )
        self.assertEqual(run["kind"], "revision")
        self.assertEqual(
            run["request_snapshot"]["related_itinerary_id"], base_id
        )

    async def test_legacy_revision_can_inherit_parent_constraint_snapshot(self):
        parent = create_legacy_run(
            self.manager, user_id="owner", query="东京三日游", overrides={},
            projected_snapshot={
                "memory_profile_revision": 3,
                "effective_constraints": [{
                    "id": "memory:f1", "fact_id": "f1", "category": "travel_pace",
                    "value_text": "慢节奏", "polarity": "prefer", "source": "long_term_memory",
                }],
                "constraint_coverage": [{"constraint_id": "memory:f1", "status": "applied"}],
            },
        )
        with get_conn(self.db_path) as conn:
            itinerary_id = save_itinerary(
                "owner", {"destination": "东京", "days": []}, "东京三日游", conn,
                planner_state={"query": "东京三日游", "route": [], "pois": []},
            )
        self.manager.runs.transition(parent["id"], "running")
        self.manager.runs.transition(parent["id"], "succeeded", result_itinerary_id=itinerary_id)
        inherited = legacy_parent_constraint_snapshot(self.manager, "owner", itinerary_id)
        self.assertEqual(inherited["memory_profile_revision"], 3)
        revision = create_legacy_run(
            self.manager, user_id="owner", query="第二天更轻松", overrides={},
            plan_id=itinerary_id, modification_notes="第二天更轻松",
            projected_snapshot={**inherited, "constraint_snapshot_source": "parent_run"},
        )
        self.assertEqual(revision["request_snapshot"]["effective_constraints"][0]["fact_id"], "f1")
        self.assertEqual(revision["request_snapshot"]["constraint_snapshot_source"], "parent_run")
