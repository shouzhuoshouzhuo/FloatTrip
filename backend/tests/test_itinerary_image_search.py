"""行程详情图片搜索 Agent 单元测试。

功能：
    验证 DeepSeek 生成的 Unsplash query 会优先用于图片搜索，并且搜索循环
    会遵守最大尝试次数。
"""

import unittest
from unittest.mock import patch

from backend.app.services import itinerary_details


class ItineraryImageSearchTests(unittest.TestCase):
    """功能：覆盖行程详情图片搜索 Agent 的核心行为。"""

    def test_image_search_agent_uses_deepseek_queries_first_and_stops_on_hit(self) -> None:
        """功能：验证图片搜索 Agent 优先使用 DeepSeek query，命中后停止继续尝试。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证调用顺序和图片结果。
        """
        service = FakeImageService({"Nanjing Sun Yat-sen Mausoleum": fake_photo("中山陵")})

        with patch(
            "backend.app.services.itinerary_details.build_llm_image_queries",
            return_value=["Nanjing Sun Yat-sen Mausoleum", "Sun Yat-sen Mausoleum Nanjing"],
        ):
            photo, warnings = itinerary_details.search_spot_photo_with_agent(
                service,
                "南京",
                "中山陵",
                max_attempts=5,
            )

        self.assertEqual("https://images.example/中山陵.jpg", photo["url"])
        self.assertEqual(["Nanjing Sun Yat-sen Mausoleum"], service.queries)
        self.assertEqual([], warnings)

    def test_image_search_agent_respects_max_attempts(self) -> None:
        """功能：验证图片搜索 Agent 不会超过最大 query 尝试次数。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证 Unsplash 调用次数。
        """
        service = FakeImageService({})

        with patch(
            "backend.app.services.itinerary_details.build_llm_image_queries",
            return_value=[
                "query one",
                "query two",
                "query three",
                "query four",
            ],
        ):
            photo, warnings = itinerary_details.search_spot_photo_with_agent(
                service,
                "南京",
                "夫子庙",
                max_attempts=2,
            )

        self.assertIsNone(photo)
        self.assertEqual(["query one", "query two"], service.queries)
        self.assertEqual([], warnings)

    def test_image_search_agent_skips_photo_used_by_another_spot(self) -> None:
        """功能：验证不同景点不会复用已经分配过的同一张图片。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证重复图片会被跳过。
        """
        service = FakeImageService(
            {
                "query one": fake_photo("城市兜底"),
                "query two": fake_photo("夫子庙"),
            }
        )

        with patch(
            "backend.app.services.itinerary_details.build_llm_image_queries",
            return_value=["query one", "query two"],
        ):
            photo, warnings = itinerary_details.search_spot_photo_with_agent(
                service,
                "南京",
                "夫子庙",
                max_attempts=2,
                used_photo_keys={"https://images.example/城市兜底.jpg"},
            )

        self.assertEqual("https://images.example/夫子庙.jpg", photo["url"])
        self.assertEqual(["query one", "query two"], service.queries)
        self.assertEqual([], warnings)

    def test_image_queries_for_spot_keeps_rule_fallback_after_deepseek_queries(self) -> None:
        """功能：验证 DeepSeek query 后仍保留规则别名和城市兜底。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证 query 队列。
        """
        queries = itinerary_details.image_queries_for_spot(
            "南京市",
            "夫子庙",
            llm_queries=["Fuzimiao Nanjing"],
        )

        self.assertEqual("Fuzimiao Nanjing", queries[0])
        self.assertIn("Qinhuai River Nanjing", queries)
        self.assertIn("南京 travel", queries)

    def test_day_theme_image_search_skips_spot_photo_and_uses_theme_photo(self) -> None:
        """功能：验证每日主题封面图会避开已用于景点卡的图片。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证封面图优先使用主题搜索命中。
        """
        service = FakeImageService(
            {
                "Nanjing museum lake scenery": fake_photo("景点已用图"),
                "Nanjing lake mountain travel": fake_photo("主题封面图"),
            }
        )

        with patch(
            "backend.app.services.itinerary_details.build_llm_image_queries",
            return_value=["Nanjing museum lake scenery", "Nanjing lake mountain travel"],
        ):
            photo, warnings = itinerary_details.search_day_theme_photo_with_agent(
                service,
                "南京",
                "博物寻珍 湖光山色",
                ["南京博物院", "玄武湖"],
                used_photo_keys={"https://images.example/景点已用图.jpg"},
            )

        self.assertEqual("https://images.example/主题封面图.jpg", photo["url"])
        self.assertEqual(["Nanjing museum lake scenery", "Nanjing lake mountain travel"], service.queries)
        self.assertEqual([], warnings)


class FakeImageService:
    """功能：模拟 Unsplash 图片服务并记录搜索 query。"""

    def __init__(self, photos_by_query: dict[str, dict]) -> None:
        """功能：初始化测试图片服务。

        参数：
            photos_by_query：query 到图片结果的映射。
        返回值：
            无返回值。
        """
        self.photos_by_query = photos_by_query
        self.queries: list[str] = []

    def is_configured(self) -> bool:
        """功能：返回测试服务配置状态。

        参数：
            无。
        返回值：
            始终返回 True。
        """
        return True

    def get_photo(self, query: str) -> dict | None:
        """功能：记录 query 并返回预设图片。

        参数：
            query：图片搜索关键词。
        返回值：
            返回预设图片；未命中时返回 None。
        """
        self.queries.append(query)
        return self.photos_by_query.get(query)


def fake_photo(name: str) -> dict:
    """功能：构造测试图片字典。

    参数：
        name：图片对应的景点名称。
    返回值：
        返回符合后端图片字段的字典。
    """
    return {
        "url": f"https://images.example/{name}.jpg",
        "thumb": f"https://images.example/{name}-thumb.jpg",
        "description": f"{name} 图片",
        "photographer": "FloatTrip",
    }


if __name__ == "__main__":
    unittest.main()
