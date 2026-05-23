#!/usr/bin/env python3
"""Render weighted geographic day clusters as a Leaflet debug map."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

from geo_day_cluster import (
    candidate_location,
    cluster_candidates_by_days,
    prepare_candidates_for_clustering,
)


CLUSTER_COLORS = (
    "#147bd1",
    "#e14d2a",
    "#0f9b72",
    "#a63fd4",
    "#d28a00",
    "#c42f70",
    "#007b83",
    "#5964d8",
)
EXCLUDED_COLOR = "#8a95a5"


def load_candidate_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("candidate JSON must be an object")
    if not isinstance(payload.get("candidate_pool"), list):
        raise RuntimeError("candidate JSON must contain candidate_pool")
    return payload


def build_map_html(
    candidates: list[dict[str, Any]],
    days: int,
    *,
    min_cluster_size: int = 2,
    max_iterations: int = 50,
) -> str:
    selected = prepare_candidates_for_clustering(
        candidates,
        days,
        min_cluster_size=min_cluster_size,
    )
    clusters = cluster_candidates_by_days(
        candidates,
        days,
        min_cluster_size=min_cluster_size,
        max_iterations=max_iterations,
    )
    selected_ids = {id(candidate) for candidate in selected}
    excluded = [candidate for candidate in candidates if id(candidate) not in selected_ids]
    marker_data = build_marker_data(clusters, excluded)
    escaped_markers = json.dumps(marker_data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>FloatTrip Geo Day Clusters</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
    <style>
      html, body, #map {{ height: 100%; margin: 0; }}
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .cluster-popup dl {{ margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 8px; }}
      .cluster-popup dt {{ color: #52606d; }}
      .cluster-popup dd {{ margin: 0; max-width: 320px; overflow-wrap: anywhere; }}
    </style>
  </head>
  <body>
    <div id="map" aria-label="FloatTrip geographic day cluster debug map"></div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
      const markers = {escaped_markers};
      const map = L.map("map");
      L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
        attribution: '&copy; OpenStreetMap contributors'
      }}).addTo(map);
      const bounds = [];
      markers.forEach((marker) => {{
        bounds.push([marker.lat, marker.lng]);
        const point = L.circleMarker([marker.lat, marker.lng], {{
          color: marker.color,
          fillColor: marker.color,
          fillOpacity: marker.excluded ? 0.32 : 0.82,
          opacity: marker.excluded ? 0.55 : 1,
          radius: marker.medoid ? 11 : 7,
          weight: marker.medoid ? 4 : 2
        }}).addTo(map);
        point.bindPopup(marker.popup, {{ className: "cluster-popup" }});
      }});
      if (bounds.length === 1) {{
        map.setView(bounds[0], 13);
      }} else {{
        map.fitBounds(bounds, {{ padding: [36, 36] }});
      }}
    </script>
  </body>
</html>
"""


def build_marker_data(
    clusters: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    markers = []
    for cluster in clusters:
        cluster_id = int(cluster["cluster_id"])
        medoid = cluster["medoid"]
        medoid_id = id(medoid)
        color = CLUSTER_COLORS[cluster_id % len(CLUSTER_COLORS)]
        for candidate in cluster["candidates"]:
            lng, lat = candidate_location(candidate)
            is_medoid = id(candidate) == medoid_id
            markers.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "color": color,
                    "cluster_id": cluster_id,
                    "medoid": is_medoid,
                    "excluded": False,
                    "popup": candidate_popup(candidate, cluster_id=cluster_id, medoid=is_medoid),
                }
            )
    for candidate in excluded:
        lng, lat = candidate_location(candidate)
        markers.append(
            {
                "lat": lat,
                "lng": lng,
                "color": EXCLUDED_COLOR,
                "cluster_id": None,
                "medoid": False,
                "excluded": True,
                "popup": candidate_popup(candidate, cluster_id=None, medoid=False),
            }
        )
    return markers


def candidate_popup(
    candidate: dict[str, Any],
    *,
    cluster_id: int | None,
    medoid: bool,
) -> str:
    poi = candidate.get("poi") if isinstance(candidate.get("poi"), dict) else {}
    lng, lat = candidate_location(candidate)
    rows = (
        ("景点", candidate.get("name", "")),
        ("cluster", "excluded" if cluster_id is None else cluster_id),
        ("medoid", medoid),
        ("mention_count", candidate.get("mention_count", "")),
        ("score", candidate.get("score", "")),
        ("lng", lng),
        ("lat", lat),
        ("poi_id", poi.get("id", "")),
        ("type", poi.get("type", "")),
        ("province", poi.get("province", "")),
        ("city", poi.get("city", "")),
        ("district", poi.get("district", "")),
        ("address", poi.get("address", "")),
    )
    definition_list = "".join(
        f"<dt>{html.escape(str(label))}</dt><dd>{html.escape(str(value))}</dd>"
        for label, value in rows
    )
    return f"<dl>{definition_list}</dl>"


def render_map_file(
    input_json: Path,
    output_html: Path,
    days: int,
    *,
    min_cluster_size: int = 2,
    max_iterations: int = 50,
) -> None:
    payload = load_candidate_payload(input_json)
    output_html.write_text(
        build_map_html(
            payload["candidate_pool"],
            days,
            min_cluster_size=min_cluster_size,
            max_iterations=max_iterations,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="渲染 FloatTrip 地理区域聚类 Leaflet 调试地图。")
    parser.add_argument("input_json", type=Path, help="amap_poi_filter.py 输出的 JSON 文件")
    parser.add_argument("--days", type=int, required=True, help="旅行天数，也是区域聚类簇数")
    parser.add_argument("--output", type=Path, required=True, help="输出 HTML 文件路径")
    parser.add_argument("--min-cluster-size", type=int, default=2, help="每簇最少候选数，默认 2")
    parser.add_argument("--max-iterations", type=int, default=50, help="K-Medoids 最大迭代轮数，默认 50")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        render_map_file(
            args.input_json,
            args.output,
            args.days,
            min_cluster_size=args.min_cluster_size,
            max_iterations=args.max_iterations,
        )
    except Exception as exc:
        print(f"地理区域聚类地图渲染失败：{exc}", file=sys.stderr)
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
