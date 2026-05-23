import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.services.travel_research import (
    AttractionCandidate,
    CandidatePool,
    ResearchBundle,
    ResearchDocument,
    SearchResult,
)
from backend.app.workflows.research_route_planner import merge_preferred_spots


class PlannerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

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
                    text=(
                        "## 南京两日游攻略\n\n"
                        "中山陵 明孝陵 夫子庙 老门东 南京博物院 总统府 "
                        "中山陵 夫子庙 明孝陵 老门东 南京博物院 总统府"
                    ),
                )
            ],
            warnings=[],
        )

        with patch(
            "backend.app.workflows.research_route_planner.collect_research",
            return_value=bundle,
        ) as collect_research, patch(
            "backend.app.services.travel_research.build_structured_deepseek",
            return_value=FakeStructuredLlm(),
        ), patch(
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
        self.assertEqual("deepseek_markdown", data["research_summary"]["candidate_builder"])
        self.assertEqual("deepseek-v4-flash", data["research_summary"]["model"])
        self.assertTrue(data["days"][0]["route_segments"])

    def test_generate_routes_returns_503_when_deepseek_candidate_pool_fails(self) -> None:
        payload = {
            "destination": "南京",
            "days": 2,
            "max_search_results": 2,
            "max_candidates": 8,
        }
        bundle = ResearchBundle(
            query_plan=["南京 两日游 攻略 景点"],
            search_results=[
                SearchResult(
                    title="南京两日游攻略",
                    url="https://example.com/nanjing",
                    snippet="中山陵 明孝陵",
                    source="test",
                )
            ],
            documents=[
                ResearchDocument(
                    title="南京两日游攻略",
                    url="https://example.com/nanjing",
                    source="test",
                    text="## 南京两日游攻略\n\n中山陵 明孝陵 夫子庙 老门东",
                )
            ],
            warnings=[],
        )

        with patch(
            "backend.app.workflows.research_route_planner.collect_research",
            return_value=bundle,
        ), patch(
            "backend.app.services.travel_research.build_structured_deepseek",
            side_effect=RuntimeError("缺少 DEEPSEEK_API_KEY"),
        ):
            response = self.client.post("/api/planner/generate", json=payload)

        self.assertEqual(503, response.status_code)
        self.assertIn("缺少 DEEPSEEK_API_KEY", response.json()["detail"])

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


class FakeStructuredLlm:
    def invoke(self, _messages: list[tuple[str, str]]) -> CandidatePool:
        return CandidatePool(
            candidate_pool=[
                AttractionCandidate(name="中山陵", preference_score=10),
                AttractionCandidate(name="明孝陵", preference_score=8),
                AttractionCandidate(name="夫子庙", preference_score=7),
                AttractionCandidate(name="老门东", preference_score=6),
                AttractionCandidate(name="南京博物院", preference_score=9),
                AttractionCandidate(name="总统府", preference_score=5),
            ]
        )


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
