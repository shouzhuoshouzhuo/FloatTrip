"""SQLite repositories for conversations, briefs, runs, and events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.database import get_conn
from app.core.planning_brief import required_brief_fields
from app.runtime.models import (
    DisconnectPolicy,
    RunKind,
    RunStatus,
    TERMINAL_STATUSES,
    validate_transition,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


class OwnedResourceNotFound(LookupError):
    pass


class ConversationRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path

    def create(self, user_id: str, title: str = "") -> dict[str, Any]:
        conversation_id = str(uuid.uuid4())
        now = utcnow()
        with get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                (conversation_id, user_id, title.strip(), now, now),
            )
        return self.get(user_id, conversation_id)

    def get(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
        if not row:
            raise OwnedResourceNotFound("conversation not found")
        return dict(row)

    def list(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE user_id=? "
                "ORDER BY updated_at DESC,id DESC LIMIT ?",
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        *,
        related_run_id: str | None = None,
        related_itinerary_id: str | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("invalid message role")
        message_id = str(uuid.uuid4())
        now = utcnow()
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute(
                "SELECT title FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
            if not owner:
                raise OwnedResourceNotFound("conversation not found")
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO messages(id,conversation_id,user_id,role,content,sequence,"
                "related_run_id,related_itinerary_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    conversation_id,
                    user_id,
                    role,
                    content,
                    sequence,
                    related_run_id,
                    related_itinerary_id,
                    now,
                ),
            )
            auto_title = (
                content.strip()[:24]
                if role == "user"
                and sequence == 1
                and str(owner["title"] or "").strip() in {"", "新的旅行对话"}
                else None
            )
            if auto_title:
                conn.execute(
                    "UPDATE conversations SET title=?,updated_at=? WHERE id=?",
                    (auto_title, now, conversation_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?",
                    (now, conversation_id),
                )
        return {
            "id": message_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "sequence": sequence,
            "related_run_id": related_run_id,
            "related_itinerary_id": related_itinerary_id,
            "created_at": now,
        }

    def messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.get(user_id, conversation_id)
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                (conversation_id, max(0, after_sequence), max(1, min(limit, 200))),
            ).fetchall()
        return [dict(row) for row in rows]


class PlanningBriefRepository:
    ACTIVE = {"collecting", "ready"}
    ALLOWED = {
        "collecting": {"collecting", "ready", "discarded"},
        "ready": {"collecting", "ready", "submitted", "discarded"},
        "submitted": {"submitted"},
        "discarded": {"discarded"},
    }

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path

    @staticmethod
    def required_missing(data: dict[str, Any]) -> list[str]:
        return required_brief_fields(data)

    def _decode(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["data"] = _loads(result.pop("data_json"), {})
        result["missing_fields"] = _loads(result.pop("missing_fields_json"), [])
        result["submission_snapshot"] = _loads(
            result.pop("submission_snapshot_json"), None
        )
        return result

    def get(self, user_id: str, brief_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE id=? AND user_id=?",
                (brief_id, user_id),
            ).fetchone()
        if not row:
            raise OwnedResourceNotFound("planning brief not found")
        return self._decode(row)

    def active_for_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE conversation_id=? AND user_id=? "
                "AND status IN ('collecting','ready') ORDER BY updated_at DESC LIMIT 1",
                (conversation_id, user_id),
            ).fetchone()
        return self._decode(row) if row else None

    def latest_for_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        """Return the latest brief, including an already submitted one.

        This preserves the idempotent result for a duplicate natural-language
        confirmation after the active brief has been frozen.
        """
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE conversation_id=? AND user_id=? "
                "ORDER BY updated_at DESC,id DESC LIMIT 1",
                (conversation_id, user_id),
            ).fetchone()
        return self._decode(row) if row else None

    def upsert_active(
        self,
        user_id: str,
        conversation_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        now = utcnow()
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
            if not owner:
                raise OwnedResourceNotFound("conversation not found")
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE conversation_id=? AND user_id=? "
                "AND status IN ('collecting','ready') LIMIT 1",
                (conversation_id, user_id),
            ).fetchone()
            data = _loads(row["data_json"], {}) if row else {}
            data.update({key: value for key, value in patch.items() if value is not None})
            missing = self.required_missing(data)
            status = "collecting" if missing else "ready"
            if row:
                brief_id = row["id"]
                conn.execute(
                    "UPDATE planning_briefs SET status=?,data_json=?,missing_fields_json=?,updated_at=? "
                    "WHERE id=?",
                    (status, _json(data), _json(missing), now, brief_id),
                )
            else:
                brief_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO planning_briefs(id,conversation_id,user_id,status,data_json,"
                    "missing_fields_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        brief_id,
                        conversation_id,
                        user_id,
                        status,
                        _json(data),
                        _json(missing),
                        now,
                        now,
                    ),
                )
        return self.get(user_id, brief_id)

    def transition(
        self, user_id: str, brief_id: str, target: str
    ) -> dict[str, Any]:
        current = self.get(user_id, brief_id)
        if target not in self.ALLOWED[current["status"]]:
            raise ValueError(f"invalid brief transition: {current['status']} -> {target}")
        if target == "submitted":
            raise ValueError("use submit() to preserve immutable snapshot")
        now = utcnow()
        with get_conn(self.db_path) as conn:
            conn.execute(
                "UPDATE planning_briefs SET status=?,updated_at=? WHERE id=? AND user_id=?",
                (target, now, brief_id, user_id),
            )
        return self.get(user_id, brief_id)

    def submit(
        self,
        user_id: str,
        brief_id: str,
        create_run,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically freeze a ready brief and create or return its run."""
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE id=? AND user_id=?",
                (brief_id, user_id),
            ).fetchone()
            if not row:
                raise OwnedResourceNotFound("planning brief not found")
            if row["status"] == "submitted" and row["submitted_run_id"]:
                run = conn.execute(
                    "SELECT * FROM runs WHERE id=?", (row["submitted_run_id"],)
                ).fetchone()
                return self._decode(row), _decode_run(run)
            if row["status"] != "ready":
                raise ValueError("planning brief is not ready")
            snapshot = _loads(row["data_json"], {})
            run = create_run(conn, snapshot, row["conversation_id"])
            now = utcnow()
            conn.execute(
                "UPDATE planning_briefs SET status='submitted',submission_snapshot_json=?,"
                "submitted_run_id=?,submitted_at=?,updated_at=? WHERE id=?",
                (_json(snapshot), run["id"], now, now, brief_id),
            )
        return self.get(user_id, brief_id), run


