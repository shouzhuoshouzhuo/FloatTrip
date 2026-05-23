import unittest

from fastapi.testclient import TestClient

from backend.app.main import app


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
            ["day_index", "cluster_id", "spots", "route_order", "route_segments", "summary_metrics"],
            list(data["days"][0].keys()),
        )

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


if __name__ == "__main__":
    unittest.main()
