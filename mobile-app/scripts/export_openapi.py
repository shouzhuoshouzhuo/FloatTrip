"""Export the colocated FastAPI schema for mobile TypeScript code generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


MOBILE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = MOBILE_ROOT.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from app.main import app  # noqa: E402


with (MOBILE_ROOT / "openapi.json").open("w", encoding="utf-8") as handle:
    json.dump(app.openapi(), handle, ensure_ascii=False, indent=2)
