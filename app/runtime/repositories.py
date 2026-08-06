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
from app.core.planning_constraints import build_brief_projection, normalize_brief_data
from app.core.travel_memory import (
    ArchivedConversationError,
    ConversationMemoryRepository,
    MemoryJobRepository,
    utcnow as memory_utcnow,
)
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
    _ATTENTION_COLUMNS = """
        CASE WHEN c.status='active' AND EXISTS(
            SELECT 1 FROM runs r
            WHERE r.conversation_id=c.id AND r.user_id=c.user_id
              AND r.kind IN ('travel_plan','revision')
              AND r.status IN ('queued','running')
        ) THEN 1 ELSE 0 END AS has_active_planning,
        CASE WHEN c.status='active' AND EXISTS(
            SELECT 1 FROM runs r
            WHERE r.conversation_id=c.id AND r.user_id=c.user_id
              AND r.kind IN ('travel_plan','revision')
              AND r.status='waiting_user'
        ) THEN 1 ELSE 0 END AS has_waiting_user,
        CASE WHEN c.status='active' AND EXISTS(
            SELECT 1 FROM planning_briefs pb
            WHERE pb.conversation_id=c.id AND pb.user_id=c.user_id
              AND pb.status='ready'
        ) THEN 1 ELSE 0 END AS has_ready_brief,
        CASE WHEN c.status='active' AND EXISTS(
            SELECT 1 FROM runs r
            WHERE r.conversation_id=c.id AND r.user_id=c.user_id
              AND r.kind IN ('travel_plan','revision')
              AND r.status='succeeded'
              AND COALESCE(r.finished_at,r.updated_at,r.created_at)
                    > COALESCE(c.last_viewed_at,c.created_at)
        ) THEN 1 ELSE 0 END AS has_unread_completed
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field in (
            "has_active_planning",
            "has_waiting_user",
            "has_ready_brief",
            "has_unread_completed",
        ):
            result[field] = bool(result.get(field))
        return result

    def create(self, user_id: str, title: str = "") -> dict[str, Any]:
        conversation_id = str(uuid.uuid4())
        now = utcnow()
        with get_conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO conversations(id,user_id,title,last_viewed_at,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (conversation_id, user_id, title.strip(), now, now, now),
            )
        return self.get(user_id, conversation_id)

    def get(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT c.*,COALESCE(cm.finalization_status,'none') AS finalization_status,"
                "cm.last_error_code AS memory_error_code," + self._ATTENTION_COLUMNS + " "
                "FROM conversations c LEFT JOIN conversation_memory_states cm "
                "ON cm.conversation_id=c.id WHERE c.id=? AND c.user_id=?",
                (conversation_id, user_id),
            ).fetchone()
        if not row:
            raise OwnedResourceNotFound("conversation not found")
        return self._decode(row)

    def list(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT c.*,COALESCE(cm.finalization_status,'none') AS finalization_status,"
                "cm.last_error_code AS memory_error_code," + self._ATTENTION_COLUMNS + " "
                "FROM conversations c LEFT JOIN conversation_memory_states cm "
                "ON cm.conversation_id=c.id WHERE c.user_id=? "
                "ORDER BY c.updated_at DESC,c.id DESC LIMIT ?",
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def mark_viewed(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            result = conn.execute(
                "UPDATE conversations SET last_viewed_at=? WHERE id=? AND user_id=?",
                (utcnow(), conversation_id, user_id),
            )
            if result.rowcount != 1:
                raise OwnedResourceNotFound("conversation not found")
        return self.get(user_id, conversation_id)

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
                "SELECT title,status FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
            if not owner:
                raise OwnedResourceNotFound("conversation not found")
            if owner["status"] == "archived":
                raise ArchivedConversationError("conversation_archived")
            ConversationMemoryRepository(self.db_path).ensure_snapshot(
                user_id, conversation_id, conn
            )
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

    def recent_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return the newest rows while preserving chronological presentation."""
        self.get(user_id, conversation_id)
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? AND sequence>? "
                "ORDER BY sequence DESC LIMIT ?",
                (conversation_id, max(0, after_sequence), max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def context_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        after_sequence: int = 0,
        oldest_limit: int = 240,
        recent_limit: int = 15,
    ) -> list[dict[str, Any]]:
        """Return a bounded oldest prefix plus the true newest suffix.

        The prefix lets summarization advance without skipping source rows; the
        suffix guarantees the dialogue model still sees the latest turns even
        for conversations far beyond the historical query limit.
        """
        self.get(user_id, conversation_id)
        with get_conn(self.db_path) as conn:
            oldest = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                (
                    conversation_id, max(0, after_sequence),
                    max(1, min(oldest_limit, 500)),
                ),
            ).fetchall()
            recent = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? AND sequence>? "
                "ORDER BY sequence DESC LIMIT ?",
                (
                    conversation_id, max(0, after_sequence),
                    max(1, min(recent_limit, 100)),
                ),
            ).fetchall()
        merged = {row["id"]: dict(row) for row in (*oldest, *recent)}
        return sorted(merged.values(), key=lambda row: int(row["sequence"]))

    def message_range(
        self,
        user_id: str,
        conversation_id: str,
        from_sequence: int,
        through_sequence: int,
    ) -> list[dict[str, Any]]:
        self.get(user_id, conversation_id)
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? "
                "AND sequence BETWEEN ? AND ? ORDER BY sequence",
                (conversation_id, max(1, from_sequence), through_sequence),
            ).fetchall()
        return [dict(row) for row in rows]

    def archive(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                raise OwnedResourceNotFound("conversation not found")
            if row["status"] == "archived":
                return self.get(user_id, conversation_id)
            memory = ConversationMemoryRepository(self.db_path).ensure_snapshot(
                user_id, conversation_id, conn
            )
            latest = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM messages WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()[0]
            )
            now = memory_utcnow()
            conn.execute(
                "UPDATE conversations SET status='archived',archived_at=?,updated_at=? WHERE id=?",
                (now, now, conversation_id),
            )
            if latest > 0:
                MemoryJobRepository(self.db_path).enqueue(
                    user_id,
                    conversation_id,
                    "archive",
                    1,
                    latest,
                    conn,
                )
                final_status = "pending"
                finalized_at = None
            else:
                final_status = "succeeded"
                finalized_at = now
            conn.execute(
                "UPDATE conversation_memory_states SET finalization_status=?,"
                "finalized_at=?,last_error_code=NULL,updated_at=? "
                "WHERE conversation_id=? AND user_id=?",
                (final_status, finalized_at, now, conversation_id, user_id),
            )
        return self.get(user_id, conversation_id)


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
        result["data"] = normalize_brief_data(_loads(result.pop("data_json"), {}))
        result["missing_fields"] = _loads(result.pop("missing_fields_json"), [])
        result["submission_snapshot"] = _loads(
            result.pop("submission_snapshot_json"), None
        )
        result["memory_projection"] = _loads(
            result.pop("memory_projection_json", None), None
        )
        return result

    def _present(self, result: dict[str, Any]) -> dict[str, Any]:
        try:
            memory = ConversationMemoryRepository(self.db_path).get(
                result["user_id"], result["conversation_id"]
            )
        except Exception:
            memory = {"profile_revision": 0, "profile_snapshot": []}
        view = build_brief_projection(
            result["data"],
            revision=memory.get("profile_revision", 0),
            frozen_facts=memory.get("profile_snapshot") or [],
            projection=result.get("memory_projection"),
            match_status=result.get("memory_match_status", "none"),
            error_code=result.get("memory_match_error_code"),
        )
        return {**result, **view}

    def get(self, user_id: str, brief_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE id=? AND user_id=?",
                (brief_id, user_id),
            ).fetchone()
        if not row:
            raise OwnedResourceNotFound("planning brief not found")
        return self._present(self._decode(row))

    def active_for_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE conversation_id=? AND user_id=? "
                "AND status IN ('collecting','ready') ORDER BY updated_at DESC LIMIT 1",
                (conversation_id, user_id),
            ).fetchone()
        return self._present(self._decode(row)) if row else None

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
        return self._present(self._decode(row)) if row else None

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
            ConversationMemoryRepository(self.db_path).ensure_snapshot(
                user_id, conversation_id, conn
            )
            row = conn.execute(
                "SELECT * FROM planning_briefs WHERE conversation_id=? AND user_id=? "
                "AND status IN ('collecting','ready') LIMIT 1",
                (conversation_id, user_id),
            ).fetchone()
            data = normalize_brief_data(_loads(row["data_json"], {}) if row else {})
            data.update({key: value for key, value in patch.items() if value is not None})
            data = normalize_brief_data(data)
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

    def begin_memory_match(
        self, user_id: str, brief_id: str, fingerprint: str
    ) -> dict[str, Any]:
        now = utcnow()
        with get_conn(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE planning_briefs SET memory_match_status='pending',"
                "memory_match_error_code=NULL,memory_context_fingerprint=?,updated_at=? "
                "WHERE id=? AND user_id=? AND status IN ('collecting','ready')",
                (fingerprint, now, brief_id, user_id),
            )
            if cursor.rowcount != 1:
                raise OwnedResourceNotFound("active planning brief not found")
        return self.get(user_id, brief_id)

    def complete_memory_match(
        self,
        user_id: str,
        brief_id: str,
        fingerprint: str,
        projection: dict[str, Any],
    ) -> bool:
        now = utcnow()
        with get_conn(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE planning_briefs SET memory_projection_json=?,"
                "memory_match_status='succeeded',memory_match_error_code=NULL,"
                "memory_matched_at=?,updated_at=? WHERE id=? AND user_id=? "
                "AND memory_context_fingerprint=? AND status IN ('collecting','ready')",
                (_json(projection), now, now, brief_id, user_id, fingerprint),
            )
        return cursor.rowcount == 1

    def fail_memory_match(
        self, user_id: str, brief_id: str, fingerprint: str, error_code: str
    ) -> bool:
        now = utcnow()
        with get_conn(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE planning_briefs SET memory_match_status='failed',"
                "memory_match_error_code=?,updated_at=? WHERE id=? AND user_id=? "
                "AND memory_context_fingerprint=? AND status IN ('collecting','ready')",
                (error_code, now, brief_id, user_id, fingerprint),
            )
        return cursor.rowcount == 1

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
                return self._present(self._decode(row)), _decode_run(run)
            if row["status"] != "ready":
                raise ValueError("planning brief is not ready")
            decoded = self._decode(row)
            memory_row = conn.execute(
                "SELECT * FROM conversation_memory_states WHERE conversation_id=? AND user_id=?",
                (row["conversation_id"], user_id),
            ).fetchone()
            memory = (
                {
                    "profile_revision": int(memory_row["profile_revision"]),
                    "profile_snapshot": _loads(memory_row["profile_snapshot_json"], []),
                }
                if memory_row else {"profile_revision": 0, "profile_snapshot": []}
            )
            view = build_brief_projection(
                decoded["data"],
                revision=memory["profile_revision"],
                frozen_facts=memory["profile_snapshot"],
                projection=decoded.get("memory_projection"),
                match_status=decoded.get("memory_match_status", "none"),
                error_code=decoded.get("memory_match_error_code"),
            )
            snapshot = {
                **view["data"],
                "memory_context": view["memory_context"],
                "effective_constraints": view["effective_constraints"],
                "constraint_coverage": view["constraint_coverage"],
            }
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
