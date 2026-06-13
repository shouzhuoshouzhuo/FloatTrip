"""用户记忆读写：偏好提取、行程保存、历史查询。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


# ─── 用户偏好 ────────────────────────────────────────────────

def get_user_profile(user_id: str, conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT attraction_prefs, food_prefs, habit_prefs, visited_destinations "
        "FROM user_profiles WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not row:
        return {"attraction_prefs": [], "food_prefs": [], "habit_prefs": [], "visited_destinations": []}
    return {
        "attraction_prefs":     json.loads(row["attraction_prefs"] or "[]"),
        "food_prefs":           json.loads(row["food_prefs"] or "[]"),
        "habit_prefs":          json.loads(row["habit_prefs"] or "[]"),
        "visited_destinations": json.loads(row["visited_destinations"] or "[]"),
    }


def set_user_profile(user_id: str, profile: dict, conn: sqlite3.Connection) -> None:
    """整体覆盖式更新用户画像（供用户手动编辑）。每个字段为字符串列表，去空去重。"""
    def clean(items) -> list:
        seen, out = set(), []
        for it in (items or []):
            s = str(it).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out[:20]

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO user_profiles (user_id, attraction_prefs, food_prefs, habit_prefs, visited_destinations, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
               attraction_prefs=excluded.attraction_prefs,
               food_prefs=excluded.food_prefs,
               habit_prefs=excluded.habit_prefs,
               visited_destinations=excluded.visited_destinations,
               updated_at=excluded.updated_at""",
        (
            user_id,
            json.dumps(clean(profile.get("attraction_prefs")), ensure_ascii=False),
            json.dumps(clean(profile.get("food_prefs")), ensure_ascii=False),
            json.dumps(clean(profile.get("habit_prefs")), ensure_ascii=False),
            json.dumps(clean(profile.get("visited_destinations")), ensure_ascii=False),
            now,
        ),
    )


_PREFERENCE_FIELDS = {"attraction_prefs", "food_prefs", "habit_prefs"}


def search_profile_fields(user_id: str, fields: list[str], conn: sqlite3.Connection) -> dict:
    """按字段名列表查询偏好画像，只返回指定字段（不含 visited_destinations）。
    fields 可选：attraction_prefs, food_prefs, habit_prefs
    """
    profile = get_user_profile(user_id, conn)
    return {f: profile[f] for f in fields if f in _PREFERENCE_FIELDS and f in profile}


def format_profile_for_prompt(profile: dict) -> str:
    parts = []
    if profile.get("attraction_prefs"):
        parts.append("景点偏好：" + "、".join(profile["attraction_prefs"]))
    if profile.get("food_prefs"):
        parts.append("餐饮偏好：" + "、".join(profile["food_prefs"]))
    if profile.get("habit_prefs"):
        parts.append("游玩节奏：" + "、".join(profile["habit_prefs"]))
    if profile.get("visited_destinations"):
        parts.append("去过的城市：" + "、".join(profile["visited_destinations"]))
    return "\n".join(parts)


