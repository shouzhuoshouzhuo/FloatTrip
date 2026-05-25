"""高德服务提供方单元测试。

功能：
    验证高德 POI 搜索参数和限流重试逻辑，避免候选池补坐标时因为瞬时限流丢失过多地点。
"""

import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from backend.app.providers import amap


class AmapProviderTests(unittest.TestCase):
    """功能：覆盖高德搜索参数和重试行为。"""

    def test_search_requests_full_poi_fields_for_adcode_check(self) -> None:
        """功能：验证地点搜索请求会读取完整 POI 字段以支持行政区编码判断。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证请求参数。
        """
        with patch.object(
            amap,
            "http_get_json",
            return_value={"status": "1", "pois": []},
        ) as http_get_json:
            amap.search_amap_pois("中山陵", "320400", "test-key", 5)

        query = parse_qs(urlparse(http_get_json.call_args.args[0]).query)
        self.assertEqual(["all"], query["extensions"])

    def test_search_retries_when_amap_qps_limit_is_hit(self) -> None:
        """功能：验证高德 QPS 限流时会重试搜索请求。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证限流恢复后的 POI 返回。
        """
        recovered_pois = [{"name": "拙政园"}]
        with (
            patch.object(
                amap,
                "http_get_json",
                side_effect=[
                    {"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT"},
                    {"status": "1", "pois": recovered_pois},
                ],
            ) as http_get_json,
            patch.object(amap.time, "sleep") as sleep,
        ):
            pois = amap.search_amap_pois("拙政园", "苏州", "test-key", 5)

        self.assertEqual(recovered_pois, pois)
        self.assertEqual(2, http_get_json.call_count)
        sleep.assert_called_once()

    def test_search_around_pois_uses_location_and_radius(self) -> None:
        """功能：验证周边搜索会把坐标、半径和关键词传给高德接口。

        参数：
            无。
        返回值：
            无返回值；通过 mock 断言验证请求参数。
        """
        with patch.object(
            amap,
            "http_get_json",
            return_value={"status": "1", "pois": [{"name": "附近餐厅"}]},
        ) as http_get_json:
            pois = amap.search_around_pois(
                "餐厅",
                {"lng": 118.84, "lat": 32.05},
                "test-key",
                radius=3000,
                offset=5,
            )

        query = parse_qs(urlparse(http_get_json.call_args.args[0]).query)
        self.assertEqual([{"name": "附近餐厅"}], pois)
        self.assertEqual(["餐厅"], query["keywords"])
        self.assertEqual(["118.84,32.05"], query["location"])
        self.assertEqual(["3000"], query["radius"])
        self.assertEqual(["5"], query["offset"])


if __name__ == "__main__":
    unittest.main()
