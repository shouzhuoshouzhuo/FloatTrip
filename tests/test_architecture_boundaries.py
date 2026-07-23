from __future__ import annotations

import ast
from pathlib import Path


def test_agent_graphs_do_not_import_transport_layers():
    root = Path(__file__).resolve().parents[1] / "app"
    violations = []
    for package in ("chat", "planning"):
        for path in (root / package).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(
                    name.startswith(("fastapi", "app.api"))
                    for name in names
                ):
                    violations.append(f"{path.name}: {names}")
    assert not violations, "transport imports found: " + ", ".join(violations)


def test_chat_understanding_has_no_rule_based_language_fallback():
    root = Path(__file__).resolve().parents[1] / "app" / "chat"
    violations = []
    for path in (root / "graph.py", root / "service.py", root / "executor.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name == "re" for alias in node.names):
                violations.append(f"{path.name}: imports re")
            if isinstance(node, ast.ImportFrom) and node.module == "re":
                violations.append(f"{path.name}: imports from re")
    assert not violations, "chat rule fallback found: " + ", ".join(violations)
