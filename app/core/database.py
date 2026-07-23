"""SQLite 数据库初始化与连接管理。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
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
        """)
        # 对已有数据库做迁移保护
        try:
            conn.execute("ALTER TABLE itineraries ADD COLUMN planner_state_json TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在
        for statement in (
            "ALTER TABLE itineraries ADD COLUMN root_id TEXT",
            "ALTER TABLE itineraries ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
        ):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass
        journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            raise RuntimeError("SQLite WAL mode could not be enabled")
        conn.execute(
            "DELETE FROM pending_modifications "
            "WHERE julianday(created_at) < julianday('now', '-30 days')"
        )


@contextmanager
def get_conn(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = Path(path) if path is not None else _DB_PATH
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
