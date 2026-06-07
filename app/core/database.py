"""SQLite 数据库初始化与连接管理。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.db"


def init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
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
        """)
        # 对已有数据库做迁移保护
        try:
            conn.execute("ALTER TABLE itineraries ADD COLUMN planner_state_json TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
