"""HTTP 公共工具：代理选择、带重试的 GET、URL 脱敏。"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

import httpx

from app.core.async_resources import provider_slot


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) TripAgentBackend/0.1"
)
HTTP_PROXY_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_SECRET_QUERY_KEYS = ("key", "api_key", "access_token", "token")


def choose_http_proxy() -> str | None:
    """返回 httpx 可直接使用的 HTTP(S) 代理 URL，没有则返回 None。"""
    for key in HTTP_PROXY_ENV_KEYS:
        proxy = os.getenv(key, "").strip()
        if proxy.startswith(("http://", "https://")):
            return proxy
    return None


def redact_url(url: str) -> str:
    """隐藏 URL 中的 key/token 等敏感查询参数，用于安全地打印日志。"""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for secret_key in _SECRET_QUERY_KEYS:
        if secret_key in query:
            query[secret_key] = ["<redacted>"]
    redacted_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=redacted_query))


def http_get_json(url: str, timeout: int = 15) -> dict[str, Any]:
    """发起 GET 请求并解析 JSON，失败时退避重试三次。"""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(response.read().decode(charset, errors="replace"))
        except Exception as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"请求失败：{redact_url(url)}；原因：{last_error}")


_async_client: httpx.AsyncClient | None = None
_async_client_lock = asyncio.Lock()


async def get_async_http_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        async with _async_client_lock:
            if _async_client is None:
                _async_client = httpx.AsyncClient(
                    proxy=choose_http_proxy(),
                    trust_env=False,
                    timeout=15,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                    },
                )
    return _async_client


async def close_async_http_client() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


async def http_get_json_async(url: str, timeout: int = 15) -> dict[str, Any]:
    client = await get_async_http_client()
    last_error: Exception | None = None
    async with provider_slot("amap"):
        for attempt in range(3):
            try:
                response = await client.get(url, timeout=timeout)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("response is not a JSON object")
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"请求失败：{redact_url(url)}；原因：{last_error}")
