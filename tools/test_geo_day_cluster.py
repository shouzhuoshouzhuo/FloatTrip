import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geo_day_cluster as clusters


def candidate(
    name: str,
    lng: float,
    lat: float,
    *,
    mention_count: int = 1,
    score: int | None = None,
) -> dict:
    item = {
        "name": name,
        "mention_count": mention_count,
        "poi": {
            "id": f"poi-{name}",
            "location": {"lng": lng, "lat": lat},
        },
    }
    if score is not None:
        item["score"] = score
    return item


class GeoDayClusterTests(unittest.TestCase):
    def test_clusters_clear_geographic_areas_with_real_medoids_and_radius(self) -> None:
        pool = [
            candidate("老城甲", 119.970, 31.780, mention_count=8),
            candidate("老城乙", 119.974, 31.782, mention_count=5),
            candidate("湖区甲", 120.020, 31.720, mention_count=7),
            candidate("湖区乙", 120.024, 31.724, mention_count=4),
            candidate("山麓甲", 119.890, 31.845, mention_count=6),
            candidate("山麓乙", 119.895, 31.848, mention_count=3),
        ]

        result = clusters.cluster_candidates_by_days(pool, 3)

        self.assertEqual(3, len(result))
        self.assertEqual([0, 1, 2], [cluster["cluster_id"] for cluster in result])
        for cluster in result:
            self.assertIn(cluster["medoid"], cluster["candidates"])
            self.assertGreaterEqual(len(cluster["candidates"]), 2)
            self.assertGreater(cluster["radius_km"], 0)

    def test_haversine_uses_kilometers_for_near_and_far_points(self) -> None:
        near = clusters.haversine_km((119.970, 31.780), (119.971, 31.780))
        far = clusters.haversine_km((119.970, 31.780), (120.070, 31.780))

        self.assertGreater(near, 0)
        self.assertLess(near, 0.2)
        self.assertGreater(far, 9)

    def test_mention_weight_can_move_single_cluster_medoid(self) -> None:
        pool = [
            candidate("西端", 119.970, 31.780, mention_count=1),
            candidate("中点", 119.980, 31.780, mention_count=1),
            candidate("东端高频", 119.990, 31.780, mention_count=100),
        ]

        result = clusters.cluster_candidates_by_days(pool, 1)

        self.assertEqual("东端高频", result[0]["medoid"]["name"])
        self.assertAlmostEqual(1 + math.log(100), clusters.mention_weight(pool[2]))

    def test_candidate_window_prefers_score_then_mention_count(self) -> None:
        pool = [
            candidate("mention fallback", 119.970, 31.780, mention_count=9),
            candidate("score winner", 119.971, 31.780, mention_count=1, score=20),
            candidate("score runner up", 119.972, 31.780, mention_count=1, score=8),
            candidate("score third", 119.973, 31.780, mention_count=1, score=7),
            candidate("truncated", 119.974, 31.780, mention_count=6, score=1),
        ]

        selected = clusters.prepare_candidates_for_clustering(pool, 1)

        self.assertEqual(4, len(selected))
        self.assertEqual(
            ["score winner", "mention fallback", "score runner up", "score third"],
            [item["name"] for item in selected],
        )

    def test_repairs_small_cluster_to_minimum_size(self) -> None:
        pool = [
            candidate("核心甲", 119.970, 31.780, mention_count=10),
            candidate("核心乙", 119.971, 31.780, mention_count=8),
            candidate("核心丙", 119.972, 31.780, mention_count=7),
            candidate("核心丁", 119.973, 31.780, mention_count=6),
            candidate("远点", 120.080, 31.900, mention_count=9),
        ]

        result = clusters.cluster_candidates_by_days(pool, 2)

        self.assertEqual([2, 3], sorted(len(cluster["candidates"]) for cluster in result))

    def test_rejects_invalid_inputs_and_coordinates(self) -> None:
        with self.assertRaisesRegex(ValueError, "days"):
            clusters.cluster_candidates_by_days([candidate("景点", 119.97, 31.78)], 0)
        with self.assertRaisesRegex(ValueError, "at least 4 candidates"):
            clusters.cluster_candidates_by_days(
                [candidate("甲", 119.97, 31.78), candidate("乙", 119.98, 31.78), candidate("丙", 119.99, 31.78)],
                2,
            )
        with self.assertRaisesRegex(ValueError, "poi.location"):
            clusters.cluster_candidates_by_days(
                [
                    {"name": "坏点", "mention_count": 1, "poi": {}},
                    candidate("好点", 119.97, 31.78),
                ],
                1,
            )
        with self.assertRaisesRegex(ValueError, "invalid lng"):
            clusters.cluster_candidates_by_days(
                [
                    candidate("好点", 119.97, 31.78),
                    candidate("坏坐标", float("nan"), 31.78),
                ],
                1,
            )
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            clusters.cluster_candidates_by_days(
                [candidate("景点", 119.97, 31.78)],
                1,
                min_cluster_size=5,
            )


if __name__ == "__main__":
    unittest.main()
