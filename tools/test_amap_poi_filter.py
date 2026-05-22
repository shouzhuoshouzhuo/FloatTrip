import sys
import unittest
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import amap_poi_filter


class AmapPoiFilterTests(unittest.TestCase):
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

        poi = amap_poi_filter.choose_attraction_poi(
            "青果巷",
            [other_district_poi, matching_poi],
            "天宁区",
        )

        self.assertEqual(matching_poi, poi)

    def test_city_adcode_accepts_poi_in_its_district(self) -> None:
        self.assertTrue(amap_poi_filter.adcode_matches_region("320402", "320400"))
        self.assertFalse(amap_poi_filter.adcode_matches_region("320402", "320500"))

    def test_filter_passes_admin_region_to_search_and_keeps_matching_poi(self) -> None:
        payload = {
            "candidate_pool": [
                {
                    "name": "青果巷",
                    "mention_count": 1,
                    "preference_score": 8,
                }
            ]
        }
        poi = {
            "id": "poi-1",
            "name": "青果巷",
            "type": "风景名胜;风景名胜",
            "location": "119.973,31.779",
            "pname": "江苏省",
            "cityname": "常州市",
            "adname": "天宁区",
            "adcode": "320402",
        }

        with (
            patch.object(amap_poi_filter, "search_amap_pois", return_value=[poi]) as search,
            patch.object(amap_poi_filter.time, "sleep"),
        ):
            output = amap_poi_filter.filter_candidate_pool(
                payload,
                "天宁区",
                "test-key",
                offset=5,
                min_mentions=1,
            )

        search.assert_called_once_with("青果巷", "天宁区", "test-key", 5)
        self.assertEqual(["青果巷"], amap_poi_filter.extract_candidate_names(output))
        self.assertEqual("320402", output["candidate_pool"][0]["poi"]["adcode"])
        self.assertEqual("天宁区", output["filter"]["admin_region"])

    def test_search_requests_full_poi_fields_for_adcode_check(self) -> None:
        with patch.object(
            amap_poi_filter,
            "http_get_json",
            return_value={"status": "1", "pois": []},
        ) as http_get_json:
            amap_poi_filter.search_amap_pois("中山陵", "320400", "test-key", 5)

        query = parse_qs(urlparse(http_get_json.call_args.args[0]).query)
        self.assertEqual(["all"], query["extensions"])


if __name__ == "__main__":
    unittest.main()
