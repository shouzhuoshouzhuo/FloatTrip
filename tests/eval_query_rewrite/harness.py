"""
query_rewrite 评估核心：
  - 与生产代码完全对齐：直接读 DB → 单次结构化 LLM 调用
  - 使用临时 SQLite 隔离测试数据
  - 返回全链路观测数据 + 确定性打分结果

用法：
    from tests.eval_query_rewrite.harness import run_single
    result = run_single(fixture, model_name=None)
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch


# ─── 单用例执行 ───────────────────────────────────────────────────────────────

def run_single(fixture: dict, model_name: str | None = None) -> dict[str, Any]:
    """
    执行一条 fixture，返回全链路观测数据。

    Returns:
        {
            "fixture_id", "raw_query", "profile_from_db",
            "intent_prefs_string", "profile_text",
            "output", "grading"
        }
    """
    import app.core.database as _db_module
    from app.core.database import init_db, get_conn
    from app.core.memory import set_user_profile, search_profile_fields, get_user_profile
    from app.llm.deepseek import build_structured_deepseek
    from app.planning.schemas import RewrittenQuery
    from app.planning.prompts import QUERY_REWRITE_SYSTEM
    from app.planning.helpers import invoke_structured

    raw_query   = fixture["query"]
    profile_cfg = fixture["profile"]

    # ── 1. 临时 DB，插入测试用户 + 画像 ──────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)

    with patch.object(_db_module, "_DB_PATH", tmp_path):
        init_db()

        test_user_id = str(uuid.uuid4())

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?,?,?,?)",
                (test_user_id, f"testuser_{test_user_id[:8]}", "x", "2026-01-01"),
            )

        with get_conn() as conn:
            set_user_profile(test_user_id, profile_cfg, conn)

        # 读回确认（用于报告）
        with get_conn() as conn:
            profile_from_db = get_user_profile(test_user_id, conn)

        # ── 2. 直接读画像（与生产代码完全对齐）──────────────────────────────
        profile_text = "（该用户暂无历史画像）"
        with get_conn() as conn:
            data = search_profile_fields(
                test_user_id, ["attraction_prefs", "food_prefs", "habit_prefs"], conn
            )
        if data and any(data.values()):
            parts = []
            if data.get("attraction_prefs"):
                parts.append("景点偏好：" + "、".join(data["attraction_prefs"]))
            if data.get("food_prefs"):
                parts.append("餐饮偏好：" + "、".join(data["food_prefs"]))
            if data.get("habit_prefs"):
                parts.append("游玩习惯：" + "、".join(data["habit_prefs"]))
            profile_text = "\n".join(parts)

        # ── 3. 构造 intent_prefs（与生产代码完全一致）──────────────────────
        intent_attraction = fixture.get("intent_attraction")
        intent_food       = fixture.get("intent_food")
        intent_habit      = fixture.get("intent_habit")
        intent_prefs_string = (
            f"本次查询提取的偏好：景点={intent_attraction or '无'}，"
            f"餐饮={intent_food or '无'}，习惯={intent_habit or '无'}"
        )

        # ── 4. 单次结构化 LLM 调用 ────────────────────────────────────────
        rewrite_llm = build_structured_deepseek(RewrittenQuery, model=model_name, temperature=0)
        rewritten: RewrittenQuery = invoke_structured(rewrite_llm, [
            ("system", QUERY_REWRITE_SYSTEM),
            ("human", f"原始查询：{raw_query}\n\n{intent_prefs_string}\n\n用户历史画像：\n{profile_text}"),
        ])

        # ── 5. 合并（与生产代码一致：LLM 输出为空时 fallback 到 intent）──────
        output = {
            "rewritten_query":       rewritten.rewritten_query,
            "reasoning":             rewritten.reasoning,
            "attraction_preference": rewritten.attraction_preference or intent_attraction,
            "food_preference":       rewritten.food_preference       or intent_food,
            "habit_preference":      rewritten.habit_preference      or intent_habit,
        }

        # ── 6. 打分 ─────────────────────────────────────────────────────────
        grading = _grade(fixture, output)

    # 清理临时文件（忽略失败）
    try:
        tmp_path.unlink()
    except Exception:
        pass

    return {
        "fixture_id":          fixture["id"],
        "description":         fixture["description"],
        "raw_query":           raw_query,
        "profile_from_db":     profile_from_db,
        "intent_prefs_string": intent_prefs_string,
        "profile_text":        profile_text,
        "output":              output,
        "grading":             grading,
    }


# ─── 打分器（确定性代码逻辑，不用 LLM）────────────────────────────────────────

def _grade(fixture: dict, output: dict[str, Any]) -> dict[str, Any]:
    exp = fixture["expectations"]
    grades: dict[str, Any] = {}

    # G1：补全检查（指定字段应非 None）
    supplement_fields = exp.get("supplement_check", [])
    if supplement_fields:
        missing = [f for f in supplement_fields if output.get(f) is None]
        grades["g_supplement"] = len(missing) == 0
        grades["g_supplement_detail"] = (
            "OK" if not missing else f"以下字段未补全: {missing}"
        )
    else:
        grades["g_supplement"] = None  # N/A

    # G2：冲突解析检查
    conflict_field    = exp.get("conflict_field")
    must_not_contain  = exp.get("conflict_must_not_contain", [])
    if conflict_field and must_not_contain:
        field_val  = output.get(conflict_field) or ""
        violations = [w for w in must_not_contain if w in field_val]
        grades["g_conflict"] = len(violations) == 0
        grades["g_conflict_detail"] = (
            "OK" if not violations
            else f"字段 {conflict_field!r} 含禁止词: {violations}（值={field_val!r}）"
        )
    else:
        grades["g_conflict"] = None  # N/A

    # G3：不发明偏好检查（all_prefs_none 场景）
    if exp.get("all_prefs_none"):
        invented = [
            f for f in ["attraction_preference", "food_preference", "habit_preference"]
            if output.get(f) is not None
        ]
        grades["g_no_invention"] = len(invented) == 0
        grades["g_no_invention_detail"] = (
            "OK" if not invented else f"以下字段不应有值但有内容: {invented}"
        )
    else:
        grades["g_no_invention"] = None  # N/A

    # overall_pass：所有非 N/A 的指标均通过
    active = [v for v in grades.values() if isinstance(v, bool)]
    grades["overall_pass"] = all(active) if active else True

    return grades
