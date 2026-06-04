"""DeepSeek 结构化输出客户端工厂。"""

from __future__ import annotations

import os
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.env import load_local_env
from app.core.http import choose_http_proxy


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
_LEGACY_MODEL_ALIASES = {
    "deepseekv4flash": "deepseek-v4-flash",
    "deepseekv4pro": "deepseek-v4-pro",
}

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def normalize_deepseek_model(model: str) -> str:
    return _LEGACY_MODEL_ALIASES.get(model.strip(), model.strip())


def resolve_deepseek_model(model: str | None = None) -> str:
    chosen = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    return normalize_deepseek_model(chosen)


def build_chat_deepseek(*, model: str | None = None, temperature: float = 0) -> Any:
    """创建未绑定 schema 的 DeepSeek ChatOpenAI 客户端。"""
    load_local_env()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY。请在 .env.local 中配置后重试。")
    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx 或 langchain-openai。请先安装依赖。") from exc

    proxy = choose_http_proxy()
    return ChatOpenAI(
        model=resolve_deepseek_model(model),
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
        http_client=httpx.Client(proxy=proxy, trust_env=False),
        http_async_client=httpx.AsyncClient(proxy=proxy, trust_env=False),
        http_socket_options=(),
        extra_body={"thinking": {"type": "disabled"}},
    )


def build_structured_deepseek(
    schema: type[SchemaT],
    *,
    model: str | None = None,
    temperature: float = 0,
) -> Any:
    """创建绑定到给定 Pydantic schema 的 DeepSeek 结构化输出模型。"""
    llm = build_chat_deepseek(model=model, temperature=temperature)
    return llm.with_structured_output(schema, method="function_calling", strict=True)