def extract_and_update_preferences(user_id: str, plan: dict, conn: sqlite3.Connection) -> None:
    """从 final_plan 提取偏好，去重追加到 user_profiles。"""
    prefs = plan.get("preferences", {})
    destination = plan.get("destination", "")

    existing = get_user_profile(user_id, conn)

    def merge(existing_list: list, new_str: str) -> list:
        if not new_str:
            return existing_list
        new_items = [s.strip() for s in new_str.replace("、", "/").replace("，", "/").split("/") if s.strip()]
        merged = list(existing_list)
        for item in new_items:
            if item not in merged:
                merged.append(item)
        return merged[:20]  # 最多保留 20 条

    attraction = merge(existing["attraction_prefs"], prefs.get("attraction", ""))
    food       = merge(existing["food_prefs"],       prefs.get("food", ""))
    habit      = merge(existing["habit_prefs"],      prefs.get("habit", ""))
    visited    = list(existing["visited_destinations"])
    if destination and destination not in visited:
        visited.append(destination)
        visited = visited[-20:]

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO user_profiles (user_id, attraction_prefs, food_prefs, habit_prefs, visited_destinations, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
               attraction_prefs=excluded.attraction_prefs,
               food_prefs=excluded.food_prefs,
               habit_prefs=excluded.habit_prefs,
               visited_destinations=excluded.visited_destinations,
               updated_at=excluded.updated_at""",
        (user_id, json.dumps(attraction, ensure_ascii=False),
         json.dumps(food, ensure_ascii=False),
         json.dumps(habit, ensure_ascii=False),
         json.dumps(visited, ensure_ascii=False), now),
    )


# ─── 行程保存 / 查询 ─────────────────────────────────────────

def save_itinerary(
    user_id: str,
    plan: dict,
    query: str,
    conn: sqlite3.Connection,
    *,
    parent_id: str | None = None,
    modification_notes: str | None = None,
    planner_state: dict | None = None,
) -> str:
    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO itineraries
           (id, user_id, parent_id, query, modification_notes,
            destination, start_date, end_date, plan_json, planner_state_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            plan_id, user_id, parent_id, query, modification_notes,
            plan.get("destination", ""),
            plan.get("start_date", ""),
            plan.get("end_date", ""),
            json.dumps(plan, ensure_ascii=False),
            json.dumps(planner_state, ensure_ascii=False) if planner_state else None,
            now,
        ),
    )
    return plan_id


def load_itinerary(plan_id: str, conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT plan_json, modification_notes, planner_state_json FROM itineraries WHERE id=?",
        (plan_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "plan": json.loads(row["plan_json"]),
        "modification_notes": row["modification_notes"],
        "planner_state": json.loads(row["planner_state_json"]) if row["planner_state_json"] else None,
    }


# ─── Pending 修改（Human-in-the-Loop 暂存）────────────────────

def save_pending_modification(
    user_id: str,
    state_dict: dict,
    conn: sqlite3.Connection,
) -> str:
    pending_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO pending_modifications (id, user_id, state_json, created_at) VALUES (?,?,?,?)",
        (pending_id, user_id, json.dumps(state_dict, ensure_ascii=False), now),
    )
    return pending_id


def load_pending_modification(
    pending_id: str,
    conn: sqlite3.Connection,
) -> dict | None:
    row = conn.execute(
        "SELECT state_json, user_id FROM pending_modifications WHERE id=?",
        (pending_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "state": json.loads(row["state_json"]),
        "user_id": row["user_id"],
    }


def delete_pending_modification(pending_id: str, conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM pending_modifications WHERE id=?", (pending_id,))


def update_plan_json(plan_id: str, user_id: str, new_plan: dict, conn: sqlite3.Connection) -> bool:
    """更新指定行程的 plan_json，校验 user_id 所有权。返回 True 表示更新成功。"""
    cur = conn.execute(
        "UPDATE itineraries SET plan_json=? WHERE id=? AND user_id=?",
        (json.dumps(new_plan, ensure_ascii=False), plan_id, user_id),
    )
    return cur.rowcount > 0


def list_itineraries(user_id: str, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, parent_id, destination, start_date, end_date, created_at
           FROM itineraries WHERE user_id=? ORDER BY created_at DESC LIMIT 50""",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def summarize_plan_for_prompt(plan: dict) -> str:
    """提取行程摘要用于 planner 修改模式的 prompt 注入。"""
    lines = [f"目的地：{plan.get('destination', '')}，{plan.get('start_date', '')} 至 {plan.get('end_date', '')}"]
    for day in plan.get("days", []):
        spots = [t["name"] for t in day.get("timeline", []) if t.get("type") == "attraction"]
        lines.append(f"第{day['day']}天（{day.get('date', '')}）：{'、'.join(spots) or '无景点'}")
    return "\n".join(lines)
