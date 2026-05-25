"""规划流程日志格式单元测试。

功能：
    验证规划链路日志保持人类易读，方便开发者直接打开日志文件查看候选池和聚类结果。
"""

import unittest

from backend.app.services import planner_logging


class PlannerLoggingTests(unittest.TestCase):
    """功能：覆盖规划日志渲染的核心可读性要求。"""

    def test_render_candidate_pool_uses_human_readable_chinese_text(self) -> None:
        """功能：验证 LLM 候选池日志包含中文标题、请求 ID 和景点字段。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证日志文本。
        """
        text = planner_logging.render_planner_event(
            "llm_raw_candidate_pool",
            "request-1",
            {
                "destination": "南京",
                "days": 2,
                "preferences": ["文化历史"],
                "query_plan": ["南京 热门旅游景点", "南京 必去景点"],
                "search_result_count": 8,
                "accepted_document_count": 2,
                "candidates": [
                    {
                        "name": "中山陵",
                        "mention_count": 2,
                        "preference_score": 10,
                        "score": 210,
                        "sources": [{"title": "南京攻略"}],
                    }
                ],
            },
        )

        self.assertIn("事件：1/4 LLM/raw 候选池", text)
        self.assertIn("请求ID：request-1", text)
        self.assertIn("目的地：南京", text)
        self.assertIn("搜索词：南京 热门旅游景点、南京 必去景点", text)
        self.assertIn("搜索结果数：8", text)
        self.assertIn("有效网页数：2", text)
        self.assertIn("1. 中山陵 | 提及网页数=2 | 偏好分=10 | 总分=210", text)
        self.assertIn("来源：南京攻略", text)

    def test_render_cluster_result_shows_cluster_medoid_and_candidates(self) -> None:
        """功能：验证聚类日志包含中心点、半径和簇内景点列表。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证日志文本。
        """
        text = planner_logging.render_planner_event(
            "cluster_result",
            "request-2",
            {
                "destination": "南京",
                "days": 1,
                "min_cluster_size": 2,
                "clusters": [
                    {
                        "cluster_id": 0,
                        "radius_km": 1.2,
                        "medoid": {
                            "name": "中山陵",
                            "mention_count": 2,
                            "preference_score": 10,
                            "score": 210,
                        },
                        "candidates": [
                            {
                                "name": "中山陵",
                                "mention_count": 2,
                                "preference_score": 10,
                                "score": 210,
                            }
                        ],
                    }
                ],
            },
        )

        self.assertIn("事件：4/4 聚类输出", text)
        self.assertIn("簇 0 | 半径 1.2 km", text)
        self.assertIn("中心点：中山陵", text)
        self.assertIn("景点：", text)

    def test_render_candidate_pool_chain_titles_for_enriched_and_cluster_input(self) -> None:
        """功能：验证高德补全候选池和聚类输入候选池使用明确链路标题。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证四段链路中的中间两段标题。
        """
        enriched_text = planner_logging.render_planner_event(
            "amap_enriched_candidate_pool",
            "request-3",
            {
                "destination": "南京",
                "days": 2,
                "warnings": ["夫子庙 已匹配 POI"],
                "candidates": [{"name": "夫子庙", "poi": {"name": "夫子庙"}}],
            },
        )
        cluster_input_text = planner_logging.render_planner_event(
            "cluster_input_candidate_pool",
            "request-3",
            {
                "destination": "南京",
                "days": 2,
                "candidates": [{"name": "夫子庙"}],
            },
        )

        self.assertIn("事件：2/4 高德 enriched 候选池", enriched_text)
        self.assertIn("警告：夫子庙 已匹配 POI", enriched_text)
        self.assertIn("事件：3/4 聚类输入候选池", cluster_input_text)


if __name__ == "__main__":
    unittest.main()
