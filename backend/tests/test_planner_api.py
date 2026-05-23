import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.services.travel_research import ResearchBundle, ResearchDocument, SearchResult
from backend.app.workflows.research_route_planner import merge_preferred_spots


def candidate(name: str, lng: float, lat: float, mention_count: int = 3, score: int = 5) -> dict:
    return {
        "name": name,
        "mention_count": mention_count,
        "score": score,
        "poi": {
            "provider": "amap",
            "id": f"poi-{name}",
            "name": name,
            "type": "风景名胜",
            "address": f"{name}地址",
            "location": {"lng": lng, "lat": lat},
        },
    }


class PlannerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    def test_cluster_routes_returns_map_ready_days(self) -> None:
        payload = {
            "destination": "常州",
            "days": 2,
            "candidates": [
                candidate("老城甲", 119.970, 31.780, score=10),
                candidate("老城乙", 119.974, 31.782, score=8),
                candidate("湖区甲", 120.020, 31.720, score=9),
                candidate("湖区乙", 120.024, 31.724, score=7),
            ],
        }

        response = self.client.post("/api/planner/cluster-routes", json=payload)

        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("常州", data["destination"])
        self.assertEqual(2, len(data["days"]))
        self.assertEqual("route_pending", data["days"][0]["summary_metrics"]["route_status"])
        self.assertEqual([], data["days"][0]["route_segments"])
        self.assertEqual(
            [
                "day_index",
                "cluster_id",
                "spots",
                "route_order",
                "route_segments",
                "summary_metrics",
                "duration_matrix_seconds",
                "optimized_order",
            ],
            list(data["days"][0].keys()),
        )

    def test_transit_routes_returns_frontend_ready_nanjing_three_day_json(self) -> None:
        payload = {
            "destination": "南京",
            "days": 3,
            "candidates": [
                candidate("中山陵", 118.8482, 32.0640, score=10),
                candidate("明孝陵", 118.8355, 32.0572, score=9),
                candidate("夫子庙", 118.7881, 32.0206, score=10),
                candidate("老门东", 118.7927, 32.0142, score=8),
                candidate("南京博物院", 118.8172, 32.0411, score=9),
                candidate("总统府", 118.7976, 32.0443, score=8),
            ],
        }

        with patch(
            "backend.app.workflows.trip_planner_graph.require_amap_key",
            return_value="test-key",
        ), patch(
            "backend.app.planning.transit_routes.time.sleep",
            return_value=None,
        ), patch(
            "backend.app.planning.transit_routes.amap.query_transit_route",
            side_effect=fake_transit_route,
        ):
            response = self.client.post("/api/planner/transit-routes", json=payload)

        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("floattrip_daily_transit_routes.v1", data["schema_version"])
        self.assertEqual("南京", data["destination"])
        self.assertEqual(3, data["days_count"])
        self.assertEqual("amap_transit", data["route_mode"])
        self.assertEqual(3, len(data["days"]))
        for day in data["days"]:
            self.assertEqual("route_planned", day["summary_metrics"]["route_status"])
            self.assertGreaterEqual(len(day["spots"]), 2)
            self.assertEqual(len(day["spots"]) - 1, len(day["route_segments"]))
            self.assertEqual(len(day["spots"]), len(day["optimized_order"]))
            self.assertTrue(day["route_segments"][0]["path"])
            self.assertIn("lng", day["route_segments"][0]["path"][0])
            self.assertIn("lat", day["route_segments"][0]["path"][0])

    def test_cluster_routes_returns_clear_error_for_missing_location(self) -> None:
        payload = {
            "destination": "常州",
            "days": 1,
            "candidates": [
                {
                    "name": "坏点",
                    "mention_count": 2,
                    "poi": {
                        "provider": "amap",
                        "location": {"lng": 119.970},
                    },
                }
            ],
        }

        response = self.client.post("/api/planner/cluster-routes", json=payload)

        self.assertEqual(422, response.status_code)

    def test_cluster_routes_returns_400_for_insufficient_candidates(self) -> None:
        payload = {
            "destination": "常州",
            "days": 2,
            "candidates": [
                candidate("甲", 119.970, 31.780),
                candidate("乙", 119.974, 31.782),
            ],
        }

        response = self.client.post("/api/planner/cluster-routes", json=payload)

        self.assertEqual(400, response.status_code)
        self.assertIn("need at least 4 candidates", response.json()["detail"])

    def test_generate_routes_runs_research_poi_and_transit_pipeline(self) -> None:
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
                    text="中山陵 明孝陵 夫子庙 老门东 南京博物院 总统府 中山陵 夫子庙",
                )
            ],
            warnings=[],
        )

        with patch(
            "backend.app.workflows.research_route_planner.collect_research",
            return_value=bundle,
        ) as collect_research, patch(
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
        collect_research.assert_called_once()
        data = response.json()
        self.assertEqual("floattrip_daily_transit_routes.v1", data["schema_version"])
        self.assertEqual("南京", data["destination"])
        self.assertEqual("amap_transit", data["route_mode"])
        self.assertEqual(2, data["days_count"])
        self.assertGreaterEqual(data["candidate_count"], 4)
        self.assertEqual(1, data["research_summary"]["search_result_count"])
        self.assertEqual(1, data["research_summary"]["accepted_document_count"])
        self.assertTrue(data["days"][0]["route_segments"])

    def test_generate_request_splits_user_spot_text(self) -> None:
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
