"""高德 REST 接口的公共常量与小工具。"""

from __future__ import annotations

from typing import Any


AMAP_TEXT_SEARCH_URL = "https://restapi.amap.com/v3/place/text"
AMAP_AROUND_SEARCH_URL = "https://restapi.amap.com/v3/place/around"
AMAP_RATE_LIMIT_INFOS = {
    "CUQPS_HAS_EXCEEDED_THE_LIMIT",
    "USER_DAILY_QUERY_OVER_LIMIT",
    "USER_KEY_RECYCLED",
}


def int_or_none(value: Any) -> int | None:
    """把高德返回的数字字符串转成整数，无法转换时返回 None。"""
    return int(value) if str(value).isdigit() else None
