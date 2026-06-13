"""统一 LLM 工厂：支持多个提供商（DeepSeek、豆包等）。"""

from __future__ import annotations

import os
from typing import Any, TypeVar, Literal

from pydantic import BaseModel

from app.core.env import load_local_env


SchemaT = TypeVar("SchemaT", bound=BaseModel)
LLMProvider = Literal["deepseek", "doubao"]

DEFAULT_PROVIDER = "deepseek"


def resolve_llm_provider() -> LLMProvider:
    """从环境变量解析 LLM 提供商，默认为 DeepSeek。"""
    load_local_env()
    provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider not in ("deepseek", "doubao"):
        raise ValueError(f"未知的 LLM 提供商：{provider}，支持：deepseek, doubao")
    return provider  # type: ignore


def build_chat_llm(*, model: str | None = None, temperature: float = 0) -> Any:
    """创建 Chat 客户端（自动选择提供商）。"""
    provider = resolve_llm_provider()
    if provider == "deepseek":
        from app.llm.deepseek import build_chat_deepseek
        return build_chat_deepseek(model=model, temperature=temperature)
    elif provider == "doubao":
        from app.llm.doubao import build_chat_doubao
        return build_chat_doubao(model=model, temperature=temperature)


def build_structured_llm(
    schema: type[SchemaT],
    *,
    model: str | None = None,
    temperature: float = 0,
) -> Any:
    """创建结构化输出客户端（自动选择提供商）。"""
    provider = resolve_llm_provider()
    if provider == "deepseek":
        from app.llm.deepseek import build_structured_deepseek
        return build_structured_deepseek(schema, model=model, temperature=temperature)
    elif provider == "doubao":
        from app.llm.doubao import build_structured_doubao
        return build_structured_doubao(schema, model=model, temperature=temperature)
