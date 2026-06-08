"""Redis 缓存层：高德 API 结果缓存，Redis 不可用时静默降级。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 全局 Redis 客户端（延迟初始化）
_redis_client = None
_redis_init_attempted = False


def _get_redis():
    """获取 Redis 客户端，使用连接池复用连接。Redis 不可用时返回 None。"""
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        logger.info("未配置 REDIS_URL，缓存功能已禁用")
        return None

    try:
        import redis
        _redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1,
            retry_on_timeout=False,
        )
        # 测试连接
        _redis_client.ping()
        logger.info("Redis 缓存已连接：%s", redis_url.split("@")[-1] if "@" in redis_url else redis_url)
    except Exception as exc:
        logger.warning("Redis 连接失败，缓存功能已禁用：%s", exc)
        _redis_client = None

    return _redis_client


def get_cached(key: str) -> Any | None:
    """从缓存获取数据。Redis 不可用或未命中时返回 None。"""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw is not None:
            return json.loads(raw)
    except Exception as exc:
        logger.debug("缓存读取失败 [%s]：%s", key, exc)
    return None


def set_cached(key: str, value: Any, ttl_seconds: int) -> None:
    """写入缓存。Redis 不可用时静默跳过。"""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        logger.debug("缓存写入失败 [%s]：%s", key, exc)


# ─── 缓存键命名工具 ──────────────────────────────────────────

def weather_cache_key(city: str) -> str:
    """天气预报缓存键。格式：tripagent:weather:{city}"""
    return f"tripagent:weather:{city}"


def poi_cache_key(city: str, keyword: str) -> str:
    """POI 搜索缓存键。格式：tripagent:poi:{city}:{keyword}"""
    return f"tripagent:poi:{city}:{keyword}"


# ─── TTL 常量 ──────────────────────────────────────────────────

WEATHER_TTL = 4 * 3600    # 天气缓存 4 小时
POI_TTL = 12 * 3600       # POI 缓存 12 小时
