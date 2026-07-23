from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.auth import create_token
from app.core.database import configure_database, get_conn, get_db_path, init_db


class RuntimeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.main import app

        cls.app = app

    def setUp(self):
        self.original_path = get_db_path()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "api.db"
        configure_database(self.db_path)
        init_db()
        with get_conn() as conn:
            conn.executemany(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                [
                    ("owner", "owner", "hash", "2026-01-01"),
                    ("other", "other", "hash", "2026-01-01"),
                ],
            )
        self.client = TestClient(self.app)
        self.owner_headers = {"Authorization": f"Bearer {create_token('owner')}"}
        self.other_headers = {"Authorization": f"Bearer {create_token('other')}"}

    def tearDown(self):
        self.client.close()
        configure_database(self.original_path)
        self.tmp.cleanup()

    def test_conversation_message_and_cross_user_isolation(self):
        conversation = self.client.post(
            "/api/conversations",
            headers=self.owner_headers,
            json={"title": "云南"},
        ).json()
        with patch("app.api.runtime_routes.scheduler.notify"):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                headers=self.owner_headers,
                json={"content": "帮我规划云南五日游"},
            )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["message"]["sequence"], 1)
        self.assertEqual(body["run"]["status"], "queued")
        self.assertEqual(
            self.client.get(
                f"/api/conversations/{conversation['id']}",
                headers=self.other_headers,
            ).status_code,
            404,
        )

    def test_brief_submission_is_idempotent_and_creates_one_run(self):
        conversation = self.client.post(
            "/api/conversations", headers=self.owner_headers, json={}
        ).json()
        from app.runtime.repositories import PlanningBriefRepository

        brief = PlanningBriefRepository().upsert_active(
            "owner",
            conversation["id"],
            {
                "destination": "云南",
                "days": 5,
                "start_date": "2026-10-01",
                "end_date": "2026-10-05",
            },
        )
        with patch("app.api.runtime_routes.scheduler.notify"):
            first = self.client.post(
                f"/api/planning-briefs/{brief['id']}/submit",
                headers=self.owner_headers,
            )
            second = self.client.post(
                f"/api/planning-briefs/{brief['id']}/submit",
                headers=self.owner_headers,
            )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["run"]["id"], second.json()["run"]["id"])
        runs = self.client.get("/api/runs", headers=self.owner_headers).json()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["request_snapshot"]["destination"], "云南")

    def test_cancel_retry_event_history_and_completed_replay(self):
        with patch("app.api.runtime_routes.scheduler.notify"):
            run = self.client.post(
                "/api/runs",
                headers=self.owner_headers,
                json={
                    "kind": "travel_plan",
                    "request": {
                        "destination": "成都",
                        "days": 2,
                        "start_date": "2026-08-01",
                        "end_date": "2026-08-02",
                    },
                },
            ).json()
        cancelled = self.client.post(
            f"/api/runs/{run['id']}/cancel", headers=self.owner_headers
        )
        self.assertEqual(cancelled.json()["status"], "cancelled")
        again = self.client.post(
            f"/api/runs/{run['id']}/cancel", headers=self.owner_headers
        )
        self.assertEqual(again.status_code, 200)
        with patch("app.api.runtime_routes.scheduler.notify"):
            retried = self.client.post(
                f"/api/runs/{run['id']}/retry", headers=self.owner_headers
            )
        self.assertEqual(retried.status_code, 202)
        self.assertEqual(retried.json()["retry_of_run_id"], run["id"])
        events = self.client.get(
            f"/api/runs/{run['id']}/events?after_seq=0",
            headers=self.owner_headers,
        ).json()
        self.assertEqual([event["kind"] for event in events], ["custom", "end"])
        with self.client.stream(
            "GET",
            f"/api/runs/{run['id']}/stream",
            headers=self.owner_headers,
        ) as response:
            text = "".join(response.iter_text())
        self.assertIn("event: custom", text)
        self.assertIn("event: end", text)

    def test_direct_start_requires_complete_request(self):
        response = self.client.post(
            "/api/runs",
            headers=self.owner_headers,
            json={"kind": "travel_plan", "request": {"destination": "北京"}},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("start_date", str(response.json()))
        self.assertIn("end_date", str(response.json()))
