import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_geo_day_clusters_map as renderer


def candidate(name: str, lng: float, lat: float, score: int) -> dict:
    return {
        "name": name,
        "mention_count": score,
        "score": score,
        "poi": {
            "id": f"poi-{name}",
            "type": "风景名胜;风景名胜",
            "province": "江苏省",
            "city": "常州市",
            "district": "天宁区",
            "address": f"{name}路 1 号",
            "location": {"lng": lng, "lat": lat},
        },
    }


class RenderGeoDayClustersMapTests(unittest.TestCase):
    def test_html_contains_cluster_markers_excluded_markers_and_poi_popup_fields(self) -> None:
        pool = [
            candidate("高分甲", 119.970, 31.780, 10),
            candidate("高分乙", 119.971, 31.780, 9),
            candidate("高分丙", 119.972, 31.780, 8),
            candidate("高分丁", 119.973, 31.780, 7),
            candidate("灰点", 119.974, 31.780, 1),
        ]

        html = renderer.build_map_html(pool, 1)

        self.assertIn("leaflet@1.9.4", html)
        self.assertIn('const markers = ', html)
        self.assertIn('"medoid": true', html)
        self.assertIn('"excluded": true', html)
        self.assertIn(renderer.EXCLUDED_COLOR, html)
        self.assertIn("灰点", html)
        self.assertIn("poi_id", html)
        self.assertIn("风景名胜", html)
        self.assertIn("天宁区", html)
        self.assertIn("address", html)

    def test_render_map_file_reads_amap_payload_and_writes_html(self) -> None:
        payload = {
            "candidate_pool": [
                candidate("甲", 119.970, 31.780, 4),
                candidate("乙", 119.971, 31.780, 3),
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "candidates.json"
            output_path = Path(temp_dir) / "clusters.html"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            renderer.render_map_file(input_path, output_path, 1)

            rendered = output_path.read_text(encoding="utf-8")
        self.assertIn("FloatTrip Geo Day Clusters", rendered)
        self.assertIn("甲", rendered)

    def test_main_reports_missing_input_file(self) -> None:
        stderr = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "render_geo_day_clusters_map.py",
                    "/missing/amap-candidates.json",
                    "--days",
                    "1",
                    "--output",
                    "/tmp/clusters.html",
                ],
            ),
            contextlib.redirect_stderr(stderr),
        ):
            return_code = renderer.main()

        self.assertEqual(1, return_code)
        self.assertIn("地图渲染失败", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
