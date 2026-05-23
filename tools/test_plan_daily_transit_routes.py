import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plan_daily_transit_routes as planner


def candidate(name: str, lng: float, lat: float, score: int = 5) -> dict:
    return {
        "name": name,
        "mention_count": score,
        "score": score,
        "preference_score": score,
        "poi": {
            "id": f"poi-{name}",
            "name": name,
            "type": "风景名胜",
            "address": f"{name}地址",
            "district": "测试区",
            "location": {"lng": lng, "lat": lat},
        },
    }


def transit(duration_seconds: int) -> dict:
    return {
        "duration_seconds": duration_seconds,
        "duration_minutes": round(duration_seconds / 60, 1),
        "distance_meters": duration_seconds * 2,
        "walking_distance_meters": 100,
        "cost": "2.0",
        "segments_count": 1,
        "summary": "地铁1号线: A -> B",
        "amap_transit": {
            "duration": str(duration_seconds),
            "distance": str(duration_seconds * 2),
            "walking_distance": "100",
            "cost": "2.0",
            "segments": [],
        },
        "path": [
            {"lng": 119.970, "lat": 31.780},
            {"lng": 119.971, "lat": 31.781},
        ],
    }


def walking(duration_seconds: int = 240) -> dict:
    return {
        "duration_seconds": duration_seconds,
        "duration_minutes": round(duration_seconds / 60, 1),
        "distance_meters": 260,
        "walking_distance_meters": 260,
        "cost": None,
        "segments_count": 1,
        "summary": "步行约 0.3 km",
        "amap_transit": None,
        "fallback_mode": "walking",
        "path": [
            {"lng": 118.797398, "lat": 32.044228},
            {"lng": 118.798000, "lat": 32.043600},
            {"lng": 118.799124, "lat": 32.042840},
        ],
    }