def _decode_run(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        raise OwnedResourceNotFound("run not found")
    result = dict(row)
    result["request_snapshot"] = _loads(result.pop("request_snapshot_json"), {})
    result["error_public"] = _loads(result.pop("error_public_json"), None)
    return result


class RunRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path

    def insert(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        user_id: str,
        kind: RunKind | str,
        concurrency_key: str,
        request_snapshot: dict[str, Any],
        conversation_id: str | None = None,
        disconnect_policy: DisconnectPolicy | str = DisconnectPolicy.CONTINUE,
        retry_of_run_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        conn.execute(
            "INSERT INTO runs(id,user_id,conversation_id,kind,status,concurrency_key,"
            "request_snapshot_json,disconnect_policy,retry_of_run_id,created_at,queued_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                user_id,
                conversation_id,
                RunKind(kind).value,
                RunStatus.QUEUED.value,
                concurrency_key,
                _json(request_snapshot),
                DisconnectPolicy(disconnect_policy).value,
                retry_of_run_id,
                now,
                now,
                now,
            ),
        )
        return _decode_run(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def get(self, user_id: str, run_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id=? AND user_id=?", (run_id, user_id)
            ).fetchone()
        if not row:
            raise OwnedResourceNotFound("run not found")
        return _decode_run(row)

    def get_internal(self, run_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            return _decode_run(
                conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            )

    def list(
        self,
        user_id: str,
        *,
        conversation_id: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id=?"]
        args: list[Any] = [user_id]
        if conversation_id:
            clauses.append("conversation_id=?")
            args.append(conversation_id)
        if active_only:
            clauses.append("status IN ('queued','running','waiting_user')")
        args.append(max(1, min(limit, 200)))
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM runs WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at DESC,id DESC LIMIT ?",
                args,
            ).fetchall()
        return [_decode_run(row) for row in rows]

    def transition(
        self,
        run_id: str,
        target: RunStatus | str,
        *,
        expected: set[RunStatus | str] | None = None,
        error_public: dict[str, Any] | None = None,
        error_internal: str | None = None,
        result_itinerary_id: str | None = None,
        outstanding_interaction_id: str | None = None,
    ) -> dict[str, Any]:
        target_status = RunStatus(target)
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise OwnedResourceNotFound("run not found")
            current = RunStatus(row["status"])
            if expected and current not in {RunStatus(value) for value in expected}:
                raise ValueError(f"run status is {current.value}")
            validate_transition(current, target_status)
            now = utcnow()
            started_at = now if target_status is RunStatus.RUNNING and not row["started_at"] else row["started_at"]
            finished_at = now if target_status in TERMINAL_STATUSES else None
            interaction = (
                outstanding_interaction_id
                if target_status is RunStatus.WAITING_USER
                else None
            )
            conn.execute(
                "UPDATE runs SET status=?,started_at=?,finished_at=?,updated_at=?,"
                "error_public_json=?,error_internal=?,result_itinerary_id=COALESCE(?,result_itinerary_id),"
                "outstanding_interaction_id=? WHERE id=?",
                (
                    target_status.value,
                    started_at,
                    finished_at,
                    now,
                    _json(error_public) if error_public else None,
                    error_internal,
                    result_itinerary_id,
                    interaction,
                    run_id,
                ),
            )
            return _decode_run(
                conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            )

    def queued(self, limit: int = 100) -> list[dict[str, Any]]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status='queued' ORDER BY queued_at,id LIMIT ?",
                (limit,),
            ).fetchall()
        return [_decode_run(row) for row in rows]

    def orphaned_active(self) -> list[dict[str, Any]]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status IN ('running','waiting_user') "
                "ORDER BY updated_at,id"
            ).fetchall()
        return [_decode_run(row) for row in rows]


class RunEventRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path

    def append(
        self,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        durable: bool = True,
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        now = utcnow()
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
                raise OwnedResourceNotFound("run not found")
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM run_events WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO run_events(id,run_id,sequence,kind,payload_json,durable,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (event_id, run_id, sequence, kind, _json(payload), int(durable), now),
            )
        return {
            "id": event_id,
            "run_id": run_id,
            "sequence": sequence,
            "kind": kind,
            "payload": payload,
            "durable": durable,
            "created_at": now,
        }

    def after(
        self, run_id: str, after_sequence: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE run_id=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                (run_id, max(0, after_sequence), max(1, min(limit, 1000))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = _loads(item.pop("payload_json"), {})
            item["durable"] = bool(item["durable"])
            result.append(item)
        return result
