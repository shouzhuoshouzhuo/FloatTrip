"""HTTP 公共工具：代理选择、带重试的 GET、URL 脱敏。"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any


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
