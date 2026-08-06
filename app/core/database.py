"""SQLite 数据库初始化与连接管理。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.db"


def get_db_path() -> Path:
    return _DB_PATH


def configure_database(path: str | Path) -> None:
    """Override the database path, primarily for isolated tests."""
    global _DB_PATH
    _DB_PATH = Path(path)


def init_db(path: str | Path | None = None) -> None:
    db_path = Path(path) if path is not None else _DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS itineraries (
                id                  TEXT PRIMARY KEY,
                user_id             TEXT NOT NULL REFERENCES users(id),
                parent_id           TEXT,
                query               TEXT NOT NULL,
                modification_notes  TEXT,
                destination         TEXT,
                start_date          TEXT,
                end_date            TEXT,
                plan_json           TEXT NOT NULL,
                planner_state_json  TEXT,
                created_at          TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id              TEXT PRIMARY KEY REFERENCES users(id),
                attraction_prefs     TEXT,
                food_prefs           TEXT,
                habit_prefs          TEXT,
                visited_destinations TEXT,
                updated_at           TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_modifications (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                state_json  TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id),
                title       TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
                archived_at TEXT,
                last_viewed_at TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id                   TEXT PRIMARY KEY,
                conversation_id      TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id              TEXT NOT NULL REFERENCES users(id),
                role                 TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content              TEXT NOT NULL,
                sequence             INTEGER NOT NULL,
                related_run_id       TEXT,
                related_itinerary_id TEXT,
                created_at           TEXT NOT NULL,
                UNIQUE(conversation_id, sequence)
            );

            CREATE TABLE IF NOT EXISTS planning_briefs (
                id                       TEXT PRIMARY KEY,
                conversation_id          TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id                  TEXT NOT NULL REFERENCES users(id),
                status                   TEXT NOT NULL CHECK(status IN ('collecting', 'ready', 'submitted', 'discarded')),
                data_json                TEXT NOT NULL,
                missing_fields_json      TEXT NOT NULL DEFAULT '[]',
                submission_snapshot_json TEXT,
                submitted_run_id         TEXT,
                memory_projection_json   TEXT,
                memory_match_status      TEXT NOT NULL DEFAULT 'none',
                memory_match_error_code  TEXT,
                memory_context_fingerprint TEXT,
                memory_matched_at        TEXT,
                created_at               TEXT NOT NULL,
                updated_at               TEXT NOT NULL,
                submitted_at             TEXT
            );

            CREATE TABLE IF NOT EXISTS runs (
                id                         TEXT PRIMARY KEY,
                user_id                    TEXT NOT NULL REFERENCES users(id),
                conversation_id            TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                kind                       TEXT NOT NULL CHECK(kind IN ('chat', 'travel_plan', 'revision')),
                status                     TEXT NOT NULL CHECK(status IN ('queued', 'running', 'waiting_user', 'succeeded', 'failed', 'cancelled')),
                concurrency_key            TEXT NOT NULL,
                request_snapshot_json      TEXT NOT NULL,
                disconnect_policy          TEXT NOT NULL DEFAULT 'continue' CHECK(disconnect_policy IN ('continue', 'cancel')),
                retry_of_run_id             TEXT REFERENCES runs(id),
                result_itinerary_id         TEXT REFERENCES itineraries(id),
                error_public_json           TEXT,
                error_internal              TEXT,
                outstanding_interaction_id  TEXT,
                created_at                  TEXT NOT NULL,
                queued_at                   TEXT NOT NULL,
                started_at                  TEXT,
                finished_at                 TEXT,
                updated_at                  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_events (
                id          TEXT PRIMARY KEY,
                run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                sequence    INTEGER NOT NULL,
                kind        TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                durable     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL,
                UNIQUE(run_id, sequence)
            );

            CREATE TABLE IF NOT EXISTS user_memory_states (
                user_id     TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                revision    INTEGER NOT NULL DEFAULT 0,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_facts (
                id                       TEXT PRIMARY KEY,
                user_id                  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                category                 TEXT NOT NULL CHECK(category IN (
                    'attraction_preference','food_preference','dietary_requirement',
                    'travel_pace','budget_style','transport_preference',
                    'accommodation_preference','schedule_preference','companion_context',
                    'accessibility_need','destination_history','other_travel_preference'
                )),
                value_text               TEXT NOT NULL,
                normalized_value         TEXT NOT NULL,
                polarity                 TEXT NOT NULL CHECK(polarity IN ('prefer','avoid','require','fact')),
                scope_type               TEXT NOT NULL CHECK(scope_type IN ('global','destination','companion','destination_companion')),
                scope_key                TEXT NOT NULL DEFAULT '{}',
                status                   TEXT NOT NULL CHECK(status IN ('active','candidate','superseded','deleted')),
                source_kind              TEXT NOT NULL CHECK(source_kind IN ('explicit_chat','inferred_chat','manual','legacy')),
                sensitivity              TEXT NOT NULL DEFAULT 'normal' CHECK(sensitivity IN ('normal','protected')),
                source_conversation_id   TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                evidence_sequences_json TEXT NOT NULL DEFAULT '[]',
                confidence               REAL NOT NULL DEFAULT 1.0,
                supersedes_id            TEXT REFERENCES memory_facts(id),
                fingerprint              TEXT NOT NULL,
                created_at               TEXT NOT NULL,
                updated_at               TEXT NOT NULL,
                deleted_at               TEXT,
                UNIQUE(user_id, fingerprint)
            );

            CREATE TABLE IF NOT EXISTS conversation_memory_states (
                conversation_id              TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
                user_id                      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                profile_revision             INTEGER NOT NULL DEFAULT 0,
                profile_snapshot_json        TEXT NOT NULL DEFAULT '[]',
                summary_json                 TEXT,
                summarized_through_sequence INTEGER NOT NULL DEFAULT 0,
                summary_count                INTEGER NOT NULL DEFAULT 0,
                estimated_context_tokens     INTEGER NOT NULL DEFAULT 0,
                finalization_status          TEXT NOT NULL DEFAULT 'none' CHECK(finalization_status IN ('none','pending','succeeded','failed')),
                finalized_at                 TEXT,
                last_error_code              TEXT,
                created_at                   TEXT NOT NULL,
                updated_at                   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_extraction_jobs (
                id                  TEXT PRIMARY KEY,
                conversation_id     TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind                TEXT NOT NULL CHECK(kind IN ('pre_summary','archive')),
                from_sequence       INTEGER NOT NULL,
                through_sequence    INTEGER NOT NULL,
                status              TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed')),
                attempts            INTEGER NOT NULL DEFAULT 0,
                next_attempt_at     TEXT,
                last_error_code     TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                finished_at         TEXT,
                UNIQUE(conversation_id,kind,from_sequence,through_sequence)
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated
                ON conversations(user_id, updated_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_sequence
                ON messages(conversation_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_briefs_conversation_status
                ON planning_briefs(conversation_id, status, updated_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_brief_per_conversation
                ON planning_briefs(conversation_id)
                WHERE status IN ('collecting', 'ready');
            CREATE INDEX IF NOT EXISTS idx_runs_queue
                ON runs(status, queued_at, id);
            CREATE INDEX IF NOT EXISTS idx_runs_owner_active
                ON runs(user_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_conversation
                ON runs(conversation_id, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_run_events_replay
                ON run_events(run_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_memory_facts_owner_status
                ON memory_facts(user_id,status,updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_facts_scope
                ON memory_facts(user_id,scope_type,normalized_value);
            CREATE INDEX IF NOT EXISTS idx_memory_jobs_claim
                ON memory_extraction_jobs(status,next_attempt_at,created_at);
        """)
        # 对已有数据库做迁移保护
        try:
            conn.execute("ALTER TABLE itineraries ADD COLUMN planner_state_json TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在
        for statement in (
            "ALTER TABLE itineraries ADD COLUMN root_id TEXT",
            "ALTER TABLE itineraries ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE conversations ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "ALTER TABLE conversations ADD COLUMN archived_at TEXT",
            "ALTER TABLE conversations ADD COLUMN last_viewed_at TEXT",
            "ALTER TABLE planning_briefs ADD COLUMN memory_projection_json TEXT",
            "ALTER TABLE planning_briefs ADD COLUMN memory_match_status TEXT NOT NULL DEFAULT 'none'",
            "ALTER TABLE planning_briefs ADD COLUMN memory_match_error_code TEXT",
            "ALTER TABLE planning_briefs ADD COLUMN memory_context_fingerprint TEXT",
            "ALTER TABLE planning_briefs ADD COLUMN memory_matched_at TEXT",
        ):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass
        journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            raise RuntimeError("SQLite WAL mode could not be enabled")
        conn.execute(
            "UPDATE conversations SET last_viewed_at=updated_at "
            "WHERE last_viewed_at IS NULL"
        )
        conn.execute(
            "DELETE FROM pending_modifications "
            "WHERE julianday(created_at) < julianday('now', '-30 days')"
        )
        _migrate_legacy_profiles(conn)


def _memory_fingerprint(
    category: str,
    normalized_value: str,
    polarity: str,
    scope_type: str = "global",
    scope_key: str = "{}",
) -> str:
    raw = "\x1f".join(
        (category, normalized_value, polarity, scope_type, scope_key)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _migrate_legacy_profiles(conn: sqlite3.Connection) -> None:
    """Backfill the retired four-list profile without treating plans as visits."""
    rows = conn.execute(
        "SELECT user_id,attraction_prefs,food_prefs,habit_prefs,visited_destinations "
        "FROM user_profiles"
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    mapping = (
        ("attraction_prefs", "attraction_preference", "prefer", "active"),
        ("food_prefs", "food_preference", "prefer", "active"),
        ("habit_prefs", "travel_pace", "prefer", "active"),
        ("visited_destinations", "destination_history", "fact", "candidate"),
    )
    for row in rows:
        inserted_active = False
        for column, category, polarity, status in mapping:
            try:
                values = json.loads(row[column] or "[]")
            except (TypeError, json.JSONDecodeError):
                values = []
            for value in values if isinstance(values, list) else []:
                text = str(value).strip()
                if not text:
                    continue
                normalized = " ".join(text.casefold().split())
                fingerprint = _memory_fingerprint(category, normalized, polarity)
                fact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tripagent:{row['user_id']}:{fingerprint}"))
                before = conn.total_changes
                conn.execute(
                    """INSERT OR IGNORE INTO memory_facts(
                       id,user_id,category,value_text,normalized_value,polarity,
                       scope_type,scope_key,status,source_kind,sensitivity,
                       evidence_sequences_json,confidence,fingerprint,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,'legacy','normal','[]',0.5,?,?,?)""",
                    (
                        fact_id, row["user_id"], category, text, normalized, polarity,
                        "global", "{}", status, fingerprint, now, now,
                    ),
                )
                if status == "active" and conn.total_changes > before:
                    inserted_active = True
        conn.execute(
            "INSERT OR IGNORE INTO user_memory_states(user_id,revision,updated_at) VALUES(?,?,?)",
            (row["user_id"], 1 if inserted_active else 0, now),
        )


@contextmanager
def get_conn(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = Path(path) if path is not None else _DB_PATH
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
