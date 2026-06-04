"""本地环境变量加载。

整个项目只在这里读取 `.env.local`，避免每个模块各写一份加载逻辑。
"""

from __future__ import annotations

import os
from pathlib import Path


# app/core/env.py → app/core → app → 项目根（parents[2]）
LOCAL_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.local"


def load_local_env() -> None:
    """把 `.env.local` 中缺失的键写入 `os.environ`，不覆盖已有环境变量。"""
    if not LOCAL_ENV_FILE.exists():
        return
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value
