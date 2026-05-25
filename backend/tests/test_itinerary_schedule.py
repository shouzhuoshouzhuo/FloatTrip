"""行程详情时间线单元测试。

功能：
    验证行程详情页时间线在单景点和双景点场景下，会把景点安排到午餐和晚餐之间。
"""

import unittest

from backend.app.schemas.route_plan import (
    DayRoutePlan,
    DaySummaryMetrics,
    MealRecommendation,
    RouteSegment,
    SpotMapItem,
)
from backend.app.schemas.trip_request import Location
from backend.app.services import itinerary_details


class ItineraryScheduleTests(unittest.TestCase):
    """功能：覆盖行程详情时间线的餐饮与景点穿插规则。"""

    def test_two_spot_day_places_second_spot_between_lunch_and_dinner(self) -> None:
        """功能：验证两个景点时上午和下午各安排一个景点。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证午餐和晚餐之间存在下午景点。
        """
        day = fake_day(["南京欢乐谷", "南京玛雅海滩水公园"])
        activities = itinerary_details.build_activities(day, fake_meals())

        titles = [activity.title for activity in activities]
        lunch_index = next(index for index, title in enumerate(titles) if title.startswith("午餐推荐"))
        dinner_index = next(index for index, title in enumerate(titles) if title.startswith("晚餐推荐"))
        between_meals = activities[lunch_index + 1 : dinner_index]

        self.assertIn("南京欢乐谷（上午）", titles)
        self.assertTrue(
            any(activity.type == "spot" and activity.title == "南京玛雅海滩水公园（下午）" for activity in between_meals)
        )

    def test_single_spot_day_places_same_large_spot_morning_and_afternoon(self) -> None:
        """功能：验证单景点时拆分为上午和下午两段游览。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证午餐和晚餐之间存在同一景点下午段。
        """
        day = fake_day(["南京欢乐谷"])
        activities = itinerary_details.build_activities(day, fake_meals())

        titles = [activity.title for activity in activities]
        lunch_index = next(index for index, title in enumerate(titles) if title.startswith("午餐推荐"))
        dinner_index = next(index for index, title in enumerate(titles) if title.startswith("晚餐推荐"))
        between_meals = activities[lunch_index + 1 : dinner_index]

        self.assertIn("南京欢乐谷（上午）", titles)
        self.assertTrue(any(activity.type == "spot" and activity.title == "南京欢乐谷（下午）" for activity in between_meals))


def fake_day(names: list[str]) -> DayRoutePlan:
    """功能：构造测试用单日路线。

    参数：
        names：景点名称列表。
    返回值：
        返回可传入 build_activities 的 DayRoutePlan。
    """
    spots = [
        SpotMapItem(
            spot_id=f"poi-{index}",
            name=name,
            order=index,
            location=Location(lng=118.8 + index * 0.01, lat=32.0),
            poi_type="风景名胜",
        )
        for index, name in enumerate(names, start=1)
    ]
    route_segments = [
        RouteSegment(
            from_spot_id=spots[index].spot_id,
            from_name=spots[index].name,
            to_spot_id=spots[index + 1].spot_id,
            to_name=spots[index + 1].name,
            mode="walking",
            duration_minutes=15,
            summary="步行约 15 分钟",
        )
        for index in range(len(spots) - 1)
    ]
    return DayRoutePlan(
        day_index=1,
        cluster_id=0,
        spots=spots,
        route_order=[spot.name for spot in spots],
        route_segments=route_segments,
        summary_metrics=DaySummaryMetrics(spot_count=len(spots), cluster_radius_km=1.0),
        optimized_order=[spot.spot_id for spot in spots if spot.spot_id],
    )


def fake_meals() -> list[MealRecommendation]:
    """功能：构造测试用午餐和晚餐推荐。

    参数：
        无。
    返回值：
        返回午餐和晚餐推荐列表。
    """
    return [
        MealRecommendation(meal_type="lunch", restaurant_name="午餐店", reason="就近午餐"),
        MealRecommendation(meal_type="dinner", restaurant_name="晚餐店", reason="就近晚餐"),
    ]


if __name__ == "__main__":
    unittest.main()
