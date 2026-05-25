"""Unsplash 景点图片查询服务。

功能：
    封装 Unsplash Search Photos API，用目的地和景点名称搜索行程详情页图片。
    服务在没有配置 UNSPLASH_ACCESS_KEY 时静默跳过，避免图片能力影响核心规划链路。
"""

from __future__ import annotations

import os
from typing import Any

import requests

from backend.app.services import travel_research


UNSPLASH_BASE_URL = "https://api.unsplash.com"
UNSPLASH_TIMEOUT_SECONDS = 10


class UnsplashService:
    """Unsplash 图片服务类。"""

    def __init__(self, access_key: str | None = None) -> None:
        """功能：初始化 Unsplash 服务。

        参数：
            access_key：Unsplash Access Key；为空时从环境变量读取。
        返回值：
            无返回值。
        """
        self.access_key = access_key if access_key is not None else read_unsplash_access_key()
        self.base_url = UNSPLASH_BASE_URL

    def is_configured(self) -> bool:
        """功能：判断当前服务是否已配置可用 Access Key。

        参数：
            无。
        返回值：
            已配置时返回 True，否则返回 False。
        """
        return bool(self.access_key)

    def search_photos(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        """功能：按关键词搜索 Unsplash 图片。

        参数：
            query：搜索关键词。
            per_page：返回图片数量。
        返回值：
            返回归一化后的图片列表；失败或未配置时返回空列表。
        """
        cleaned_query = query.strip()
        if not self.access_key or not cleaned_query:
            return []
        try:
            response = requests.get(
                f"{self.base_url}/search/photos",
                params={
                    "query": cleaned_query,
                    "per_page": per_page,
                    "client_id": self.access_key,
                    "orientation": "landscape",
                },
                timeout=UNSPLASH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException:
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        return [photo for item in results if (photo := normalize_photo(item))]

    def get_photo(self, query: str) -> dict[str, Any] | None:
        """功能：获取单张最匹配图片。

        参数：
            query：搜索关键词。
        返回值：
            返回图片字典；没有结果时返回 None。
        """
        photos = self.search_photos(query, per_page=1)
        return photos[0] if photos else None


def read_unsplash_access_key() -> str:
    """功能：读取 Unsplash Access Key。

    参数：
        无。
    返回值：
        返回环境变量中的 Access Key；未配置时返回空字符串。
    """
    travel_research.load_local_env()
    return os.getenv("UNSPLASH_ACCESS_KEY", "").strip()


def normalize_photo(photo: Any) -> dict[str, Any] | None:
    """功能：把 Unsplash 原始图片结果压缩成前端需要的字段。

    参数：
        photo：Unsplash 返回的单张图片原始字典。
    返回值：
        返回包含 url、thumb、description 和 photographer 的图片字典；无 URL 时返回 None。
    """
    if not isinstance(photo, dict):
        return None
    urls = photo.get("urls") if isinstance(photo.get("urls"), dict) else {}
    image_url = str(urls.get("regular") or urls.get("small") or "").strip()
    if not image_url:
        return None
    user = photo.get("user") if isinstance(photo.get("user"), dict) else {}
    return {
        "id": photo.get("id"),
        "url": image_url,
        "thumb": str(urls.get("thumb") or image_url),
        "description": photo.get("description") or photo.get("alt_description"),
        "photographer": user.get("name"),
        "photographer_url": user.get("links", {}).get("html") if isinstance(user.get("links"), dict) else None,
    }


_unsplash_service: UnsplashService | None = None


def get_unsplash_service() -> UnsplashService:
    """功能：获取 Unsplash 服务单例。

    参数：
        无。
    返回值：
        返回 UnsplashService 实例。
    """
    global _unsplash_service
    if _unsplash_service is None:
        _unsplash_service = UnsplashService()
    return _unsplash_service
