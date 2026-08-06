"""Structured travel memory persistence and conversation snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.database import get_conn


FACT_CATEGORIES = {
    "attraction_preference",
    "food_preference",
    "dietary_requirement",
    "travel_pace",
    "budget_style",
    "transport_preference",
    "accommodation_preference",
    "schedule_preference",
    "companion_context",
    "accessibility_need",
    "destination_history",
    "other_travel_preference",
}
POLARITIES = {"prefer", "avoid", "require", "fact"}
SCOPE_TYPES = {"global", "destination", "companion", "destination_companion"}
FACT_STATUSES = {"active", "candidate", "superseded", "deleted"}
SOURCE_KINDS = {"explicit_chat", "inferred_chat", "manual", "legacy"}
_PROHIBITED_VALUE_PATTERNS = (
    re.compile(r"\b\d{15,18}[0-9Xx]\b"),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b(?:\d[ -]?){16,19}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"(?:身份证|护照|银行卡|信用卡|手机号|电话号码|微信号|邮箱|精确住址)"),
)


class MemoryNotFound(LookupError):
    pass


class ArchivedConversationError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_value(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def is_prohibited_memory_value(value: str) -> bool:
    return any(pattern.search(str(value or "")) for pattern in _PROHIBITED_VALUE_PATTERNS)


def canonical_scope_key(scope_type: str, scope_key: Any = None) -> str:
    if scope_type not in SCOPE_TYPES:
        raise ValueError("invalid memory scope")
    if scope_type == "global":
        return "{}"
    if isinstance(scope_key, str):
        try:
            parsed = json.loads(scope_key)
        except json.JSONDecodeError:
            parsed = {scope_type: scope_key}
    elif isinstance(scope_key, dict):
        parsed = scope_key
    else:
        parsed = {}
    cleaned = {
        str(key): normalize_value(str(value))
        for key, value in parsed.items()
        if str(value).strip()
    }
    required_keys = {
        "destination": {"destination"},
        "companion": {"companion"},
        "destination_companion": {"destination", "companion"},
    }[scope_type]
    if not required_keys <= cleaned.keys():
        raise ValueError(
            "scoped memory requires " + " and ".join(sorted(required_keys))
        )
    normalized = {key: cleaned[key] for key in sorted(required_keys)}
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def memory_fingerprint(
    category: str,
    normalized_value: str,
    polarity: str,
    scope_type: str,
    scope_key: str,
) -> str:
    raw = "\x1f".join(
        (category, normalized_value, polarity, scope_type, scope_key)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def decode_fact(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["scope_key"] = json.loads(result.get("scope_key") or "{}")
    result["evidence_sequences"] = json.loads(
        result.pop("evidence_sequences_json", "[]") or "[]"
    )
    result.pop("fingerprint", None)
    return result


def decode_memory_state(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["profile_snapshot"] = json.loads(
        result.pop("profile_snapshot_json", "[]") or "[]"
    )
    result["summary"] = json.loads(result.pop("summary_json", "null") or "null")
    return result


class MemoryRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path

    @staticmethod
    def _ensure_revision(conn: sqlite3.Connection, user_id: str) -> int:
        now = utcnow()
        conn.execute(
            "INSERT OR IGNORE INTO user_memory_states(user_id,revision,updated_at) VALUES(?,0,?)",
            (user_id, now),
        )
        row = conn.execute(
            "SELECT revision FROM user_memory_states WHERE user_id=?", (user_id,)
        ).fetchone()
        return int(row["revision"])

    @staticmethod
    def _bump_revision(conn: sqlite3.Connection, user_id: str) -> int:
        MemoryRepository._ensure_revision(conn, user_id)
        now = utcnow()
        conn.execute(
            "UPDATE user_memory_states SET revision=revision+1,updated_at=? WHERE user_id=?",
            (now, user_id),
        )
        return int(
            conn.execute(
                "SELECT revision FROM user_memory_states WHERE user_id=?", (user_id,)
            ).fetchone()["revision"]
        )

    def revision(self, user_id: str) -> int:
        with get_conn(self.db_path) as conn:
            return self._ensure_revision(conn, user_id)

    def list(
        self, user_id: str, *, statuses: set[str] | None = None
    ) -> list[dict[str, Any]]:
        chosen = statuses or {"active", "candidate"}
        if not chosen <= FACT_STATUSES:
            raise ValueError("invalid memory status")
        placeholders = ",".join("?" for _ in chosen)
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM memory_facts WHERE user_id=? AND status IN ({placeholders}) "
                "ORDER BY category,updated_at DESC,id",
                (user_id, *sorted(chosen)),
            ).fetchall()
        return [decode_fact(row) for row in rows]

    def snapshot(self, user_id: str, conn: sqlite3.Connection | None = None) -> tuple[int, list[dict[str, Any]]]:
        if conn is None:
            with get_conn(self.db_path) as owned:
                return self.snapshot(user_id, owned)
        revision = self._ensure_revision(conn, user_id)
        rows = conn.execute(
            "SELECT * FROM memory_facts WHERE user_id=? AND status='active' "
            "ORDER BY category,updated_at DESC,id",
            (user_id,),
        ).fetchall()
        return revision, [decode_fact(row) for row in rows]

    def get(self, user_id: str, fact_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        if conn is None:
            with get_conn(self.db_path) as owned:
                return self.get(user_id, fact_id, owned)
        row = conn.execute(
            "SELECT * FROM memory_facts WHERE id=? AND user_id=?", (fact_id, user_id)
        ).fetchone()
        if not row:
            raise MemoryNotFound("memory fact not found")
        return decode_fact(row)

    def create(
        self,
        user_id: str,
        *,
        category: str,
        value_text: str,
        polarity: str = "fact",
        scope_type: str = "global",
        scope_key: Any = None,
        status: str = "active",
        source_kind: str = "manual",
        sensitivity: str = "normal",
        source_conversation_id: str | None = None,
        evidence_sequences: list[int] | None = None,
        confidence: float = 1.0,
        supersedes_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if conn is None:
            with get_conn(self.db_path) as owned:
                return self.create(
                    user_id,
                    category=category,
                    value_text=value_text,
                    polarity=polarity,
                    scope_type=scope_type,
                    scope_key=scope_key,
                    status=status,
                    source_kind=source_kind,
                    sensitivity=sensitivity,
                    source_conversation_id=source_conversation_id,
                    evidence_sequences=evidence_sequences,
                    confidence=confidence,
                    supersedes_id=supersedes_id,
                    conn=owned,
                )
        if category not in FACT_CATEGORIES or polarity not in POLARITIES:
            raise ValueError("invalid memory fact")
        if status not in FACT_STATUSES or source_kind not in SOURCE_KINDS:
            raise ValueError("invalid memory metadata")
        if sensitivity not in {"normal", "protected"}:
            raise ValueError("invalid memory sensitivity")
        text = str(value_text).strip()
        normalized = normalize_value(text)
        if not normalized or len(text) > 500:
            raise ValueError("memory value must contain 1-500 characters")
        if is_prohibited_memory_value(text):
            raise ValueError("prohibited personal data cannot be stored as memory")
        scope_json = canonical_scope_key(scope_type, scope_key)
        fingerprint = memory_fingerprint(
            category, normalized, polarity, scope_type, scope_json
        )
        existing = conn.execute(
            "SELECT * FROM memory_facts WHERE user_id=? AND fingerprint=?",
            (user_id, fingerprint),
        ).fetchone()
        now = utcnow()
        evidence_json = json.dumps(
            sorted({int(value) for value in (evidence_sequences or [])}),
            separators=(",", ":"),
        )
        if existing:
            old_status = existing["status"]
            if old_status in {"deleted", "superseded"} and source_kind != "manual":
                # Replaying an extraction job must never resurrect something
                # the user forgot or a fact that a correction replaced.
                return self.get(user_id, existing["id"], conn)
            target_status = (
                "active"
                if status == "active" or old_status == "active"
                else status
            )
            conn.execute(
                "UPDATE memory_facts SET status=?,source_kind=?,sensitivity=?,"
                "source_conversation_id=COALESCE(?,source_conversation_id),"
                "evidence_sequences_json=?,confidence=MAX(confidence,?),"
                "deleted_at=NULL,updated_at=? WHERE id=?",
                (
                    target_status, source_kind, sensitivity, source_conversation_id,
                    evidence_json, float(confidence), now, existing["id"],
                ),
            )
            if target_status == "active" and old_status != "active":
                self._bump_revision(conn, user_id)
            return self.get(user_id, existing["id"], conn)
        fact_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO memory_facts(
               id,user_id,category,value_text,normalized_value,polarity,scope_type,
               scope_key,status,source_kind,sensitivity,source_conversation_id,
               evidence_sequences_json,confidence,supersedes_id,fingerprint,
               created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fact_id, user_id, category, text, normalized, polarity, scope_type,
                scope_json, status, source_kind, sensitivity, source_conversation_id,
                evidence_json, max(0.0, min(float(confidence), 1.0)), supersedes_id,
                fingerprint, now, now,
            ),
        )
        if status == "active":
            self._bump_revision(conn, user_id)
        return self.get(user_id, fact_id, conn)

    def replace(self, user_id: str, fact_id: str, **changes: Any) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = self.get(user_id, fact_id, conn)
            if old["status"] not in {"active", "candidate"}:
                raise ValueError("memory fact cannot be edited")
            conn.execute(
                "UPDATE memory_facts SET status='superseded',updated_at=? WHERE id=?",
                (utcnow(), fact_id),
            )
            if old["status"] == "active":
                self._bump_revision(conn, user_id)
            return self.create(
                user_id,
                category=changes.get("category", old["category"]),
                value_text=changes.get("value_text", old["value_text"]),
                polarity=changes.get("polarity", old["polarity"]),
                scope_type=changes.get("scope_type", old["scope_type"]),
                scope_key=changes.get("scope_key", old["scope_key"]),
                status="active",
                source_kind="manual",
                sensitivity=old["sensitivity"],
                supersedes_id=fact_id,
                conn=conn,
            )

    def approve(self, user_id: str, fact_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            fact = self.get(user_id, fact_id, conn)
            if fact["status"] != "candidate":
                raise ValueError("only candidate memory can be approved")
            conn.execute(
                "UPDATE memory_facts SET status='active',updated_at=? WHERE id=?",
                (utcnow(), fact_id),
            )
            self._bump_revision(conn, user_id)
            return self.get(user_id, fact_id, conn)

    def delete(self, user_id: str, fact_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            fact = self.get(user_id, fact_id, conn)
            if fact["status"] == "deleted":
                return fact
            now = utcnow()
            conn.execute(
                "UPDATE memory_facts SET status='deleted',deleted_at=?,updated_at=? WHERE id=?",
                (now, now, fact_id),
            )
            if fact["status"] == "active":
                self._bump_revision(conn, user_id)
            return self.get(user_id, fact_id, conn)

    def supersede(self, user_id: str, fact_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            fact = self.get(user_id, fact_id, conn)
            if fact["status"] == "superseded":
                return fact
            if fact["status"] == "deleted":
                return fact
            conn.execute(
                "UPDATE memory_facts SET status='superseded',updated_at=? WHERE id=?",
                (utcnow(), fact_id),
            )
            if fact["status"] == "active":
                self._bump_revision(conn, user_id)
            return self.get(user_id, fact_id, conn)

    @staticmethod
    def format_for_prompt(facts: list[dict[str, Any]]) -> str:
        if not facts:
            return "（尚无已确认的长期旅行记忆）"
        lines = []
        for fact in facts:
            scope = fact.get("scope_type", "global")
            scope_key = fact.get("scope_key") or {}
            scope_label = "全局" if scope == "global" else f"{scope}:{json.dumps(scope_key, ensure_ascii=False)}"
            lines.append(
                f"- [{fact.get('category')}/{fact.get('polarity')}/{scope_label}] "
                f"{fact.get('value_text')}"
            )
        return "\n".join(lines)


class ConversationMemoryRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        self.facts = MemoryRepository(db_path)

    def ensure_snapshot(
        self, user_id: str, conversation_id: str, conn: sqlite3.Connection
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM conversation_memory_states WHERE conversation_id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone()
        if row:
            return decode_memory_state(row)
        owner = conn.execute(
            "SELECT status FROM conversations WHERE id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone()
        if not owner:
            raise MemoryNotFound("conversation not found")
        if owner["status"] == "archived":
            raise ArchivedConversationError("conversation_archived")
        revision, snapshot = self.facts.snapshot(user_id, conn)
        now = utcnow()
        conn.execute(
            """INSERT INTO conversation_memory_states(
               conversation_id,user_id,profile_revision,profile_snapshot_json,
               created_at,updated_at) VALUES(?,?,?,?,?,?)""",
            (
                conversation_id, user_id, revision,
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                now, now,
            ),
        )
        return self.get(user_id, conversation_id, conn)

    def get(
        self,
        user_id: str,
        conversation_id: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if conn is None:
            with get_conn(self.db_path) as owned:
                return self.get(user_id, conversation_id, owned)
        row = conn.execute(
            "SELECT * FROM conversation_memory_states WHERE conversation_id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone()
        if not row:
            raise MemoryNotFound("conversation memory not initialized")
        return decode_memory_state(row)

    def update_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: dict[str, Any],
        through_sequence: int,
        estimated_tokens: int,
    ) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            now = utcnow()
            conn.execute(
                """UPDATE conversation_memory_states
                   SET summary_json=?,summarized_through_sequence=?,
                       summary_count=summary_count+1,estimated_context_tokens=?,updated_at=?
                   WHERE conversation_id=? AND user_id=?
                     AND summarized_through_sequence<?""",
                (
                    json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                    through_sequence, estimated_tokens, now, conversation_id, user_id,
                    through_sequence,
                ),
            )
            return self.get(user_id, conversation_id, conn)

    def record_estimate(self, user_id: str, conversation_id: str, tokens: int) -> None:
        with get_conn(self.db_path) as conn:
            conn.execute(
                "UPDATE conversation_memory_states SET estimated_context_tokens=?,updated_at=? "
                "WHERE conversation_id=? AND user_id=?",
                (tokens, utcnow(), conversation_id, user_id),
            )


class MemoryJobRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path

    def enqueue(
        self,
        user_id: str,
        conversation_id: str,
        kind: str,
        from_sequence: int,
        through_sequence: int,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if through_sequence < from_sequence or through_sequence <= 0:
            return None
        if kind not in {"pre_summary", "archive"}:
            raise ValueError("invalid memory job kind")
        if conn is None:
            with get_conn(self.db_path) as owned:
                return self.enqueue(
                    user_id, conversation_id, kind, from_sequence,
                    through_sequence, owned,
                )
        now = utcnow()
        job_id = str(uuid.uuid4())
        conn.execute(
            """INSERT OR IGNORE INTO memory_extraction_jobs(
               id,conversation_id,user_id,kind,from_sequence,through_sequence,
               status,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,?)""",
            (
                job_id, conversation_id, user_id, kind,
                max(1, int(from_sequence)), int(through_sequence), now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM memory_extraction_jobs WHERE conversation_id=? AND kind=? "
            "AND from_sequence=? AND through_sequence=?",
            (conversation_id, kind, max(1, int(from_sequence)), int(through_sequence)),
        ).fetchone()
        return dict(row) if row else None

    def reset_running(self) -> int:
        with get_conn(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE memory_extraction_jobs SET status='pending',updated_at=? "
                "WHERE status='running'",
                (utcnow(),),
            )
            return cur.rowcount

    def claim_next(self) -> dict[str, Any] | None:
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM memory_extraction_jobs WHERE status='pending' "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
                "ORDER BY created_at,id LIMIT 1",
                (utcnow(),),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE memory_extraction_jobs SET status='running',attempts=attempts+1,updated_at=? "
                "WHERE id=? AND status='pending'",
                (utcnow(), row["id"]),
            )
            claimed = conn.execute(
                "SELECT * FROM memory_extraction_jobs WHERE id=?", (row["id"],)
            ).fetchone()
            return dict(claimed) if claimed else None

    def complete(self, job_id: str) -> None:
        with get_conn(self.db_path) as conn:
            now = utcnow()
            row = conn.execute(
                "SELECT conversation_id,kind FROM memory_extraction_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                return
            conn.execute(
                "UPDATE memory_extraction_jobs SET status='succeeded',finished_at=?,"
                "last_error_code=NULL,updated_at=? WHERE id=?",
                (now, now, job_id),
            )
            if row["kind"] == "archive":
                conn.execute(
                    "UPDATE conversation_memory_states SET finalization_status='succeeded',"
                    "finalized_at=?,last_error_code=NULL,updated_at=? WHERE conversation_id=?",
                    (now, now, row["conversation_id"]),
                )

    def fail(self, job_id: str, error_code: str) -> None:
        with get_conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT attempts,conversation_id,kind FROM memory_extraction_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                return
            attempts = int(row["attempts"])
            terminal = attempts >= 5
            delay = min(2 ** max(0, attempts - 1) * 30, 7200)
            next_at = (
                None
                if terminal
                else (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            )
            conn.execute(
                "UPDATE memory_extraction_jobs SET status=?,next_attempt_at=?,last_error_code=?,updated_at=? "
                "WHERE id=?",
                ("failed" if terminal else "pending", next_at, error_code, utcnow(), job_id),
            )
            if terminal and row["kind"] == "archive":
                conn.execute(
                    "UPDATE conversation_memory_states SET finalization_status='failed',"
                    "last_error_code=?,updated_at=? WHERE conversation_id=?",
                    (error_code, utcnow(), row["conversation_id"]),
                )

    def retry_archive(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM memory_extraction_jobs WHERE conversation_id=? AND user_id=? "
                "AND kind='archive' ORDER BY created_at DESC LIMIT 1",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                raise MemoryNotFound("archive memory job not found")
            if row["status"] != "failed":
                raise ValueError("archive memory job is not failed")
            conn.execute(
                "UPDATE memory_extraction_jobs SET status='pending',attempts=0,next_attempt_at=NULL,"
                "last_error_code=NULL,updated_at=? WHERE id=?",
                (utcnow(), row["id"]),
            )
            conn.execute(
                "UPDATE conversation_memory_states SET finalization_status='pending',"
                "last_error_code=NULL,updated_at=? WHERE conversation_id=? AND user_id=?",
                (utcnow(), conversation_id, user_id),
            )
            return dict(
                conn.execute(
                    "SELECT * FROM memory_extraction_jobs WHERE id=?", (row["id"],)
                ).fetchone()
            )
