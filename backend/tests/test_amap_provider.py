import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from backend.app.providers import amap


class AmapProviderTests(unittest.TestCase):
    def test_poi_must_match_requested_district_name(self) -> None:
        matching_poi = {
            "name": "青果巷",
            "type": "风景名胜;风景名胜",
            "pname": "江苏省",
            "cityname": "常州市",
            "adname": "天宁区",
            "adcode": "320402",
        }
        other_district_poi = {
            "name": "青果巷",
            "type": "风景名胜;风景名胜",
            "pname": "江苏省",
            "cityname": "常州市",
            "adname": "武进区",
            "adcode": "320412",
        }

        poi = amap.choose_attraction_poi(
            "青果巷",
            [other_district_poi, matching_poi],
            "天宁区",
        )

        self.assertEqual(matching_poi, poi)

    def test_search_requests_full_poi_fields_for_adcode_check(self) -> None:
        with patch.object(
            amap,
            "http_get_json",
            return_value={"status": "1", "pois": []},
        ) as http_get_json:
            amap.search_amap_pois("中山陵", "320400", "test-key", 5)

        query = parse_qs(urlparse(http_get_json.call_args.args[0]).query)
        self.assertEqual(["all"], query["extensions"])


if __name__ == "__main__":
    unittest.main()
