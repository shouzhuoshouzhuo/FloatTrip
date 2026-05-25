"""每日地理聚类算法单元测试。

功能：
    验证候选景点按地理位置分天、球面距离计算和提及次数权重对聚类中心的影响。
"""

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
    user_requested: bool = False,
) -> dict:
    """功能：构造带高德坐标的测试候选景点。

    参数：
        name：候选景点名称。
        lng：候选景点经度。
        lat：候选景点纬度。
        mention_count：候选景点在语料中的出现次数。
        score：可选排序分数。
        user_requested：是否是用户指定必去景点。
    返回值：
        返回符合聚类输入格式的候选景点字典。
    """
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
    if user_requested:
        item["user_requested"] = True
    return item


class BackendGeoDayClusterTests(unittest.TestCase):
    """功能：覆盖后端每日地理聚类的核心路径。"""

    def test_clusters_clear_geographic_areas_with_real_medoids_and_radius(self) -> None:
        """功能：验证清晰地理区域能被分成真实中心点和有效半径的每日簇。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证聚类结果。
        """
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
        """功能：验证球面距离函数使用公里单位并能区分近点和远点。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证距离范围。
        """
        near = clusters.haversine_km((119.970, 31.780), (119.971, 31.780))
        far = clusters.haversine_km((119.970, 31.780), (120.070, 31.780))

        self.assertGreater(near, 0)
        self.assertLess(near, 0.2)
        self.assertGreater(far, 9)

    def test_mention_weight_can_move_single_cluster_medoid(self) -> None:
        """功能：验证高频提及景点可以通过权重影响单簇中心选择。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证中心点和权重。
        """
        pool = [
            candidate("西端", 119.970, 31.780, mention_count=1),
            candidate("中点", 119.980, 31.780, mention_count=1),
            candidate("东端高频", 119.990, 31.780, mention_count=100),
        ]

        result = clusters.cluster_candidates_by_days(pool, 1)

        self.assertEqual("东端高频", result[0]["medoid"]["name"])
        self.assertAlmostEqual(1 + math.log(100), clusters.mention_weight(pool[2]))

    def test_prepare_candidates_limits_clustering_input_to_three_per_day(self) -> None:
        """功能：验证聚类输入只保留候选池前 3 * days 个景点。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证截取数量和候选名称。
        """
        pool = [
            candidate(f"景点{index}", 119.970 + index * 0.001, 31.780, score=100 - index)
            for index in range(8)
        ]

        selected = clusters.prepare_candidates_for_clustering(pool, 2)

        self.assertEqual(6, len(selected))
        self.assertEqual(
            ["景点0", "景点1", "景点2", "景点3", "景点4", "景点5"],
            [item["name"] for item in selected],
        )

    def test_user_requested_candidates_are_pinned_before_tail_is_trimmed(self) -> None:
        """功能：验证用户必去景点会置顶进入聚类输入并挤掉末尾普通候选。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证必去景点保留和末尾候选删除。
        """
        pool = [
            candidate("高分1", 119.970, 31.780, score=100),
            candidate("高分2", 119.971, 31.780, score=90),
            candidate("高分3", 119.972, 31.780, score=80),
            candidate("高分4", 119.973, 31.780, score=70),
            candidate("高分5", 119.974, 31.780, score=60),
            candidate("高分6", 119.975, 31.780, score=50),
            candidate("用户必去", 119.976, 31.780, score=1, user_requested=True),
        ]

        selected = clusters.prepare_candidates_for_clustering(pool, 2)
        names = [item["name"] for item in selected]

        self.assertEqual("用户必去", names[0])
        self.assertIn("用户必去", names)
        self.assertNotIn("高分6", names)
        self.assertEqual(6, len(selected))


if __name__ == "__main__":
    unittest.main()
