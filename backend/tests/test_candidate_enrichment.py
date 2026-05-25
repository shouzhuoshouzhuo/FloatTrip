"""候选景点 POI 富化单元测试。

功能：
    验证高德 POI 富化会按用户目的地行政区过滤结果，避免目的地外 POI
    进入后续聚类和路线规划。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.services import candidate_enrichment


class CandidateEnrichmentTests(unittest.TestCase):
    """功能：覆盖候选景点高德 POI 匹配过滤行为。"""

    def test_enrich_candidates_filters_pois_outside_destination_admin_region(self) -> None:
        """功能：验证目的地行政区外的 POI 会被过滤。

        参数：
            无。
        返回值：
            无返回值；通过断言验证过滤后的候选名称。
        """
        candidates = [
            {"name": "中山陵", "score": 205},
            {"name": "寒山寺", "score": 105},
        ]

        with patch(
            "backend.app.services.candidate_enrichment.amap.search_amap_pois",
            side_effect=fake_pois,
        ):
            enriched, warnings = candidate_enrichment.enrich_candidates_with_amap(
                candidates,
                destination="南京",
                api_key="test-key",
                max_candidates=10,
            )

        self.assertEqual(["中山陵"], [candidate["name"] for candidate in enriched])
        self.assertIn("寒山寺 未匹配到目的地行政区内的高德 POI", warnings)

    def test_poi_in_destination_rejects_other_admin_region(self) -> None:
        """功能：验证 POI 行政区不属于目的地时会被过滤。

        参数：
            无。
        返回值：
            无返回值；通过断言验证行政区过滤结果。
        """
        self.assertFalse(
            candidate_enrichment.poi_in_destination(
                {"city": "苏州市", "district": "姑苏区", "adcode": "320508"},
                "南京",
            )
        )
        self.assertTrue(
            candidate_enrichment.poi_in_destination(
                {"city": "南京市", "district": "玄武区", "adcode": "320102"},
                "南京",
            )
        )

    def test_prompt_mentions_destination_scope(self) -> None:
        """功能：验证 LLM 提示词明确要求只抽取指定目的地内景点。

        参数：
            无。
        返回值：
            无返回值；通过断言验证提示词关键约束。
        """
        from backend.app.services import travel_research

        prompt = travel_research.build_prompt("上海外滩 南京博物院", [], 20, "南京")

        self.assertIn("用户指定目的地：南京", prompt)
        self.assertIn("只能输出位于“南京”行政区范围内的景点", prompt)
        self.assertIn("忽略其他城市景点", prompt)


def fake_pois(keyword: str, _admin_region: str, _api_key: str, _offset: int) -> list[dict]:
    """功能：构造高德搜索结果，模拟南京内外 POI。

    参数：
        keyword：搜索关键词。
        _admin_region：行政区参数，本测试中不使用。
        _api_key：测试 Key，本测试中不使用。
        _offset：搜索数量，本测试中不使用。
    返回值：
        返回高德 POI 原始字典列表。
    """
    pois_by_keyword = {
        "中山陵": [
            {
                "id": "poi-zsl",
                "name": "中山陵景区",
                "pname": "江苏省",
                "cityname": "南京市",
                "adname": "玄武区",
                "adcode": "320102",
                "location": "118.854097,32.054508",
            }
        ],
        "寒山寺": [
            {
                "id": "poi-hss",
                "name": "寒山寺",
                "pname": "江苏省",
                "cityname": "苏州市",
                "adname": "姑苏区",
                "adcode": "320508",
                "location": "120.573166,31.311944",
            }
        ],
    }
    return pois_by_keyword.get(keyword, [])


if __name__ == "__main__":
    unittest.main()
