"""旅行规划 API 集成测试。

功能：
    验证健康检查、规划接口主链路、异常映射、用户景点输入拆分和必去景点合并行为。
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.services.travel_research import (
    CandidatePoolGenerationResult,
    ResearchBundle,
    ResearchDocument,
    SearchResult,
)
from backend.app.workflows.research_route_planner import merge_preferred_spots


class PlannerApiTests(unittest.TestCase):
    """功能：覆盖 FastAPI 规划接口和请求模型的关键行为。"""

    def setUp(self) -> None:
        """功能：为每个测试创建 FastAPI 测试客户端。

        参数：
            无。
        返回值：
            无返回值；会把 TestClient 保存到 self.client。
        """
        self.client = TestClient(app)

    def test_health(self) -> None:
        """功能：验证健康检查接口返回可用状态。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证响应。
        """
        response = self.client.get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    def test_generate_routes_runs_research_poi_and_transit_pipeline(self) -> None:
        """功能：验证规划接口会串联调研、候选抽取、POI 补全和交通路线生成。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证响应结构和关键字段。
        """
        payload = {
            "destination": "南京",
            "days": 2,
            "preferences": ["文化历史"],
            "preferred_spots": ["中山陵"],
            "max_search_results": 2,
            "max_candidates": 8,
        }
        bundle = ResearchBundle(
            query_plan=["南京 两日游 攻略 景点"],
            search_results=[
                SearchResult(
                    title="南京两日游攻略",
                    url="https://example.com/nanjing",
                    snippet="中山陵 明孝陵 夫子庙 老门东",
                    source="test",
                )
            ],
            documents=[
                ResearchDocument(
                    title="南京两日游攻略",
                    url="https://example.com/nanjing",
                    source="test",
                    text=(
                        "## 南京两日游攻略\n\n"
                        "中山陵 明孝陵 夫子庙 老门东 南京博物院 总统府 "
                        "中山陵 夫子庙 明孝陵 老门东 南京博物院 总统府"
                    ),
                )
            ],
            warnings=[],
        )

        candidates = [
            {
                "name": "中山陵",
                "mention_count": 2,
                "preference_score": 10,
                "score": 210,
                "candidate_builder": "deepseek_candidate_pool_agent",
                "model": "deepseek-v4-flash",
                "sources": [],
            },
            {
                "name": "明孝陵",
                "mention_count": 2,
                "preference_score": 8,
                "score": 208,
                "candidate_builder": "deepseek_candidate_pool_agent",
                "model": "deepseek-v4-flash",
                "sources": [],
            },
            {
                "name": "夫子庙",
                "mention_count": 2,
                "preference_score": 7,
                "score": 207,
                "candidate_builder": "deepseek_candidate_pool_agent",
                "model": "deepseek-v4-flash",
                "sources": [],
            },
            {
                "name": "老门东",
                "mention_count": 2,
                "preference_score": 6,
                "score": 206,
                "candidate_builder": "deepseek_candidate_pool_agent",
                "model": "deepseek-v4-flash",
                "sources": [],
            },
            {
                "name": "南京博物院",
                "mention_count": 2,
                "preference_score": 9,
                "score": 209,
                "candidate_builder": "deepseek_candidate_pool_agent",
                "model": "deepseek-v4-flash",
                "sources": [],
            },
            {
                "name": "总统府",
                "mention_count": 2,
                "preference_score": 5,
                "score": 205,
                "candidate_builder": "deepseek_candidate_pool_agent",
                "model": "deepseek-v4-flash",
                "sources": [],
            },
        ]

        with patch(
            "backend.app.workflows.research_route_planner.generate_hot_candidate_pool",
            return_value=CandidatePoolGenerationResult(bundle, candidates),
        ) as generate_hot_candidate_pool, patch(
            "backend.app.workflows.research_route_planner.require_amap_key",
            return_value="test-key",
        ), patch(
            "backend.app.providers.amap.search_amap_pois",
            side_effect=fake_pois,
        ), patch(
            "backend.app.planning.transit_routes.time.sleep",
            return_value=None,
        ), patch(
            "backend.app.planning.transit_routes.amap.query_transit_route",
            side_effect=fake_transit_route,
        ):
            response = self.client.post("/api/planner/generate", json=payload)

        self.assertEqual(200, response.status_code)
        generate_hot_candidate_pool.assert_called_once()
        data = response.json()
        self.assertEqual("floattrip_daily_transit_routes.v1", data["schema_version"])
        self.assertEqual("南京", data["destination"])
        self.assertEqual("amap_transit", data["route_mode"])
        self.assertEqual(2, data["days_count"])
        self.assertGreaterEqual(data["candidate_count"], 4)
        self.assertEqual(1, data["research_summary"]["search_result_count"])
        self.assertEqual(1, data["research_summary"]["accepted_document_count"])
        self.assertEqual("deepseek_candidate_pool_agent", data["research_summary"]["candidate_builder"])
        self.assertEqual("deepseek-v4-flash", data["research_summary"]["model"])
        self.assertTrue(data["days"][0]["route_segments"])

    def test_generate_routes_returns_503_when_deepseek_candidate_pool_fails(self) -> None:
        """功能：验证候选池生成失败时规划接口返回 503。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证错误状态码和提示。
        """
        payload = {
            "destination": "南京",
            "days": 2,
            "max_search_results": 2,
            "max_candidates": 8,
        }
        with patch(
            "backend.app.workflows.research_route_planner.generate_hot_candidate_pool",
            side_effect=RuntimeError("缺少 DEEPSEEK_API_KEY"),
        ):
            response = self.client.post("/api/planner/generate", json=payload)

        self.assertEqual(503, response.status_code)
        self.assertIn("缺少 DEEPSEEK_API_KEY", response.json()["detail"])

    def test_itinerary_details_endpoint_enriches_existing_route_plan(self) -> None:
        """功能：验证详情接口会基于已有路线补齐日程、天气、餐厅和注意事项。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证详情字段。
        """
        route_plan = {
            "schema_version": "floattrip_daily_transit_routes.v1",
            "destination": "南京",
            "days_count": 1,
            "route_mode": "amap_transit",
            "days": [
                {
                    "day_index": 1,
                    "cluster_id": 0,
                    "spots": [
                        {
                            "spot_id": "poi-中山陵",
                            "name": "中山陵",
                            "order": 1,
                            "location": {"lng": 118.8482, "lat": 32.064},
                            "address": "石象路7号",
                            "poi_type": "风景名胜",
                        },
                        {
                            "spot_id": "poi-明孝陵",
                            "name": "明孝陵",
                            "order": 2,
                            "location": {"lng": 118.8355, "lat": 32.0572},
                            "address": "石象路7号",
                            "poi_type": "世界遗产",
                        },
                    ],
                    "route_order": ["中山陵", "明孝陵"],
                    "route_segments": [
                        {
                            "from_spot_id": "poi-中山陵",
                            "from_name": "中山陵",
                            "to_spot_id": "poi-明孝陵",
                            "to_name": "明孝陵",
                            "mode": "transit",
                            "duration_minutes": 20,
                            "summary": "景区接驳车约 20 分钟",
                        }
                    ],
                    "summary_metrics": {
                        "spot_count": 2,
                        "cluster_radius_km": 1.2,
                        "route_status": "route_planned",
                        "failed_segment_count": 0,
                    },
                    "optimized_order": ["poi-中山陵", "poi-明孝陵"],
                }
            ],
            "warnings": [],
        }
        payload = {
            "original_request": {
                "destination": "南京",
                "days": 1,
                "start_date": "2026-05-24",
                "preferences": ["文化历史"],
            },
            "route_plan": route_plan,
            "transport_mode": "amap_transit",
            "preferences": ["文化历史"],
            "start_date": "2026-05-24",
        }

        with patch(
            "backend.app.services.itinerary_details.amap_mcp.search_nearby_pois",
            return_value=[
                {
                    "name": "测试饭店",
                    "address": "测试路1号",
                    "distance_meters": 300,
                    "location": {"lng": 118.84, "lat": 32.05},
                }
            ],
        ), patch(
            "backend.app.services.itinerary_details.amap_mcp.query_weather",
            side_effect=RuntimeError("MCP unavailable"),
        ), patch(
            "backend.app.services.itinerary_details.amap.require_amap_key",
            return_value="test-key",
        ), patch(
            "backend.app.services.itinerary_details.amap.query_weather",
            return_value=[
                {
                    "date": "2026-05-24",
                    "dayweather": "晴",
                    "daytemp": "28",
                    "nighttemp": "18",
                    "daywind": "东风",
                }
            ],
        ):
            response = self.client.post("/api/planner/itinerary-details", json=payload)

        self.assertEqual(200, response.status_code)
        data = response.json()
        detail = data["days"][0]["itinerary_detail"]
        self.assertEqual(["中山陵", "明孝陵"], detail["original_route"])
        self.assertEqual("ok", detail["weather"]["status"])
        self.assertTrue(detail["activities"])
        self.assertEqual(2, len(detail["meals"]))
        self.assertTrue(detail["notices"])

    def test_itinerary_details_uses_nearest_weather_when_trip_date_is_out_of_range(self) -> None:
        """功能：验证出行日超出预报范围时仍展示最近可用天气参考。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证天气兜底字段。
        """
        route_plan = {
            "schema_version": "floattrip_daily_transit_routes.v1",
            "destination": "南京",
            "days_count": 1,
            "route_mode": "amap_transit",
            "days": [
                {
                    "day_index": 1,
                    "cluster_id": 0,
                    "spots": [
                        {
                            "spot_id": "poi-中山陵",
                            "name": "中山陵",
                            "order": 1,
                            "location": {"lng": 118.8482, "lat": 32.064},
                        }
                    ],
                    "route_order": ["中山陵"],
                    "route_segments": [],
                    "summary_metrics": {
                        "spot_count": 1,
                        "cluster_radius_km": 1.2,
                        "route_status": "route_planned",
                        "failed_segment_count": 0,
                    },
                    "optimized_order": ["poi-中山陵"],
                }
            ],
            "warnings": [],
        }
        payload = {
            "original_request": {
                "destination": "南京",
                "days": 1,
                "start_date": "2026-05-31",
            },
            "route_plan": route_plan,
            "start_date": "2026-05-31",
        }

        with patch(
            "backend.app.services.itinerary_details.amap_mcp.search_nearby_pois",
            return_value=[],
        ), patch(
            "backend.app.services.itinerary_details.amap_mcp.query_weather",
            return_value=[
                {
                    "date": "2026-05-24",
                    "dayweather": "多云",
                    "daytemp": "27",
                    "nighttemp": "19",
                    "daywind": "东风",
                }
            ],
        ), patch(
            "backend.app.services.itinerary_details.amap.require_amap_key",
            return_value=None,
        ):
            response = self.client.post("/api/planner/itinerary-details", json=payload)

        self.assertEqual(200, response.status_code)
        weather = response.json()["days"][0]["itinerary_detail"]["weather"]
        self.assertEqual("unavailable", weather["status"])
        self.assertEqual("多云", weather["weather"])
        self.assertEqual("2026-05-24", weather["date"])
        self.assertIn("高德目前可参考到 2026-05-24", weather["dressing_advice"])

    def test_itinerary_details_falls_back_to_amap_web_restaurants_when_mcp_fails(self) -> None:
        """功能：验证 MCP 餐饮不可用时会继续使用高德 Web 周边搜索。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证真实餐厅字段。
        """
        route_plan = {
            "schema_version": "floattrip_daily_transit_routes.v1",
            "destination": "南京",
            "days_count": 1,
            "route_mode": "amap_transit",
            "days": [
                {
                    "day_index": 1,
                    "cluster_id": 0,
                    "spots": [
                        {
                            "spot_id": "poi-中山陵",
                            "name": "中山陵",
                            "order": 1,
                            "location": {"lng": 118.8482, "lat": 32.064},
                        },
                        {
                            "spot_id": "poi-明孝陵",
                            "name": "明孝陵",
                            "order": 2,
                            "location": {"lng": 118.8355, "lat": 32.0572},
                        },
                    ],
                    "route_order": ["中山陵", "明孝陵"],
                    "route_segments": [],
                    "summary_metrics": {
                        "spot_count": 2,
                        "cluster_radius_km": 1.2,
                        "route_status": "route_planned",
                        "failed_segment_count": 0,
                    },
                    "optimized_order": ["poi-中山陵", "poi-明孝陵"],
                }
            ],
            "warnings": [],
        }
        payload = {
            "original_request": {
                "destination": "南京",
                "days": 1,
                "start_date": "2026-05-24",
            },
            "route_plan": route_plan,
            "start_date": "2026-05-24",
        }

        with patch(
            "backend.app.services.itinerary_details.amap_mcp.search_nearby_pois",
            side_effect=RuntimeError("MCP unavailable"),
        ), patch(
            "backend.app.services.itinerary_details.amap.search_around_pois",
            return_value=[
                {
                    "id": "food-1",
                    "name": "钟山茶餐厅",
                    "address": "石象路8号",
                    "distance": "450",
                    "location": "118.84,32.05",
                }
            ],
        ), patch(
            "backend.app.services.itinerary_details.amap_mcp.query_weather",
            return_value=[],
        ), patch(
            "backend.app.services.itinerary_details.amap.require_amap_key",
            return_value="test-key",
        ), patch(
            "backend.app.services.itinerary_details.amap.query_weather",
            return_value=[],
        ):
            response = self.client.post("/api/planner/itinerary-details", json=payload)

        self.assertEqual(200, response.status_code)
        meals = response.json()["days"][0]["itinerary_detail"]["meals"]
        self.assertEqual("钟山茶餐厅", meals[0]["restaurant_name"])
        self.assertEqual("石象路8号", meals[0]["address"])
        self.assertEqual(450, meals[0]["distance_meters"])
        self.assertEqual("amap", meals[0]["source_poi"]["provider"])

    def test_generate_request_splits_user_spot_text(self) -> None:
        """功能：验证请求模型会把中文标点、换行和分号分隔的景点拆成数组。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证字段归一化结果。
        """
        request = TripGenerateRouteRequest(
            destination="南京",
            days=3,
            preferred_spots=["中山陵、明孝陵，夫子庙;老门东\n南京博物院", "总统府", "中山陵"],
            avoided_spots="鸡鸣寺、玄武湖",
        )

        self.assertEqual(
            ["中山陵", "明孝陵", "夫子庙", "老门东", "南京博物院", "总统府"],
            request.preferred_spots,
        )
        self.assertEqual(["鸡鸣寺", "玄武湖"], request.avoided_spots)

    def test_merge_preferred_spots_treats_split_names_as_independent_candidates(self) -> None:
        """功能：验证必去景点合并逻辑会把拆分后的名称作为独立候选处理。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证候选名称列表。
        """
        request = TripGenerateRouteRequest(
            destination="南京",
            days=3,
            preferred_spots=["中山陵、明孝陵、夫子庙"],
        )

        merged = merge_preferred_spots([], request.preferred_spots)
        names = [candidate["name"] for candidate in merged]

        self.assertEqual(["中山陵", "夫子庙", "明孝陵"], names)
        self.assertNotIn("中山陵、明孝陵、夫子庙", names)


if __name__ == "__main__":
    unittest.main()


def fake_transit_route(
    origin_lnglat: str,
    destination_lnglat: str,
    city: str,
    api_key: str,
    strategy: int = 0,
) -> dict:
    """功能：构造模拟高德公交路线结果。

    参数：
        origin_lnglat：起点坐标字符串，格式为 "lng,lat"。
        destination_lnglat：终点坐标字符串，格式为 "lng,lat"。
        city：公交规划城市名称。
        api_key：测试用高德 Key。
        strategy：公交策略参数。
    返回值：
        返回符合路线规划内部结构的模拟公交路线字典。
    """
    origin_lng, origin_lat = [float(value) for value in origin_lnglat.split(",")]
    destination_lng, destination_lat = [
        float(value) for value in destination_lnglat.split(",")
    ]
    distance = int(
        ((origin_lng - destination_lng) ** 2 + (origin_lat - destination_lat) ** 2)
        ** 0.5
        * 100000
    )
    duration = max(600, distance * 2)
    return {
        "mode": "transit",
        "duration_seconds": duration,
        "duration_minutes": round(duration / 60, 1),
        "distance_meters": distance,
        "walking_distance_meters": 300,
        "cost": "2",
        "summary": f"{city}模拟公交",
        "amap_transit": {"duration": str(duration), "distance": str(distance), "segments": []},
        "path": [
            {"lng": origin_lng, "lat": origin_lat},
            {"lng": destination_lng, "lat": destination_lat},
        ],
    }


def fake_pois(keyword: str, admin_region: str, api_key: str, offset: int) -> list[dict]:
    """功能：构造模拟高德 POI 搜索结果。

    参数：
        keyword：搜索关键词。
        admin_region：行政区名称或编码，本测试中仅保留接口形态。
        api_key：测试用高德 Key。
        offset：搜索结果数量，本测试中仅保留接口形态。
    返回值：
        返回包含坐标、行政区和景点类型的模拟 POI 列表。
    """
    locations = {
        "中山陵": "118.8482,32.0640",
        "明孝陵": "118.8355,32.0572",
        "夫子庙": "118.7881,32.0206",
        "老门东": "118.7927,32.0142",
        "南京博物院": "118.8172,32.0411",
        "总统府": "118.7976,32.0443",
    }
    location = locations.get(keyword, "118.8000,32.0400")
    return [
        {
            "id": f"poi-{keyword}",
            "name": keyword,
            "type": "风景名胜;风景名胜",
            "pname": "江苏省",
            "cityname": "南京市",
            "adname": "玄武区",
            "adcode": "320102",
            "address": f"{keyword}地址",
            "location": location,
        }
    ]