class PlanDailyTransitRoutesTests(unittest.TestCase):
    def test_build_transit_time_matrix_uses_locations_without_geocoding(self) -> None:
        pool = [
            candidate("甲", 119.970, 31.780),
            candidate("乙", 119.971, 31.781),
            candidate("丙", 119.972, 31.782),
        ]

        def fake_query(origin, destination, city, api_key, strategy):
            self.assertIn(",", origin)
            self.assertIn(",", destination)
            self.assertEqual("常州", city)
            self.assertEqual("test-key", api_key)
            self.assertEqual(0, strategy)
            return transit(600 if origin < destination else 900)

        with patch.object(planner, "query_amap_transit_by_location", side_effect=fake_query):
            matrix, segments, warnings = planner.build_transit_time_matrix(
                pool,
                "常州",
                "test-key",
                request_interval=0,
            )

        self.assertEqual(0, matrix[0][0])
        self.assertEqual(600, matrix[0][1])
        self.assertEqual(900, matrix[2][0])
        self.assertEqual(6, len(segments))
        self.assertEqual([], warnings)

    def test_optimize_visit_order_selects_shortest_complete_permutation(self) -> None:
        pool = [
            candidate("甲", 119.970, 31.780),
            candidate("乙", 119.971, 31.781),
            candidate("丙", 119.972, 31.782),
        ]
        matrix = [
            [0, 10, 100],
            [50, 0, 10],
            [10, 50, 0],
        ]

        order, complete = planner.optimize_visit_order(pool, matrix)

        self.assertTrue(complete)
        self.assertEqual([0, 1, 2], order)

    def test_failed_segment_records_warning_and_keeps_available_route(self) -> None:
        pool = [
            candidate("甲", 119.970, 31.780, score=10),
            candidate("乙", 119.971, 31.781, score=9),
            candidate("丙", 120.030, 31.840, score=8),
        ]
        calls = {}

        def fake_query(origin, destination, _city, _api_key, _strategy):
            calls[(origin, destination)] = True
            if origin.startswith("119.97,") and destination.startswith("120.03,"):
                raise planner.AMapTransitError("no transit")
            return transit(600)

        with patch.object(planner, "query_amap_transit_by_location", side_effect=fake_query):
            matrix, _segments, warnings = planner.build_transit_time_matrix(
                pool,
                "常州",
                "test-key",
                request_interval=0,
            )

        self.assertIsNone(matrix[0][2])
        self.assertGreaterEqual(len(calls), 6)
        self.assertIn("甲 -> 丙", warnings[0])

        order, complete = planner.optimize_visit_order(pool, matrix)
        self.assertTrue(complete)
        self.assertNotEqual([0, 2], order[:2])

    def test_nearby_failed_transit_uses_walking_fallback_and_improves_order(self) -> None:
        pool = [
            candidate("总统府", 118.797398, 32.044228, score=10),
            candidate("古鸡鸣寺", 118.795246, 32.061061, score=9),
            candidate("六朝博物馆", 118.799124, 32.04284, score=8),
            candidate("玄武湖", 118.801541, 32.072217, score=7),
        ]

        durations = {
            ("总统府", "古鸡鸣寺"): 1600,
            ("古鸡鸣寺", "总统府"): 1500,
            ("古鸡鸣寺", "六朝博物馆"): 1427,
            ("六朝博物馆", "古鸡鸣寺"): 1626,
            ("六朝博物馆", "玄武湖"): 2228,
            ("古鸡鸣寺", "玄武湖"): 900,
            ("总统府", "玄武湖"): 2280,
            ("玄武湖", "古鸡鸣寺"): 900,
            ("玄武湖", "总统府"): 2200,
            ("玄武湖", "六朝博物馆"): 2100,
            ("六朝博物馆", "总统府"): 240,
        }

        def fake_query(origin, destination, _city, _api_key, _strategy):
            origin_name = next(item["name"] for item in pool if planner.lnglat_text(item) == origin)
            destination_name = next(item["name"] for item in pool if planner.lnglat_text(item) == destination)
            if (origin_name, destination_name) == ("总统府", "六朝博物馆"):
                raise planner.AMapTransitError("no transit")
            return transit(durations.get((origin_name, destination_name), 3000))

        with (
            patch.object(planner, "query_amap_transit_by_location", side_effect=fake_query),
            patch.object(planner, "query_amap_walking_by_location", return_value=walking(180)),
        ):
            matrix, segments, warnings = planner.build_transit_time_matrix(
                pool,
                "南京",
                "test-key",
                request_interval=0,
            )

        self.assertLess(matrix[0][2], 300)
        self.assertEqual("walking", segments[(0, 2)]["fallback_mode"])
        self.assertGreater(len(segments[(0, 2)]["path"]), 1)
        self.assertIn("步行兜底", warnings[0])

        order, complete = planner.optimize_visit_order(pool, matrix)

        self.assertTrue(complete)
        self.assertEqual([0, 2], order[:2])

    def test_daily_candidate_selection_replaces_far_spot_with_nearby_candidate(self) -> None:
        zhan_yuan = candidate("瞻园", 118.785163, 32.021034, score=15)
        fuzimiao = candidate("南京夫子庙", 118.788899, 32.02066, score=9)
        niushou = candidate("牛首山", 118.744427, 31.912767, score=8)
        zhonghua_gate = candidate("中华门", 118.781821, 32.0128, score=3)
        memorial = candidate("南京大屠杀遇难同胞纪念馆", 118.742372, 32.035217, score=5)
        for item in (zhan_yuan, fuzimiao, zhonghua_gate):
            item["poi"]["district"] = "秦淮区"
        niushou["poi"]["district"] = "江宁区"
        memorial["poi"]["district"] = "建邺区"

        selected = planner.select_daily_candidates(
            [zhan_yuan, fuzimiao, niushou],
            all_candidates=[zhan_yuan, fuzimiao, niushou, zhonghua_gate, memorial],
            blocked_candidate_ids={
                planner.candidate_identity(zhan_yuan),
                planner.candidate_identity(fuzimiao),
                planner.candidate_identity(niushou),
            },
            medoid=zhan_yuan,
            max_day_radius_km=6,
        )

        names = [item["name"] for item in selected]
        self.assertIn("中华门", names)
        self.assertNotIn("南京大屠杀遇难同胞纪念馆", names)
        self.assertNotIn("牛首山", names)

    def test_missing_location_returns_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "poi.location"):
            planner.candidate_location({"name": "坏点", "mention_count": 1, "poi": {}})

    def test_extracts_transit_polyline_from_walking_and_bus_segments(self) -> None:
        best = {
            "segments": [
                {
                    "walking": {
                        "steps": [
                            {"polyline": "118.1,32.1;118.2,32.2"},
                        ]
                    },
                    "bus": {
                        "buslines": [
                            {"polyline": "118.2,32.2;118.3,32.3"}
                        ]
                    },
                }
            ]
        }

        self.assertEqual(
            [
                {"lng": 118.1, "lat": 32.1},
                {"lng": 118.2, "lat": 32.2},
                {"lng": 118.3, "lat": 32.3},
            ],
            planner.extract_transit_path(best),
        )

    def test_real_path_is_copied_to_route_segments(self) -> None:
        spots = [
            {"spot_id": "a", "name": "甲"},
            {"spot_id": "b", "name": "乙"},
        ]
        matrix = [[0, 120], [120, 0]]
        segment_results = {(0, 1): transit(120)}

        segments = planner.build_route_segments([0, 1], spots, matrix, segment_results)

        self.assertGreater(len(segments[0]["path"]), 1)

    def test_missing_transit_polyline_records_warning(self) -> None:
        pool = [
            candidate("甲", 119.970, 31.780),
            candidate("乙", 119.971, 31.781),
        ]
        missing_path_transit = dict(transit(600))
        missing_path_transit["path"] = []

        with patch.object(planner, "query_amap_transit_by_location", return_value=missing_path_transit):
            _matrix, _segments, warnings = planner.build_transit_time_matrix(
                pool,
                "常州",
                "test-key",
                request_interval=0,
            )

        self.assertIn("未返回真实路径 polyline", warnings[0])

    def test_cli_outputs_schema_version_json_without_real_network(self) -> None:
        payload = {
            "destination": "常州",
            "candidate_pool": [
                candidate("甲", 119.970, 31.780, score=10),
                candidate("乙", 119.971, 31.781, score=9),
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "amap_candidates.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            stdout = io.StringIO()
            with (
                patch.object(sys, "argv", ["plan_daily_transit_routes.py", str(input_path), "--days", "1"]),
                patch.object(planner, "require_amap_key", return_value="test-key"),
                patch.object(planner, "query_amap_transit_by_location", return_value=transit(600)),
                contextlib.redirect_stdout(stdout),
            ):
                return_code = planner.main()

        self.assertEqual(0, return_code)
        data = json.loads(stdout.getvalue())
        self.assertEqual(planner.SCHEMA_VERSION, data["schema_version"])
        self.assertEqual("amap_transit", data["route_mode"])
        self.assertEqual(1, len(data["days"]))
        self.assertEqual(["poi-甲", "poi-乙"], data["days"][0]["optimized_order"])


if __name__ == "__main__":
    unittest.main()
