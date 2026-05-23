import math
import unittest

from backend.app.planning import day_clustering as clusters


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


class BackendGeoDayClusterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
