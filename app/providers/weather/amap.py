"""高德天气预报客户端。

调用高德天气预报接口（extensions=all），返回未来约 4 天逐日天气。
复用项目已有的 AMAP_API_KEY，无需额外申请。
"""
from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any

from app.core.cache import get_cached, set_cached, weather_cache_key, WEATHER_TTL
from app.core.http import http_get_json, http_get_json_async

AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
BAD_WEATHER_KEYWORDS = {"雨", "雪", "冰雹", "雾", "沙尘暴", "霾"}


def _is_bad(weather: str) -> bool:
    """判断天气描述是否为不宜户外出行的天气。"""
    return any(kw in weather for kw in BAD_WEATHER_KEYWORDS)


def fetch_forecast(city: str, api_key: str) -> list[dict[str, Any]]:
    """调用高德天气预报接口，返回未来约 4 天逐日天气列表。

    每条格式：
        {
            "date":          "YYYY-MM-DD",
            "day_weather":   str,   # 白天天气，如"晴""小雨"
            "night_weather": str,   # 夜间天气
            "day_temp":      str,   # 白天最高温（°C）
            "night_temp":    str,   # 夜间最低温（°C）
            "is_bad":        bool,  # 是否为雨/雪/雾等不宜户外天气
        }

    接口异常或无数据时返回空列表（由调用方降级处理）。
    """
    # 尝试从缓存获取
    cache_key = weather_cache_key(city)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    params = {
        "key": api_key,
        "city": city,
        "extensions": "all",
        "output": "json",
    }
    url = f"{AMAP_WEATHER_URL}?{urllib.parse.urlencode(params)}"

    try:
        data = http_get_json(url)
    except Exception:
        return []

    if data.get("status") != "1":
        return []

    forecasts = data.get("forecasts") or []
    if not forecasts or not isinstance(forecasts, list):
        return []

    casts = forecasts[0].get("casts") or []
    result: list[dict[str, Any]] = []
    for c in casts:
        d = str(c.get("date", "")).strip()
        if not d:
            continue
        day_w   = str(c.get("dayweather",   "")).strip()
        night_w = str(c.get("nightweather", "")).strip()
        result.append({
            "date":          d,
            "day_weather":   day_w,
            "night_weather": night_w,
            "day_temp":      str(c.get("daytemp",   "")).strip(),
            "night_temp":    str(c.get("nighttemp", "")).strip(),
            "is_bad":        _is_bad(day_w) or _is_bad(night_w),
        })

    # 写入缓存
    if result:
        set_cached(cache_key, result, WEATHER_TTL)
    return result


async def fetch_forecast_async(city: str, api_key: str) -> list[dict[str, Any]]:
    cache_key = weather_cache_key(city)
    cached = await asyncio.to_thread(get_cached, cache_key)
    if cached is not None:
        return cached
    params = {
        "key": api_key,
        "city": city,
        "extensions": "all",
        "output": "json",
    }
    url = f"{AMAP_WEATHER_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = await http_get_json_async(url)
    except Exception:
        return []
    if data.get("status") != "1":
        return []
    forecasts = data.get("forecasts") or []
    if not forecasts or not isinstance(forecasts, list):
        return []
    result: list[dict[str, Any]] = []
    for cast in forecasts[0].get("casts") or []:
        day_weather = str(cast.get("dayweather", "")).strip()
        night_weather = str(cast.get("nightweather", "")).strip()
        if not cast.get("date"):
            continue
        result.append(
            {
                "date": str(cast["date"]),
                "day_weather": day_weather,
                "night_weather": night_weather,
                "day_temp": str(cast.get("daytemp", "")).strip(),
                "night_temp": str(cast.get("nighttemp", "")).strip(),
                "is_bad": _is_bad(day_weather) or _is_bad(night_weather),
            }
        )
    if result:
        await asyncio.to_thread(set_cached, cache_key, result, WEATHER_TTL)
    return result
