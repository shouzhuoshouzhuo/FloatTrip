from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import TypedDict

from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.database import get_conn, init_db
from app.runtime.manager import RunManager
from app.runtime.models import RunKind
from app.runtime.worker import GraphRuntimeWorker


class FakeGraph:
    def __init__(self, parts):
        self.parts = parts
        self.calls = []

    async def astream(self, value, **kwargs):
        self.calls.append((value, kwargs))
        for part in self.parts:
            yield part


class RuntimeStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "runtime.db"
        init_db(self.db_path)
        with get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                ("user-a", "a", "hash", "2026-01-01"),
            )
            conn.execute(
                "INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("c", "user-a", "", "2026-01-01", "2026-01-01"),
            )
        self.manager = RunManager(self.db_path)
        self.run = self.manager.create(
            user_id="user-a",
            kind=RunKind.CHAT,
            conversation_id="c",
            request_snapshot={"text": "hi"},
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_only_allowlisted_messages_and_valid_custom_events_are_public(self):
        graph = FakeGraph(
            [
                {
                    "type": "messages",
                    "ns": (),
                    "data": (
                        AIMessageChunk(content="secret"),
                        {"langgraph_node": "classifier"},
                    ),
                },
                {
                    "type": "messages",
                    "ns": (),
                    "data": (
                        AIMessageChunk(content="你好"),
                        {"langgraph_node": "respond"},
                    ),
                },
                {
                    "type": "custom",
                    "ns": (),
                    "data": {
                        "kind": "planning_brief.ready",
                        "brief_id": "b",
                        "status": "ready",
                        "summary": {"destination": "云南"},
                        "missing_fields": [],
                    },
                },
                {
                    "type": "custom",
                    "ns": (),
                    "data": {"kind": "debug", "prompt": "do not leak"},
                },
                {
                    "type": "updates",
                    "ns": (),
                    "data": {
                        "reviewer": {
                            "reasoning": "chain-of-thought",
                            "profile": {"private": True},
                        }
                    },
                },
            ]
        )
        worker = GraphRuntimeWorker(
            self.manager,
            graph,
            lambda run: run["request_snapshot"],
            stream_messages=True,
        )
        await worker(self.run, __import__("asyncio").Event())
        live = list(self.manager.bridge._history[self.run["id"]])
        self.assertEqual(
            [item.payload.get("delta") for item in live if item.kind == "messages"],
            ["你好"],
        )
        serialized = repr([(item.kind, item.payload) for item in live])
        self.assertNotIn("secret", serialized)
        self.assertNotIn("chain-of-thought", serialized)
        self.assertNotIn("do not leak", serialized)
        self.assertEqual(graph.calls[0][1]["version"], "v2")
        self.assertEqual(
            graph.calls[0][1]["stream_mode"],
            ["messages", "custom", "updates", "values"],
        )

    async def test_checkpointed_interrupt_resumes_the_same_run(self):
        class State(TypedDict, total=False):
            answer: str

        def ask(_state):
            answer = interrupt(
                {
                    "question": "请补充日期",
                    "input_schema": {"type": "string"},
                }
            )
            return {"answer": answer}

        builder = StateGraph(State)
        builder.add_node("ask", ask)
        builder.add_edge(START, "ask")
        builder.add_edge("ask", END)
        checkpoint_path = str(Path(self.tmp.name) / "checkpoints.db")
        finalized = {}

        async def finalizer(_run, updates, _text):
            finalized.update(updates)
            return {}

        async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
            graph = builder.compile(checkpointer=saver)
            worker = GraphRuntimeWorker(
                self.manager,
                graph,
                lambda _run: {},
                stream_messages=False,
                finalizer=finalizer,
            )
            self.manager.runs.transition(self.run["id"], "running")
            await worker(self.manager.runs.get_internal(self.run["id"]), __import__("asyncio").Event())
            waiting = self.manager.runs.get_internal(self.run["id"])
            self.assertEqual(waiting["status"], "waiting_user")
            self.assertTrue(waiting["outstanding_interaction_id"])
            self.manager.runs.transition(self.run["id"], "running")
            await worker.resume(
                self.manager.runs.get_internal(self.run["id"]),
                __import__("asyncio").Event(),
                "2026-10-01 至 2026-10-05",
            )
        self.assertEqual(finalized["answer"], "2026-10-01 至 2026-10-05")

    async def test_finalizer_receives_latest_complete_values_snapshot(self):
        finalized = {}
        graph = FakeGraph(
            [
                {
                    "type": "updates",
                    "ns": (),
                    "data": {
                        "planner": {
                            "route": [{"day": 1}],
                            "status": "partial",
                        }
                    },
                },
                {
                    "type": "values",
                    "ns": (),
                    "data": {
                        "route": [{"day": 1}, {"day": 2}],
                        "pois": [{"name": "开元寺"}, {"name": "洛阳桥"}],
                        "status": "complete",
                        "final_plan": {"destination": "泉州"},
                    },
                },
            ]
        )

        async def finalizer(_run, updates, _text):
            finalized.update(updates)
            return {}

        worker = GraphRuntimeWorker(
            self.manager,
            graph,
            lambda run: run["request_snapshot"],
            stream_messages=False,
            finalizer=finalizer,
        )
        await worker(self.run, __import__("asyncio").Event())

        self.assertEqual(finalized["status"], "complete")
        self.assertEqual(len(finalized["route"]), 2)
        self.assertEqual(
            [poi["name"] for poi in finalized["pois"]],
            ["开元寺", "洛阳桥"],
        )
        self.assertEqual(finalized["final_plan"]["destination"], "泉州")
