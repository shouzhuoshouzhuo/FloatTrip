"""Convert researched attraction names into map-ready POI candidates."""

from __future__ import annotations

from typing import Any

from backend.app.providers import amap


def enrich_candidates_with_amap(
    candidates: list[dict[str, Any]],
    *,
    destination: str,
    api_key: str,
    max_candidates: int = 24,
    search_offset: int = 8,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Attach AMap POI data to ranked attraction candidates."""
    enriched_candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_poi_ids: set[str] = set()
    seen_names: set[str] = set()

    for candidate in candidates:
        name = str(candidate.get("name", "")).strip()
        if not name:
            continue
        try:
            pois = amap.search_amap_pois(name, destination, api_key, search_offset)
            poi = amap.choose_attraction_poi(name, pois, destination)
        except Exception as exc:
            warnings.append(f"{name} 高德 POI 搜索失败：{exc}")
            continue
        if not poi:
            warnings.append(f"{name} 未匹配到目的地内的景点 POI")
            continue

        normalized_poi = amap.normalize_poi(poi)
        location = normalized_poi.get("location")
        if not isinstance(location, dict):
            warnings.append(f"{name} 高德 POI 缺少坐标")
            continue

        poi_id = str(normalized_poi.get("id") or "")
        dedupe_key = poi_id or str(normalized_poi.get("name") or name)
        if dedupe_key in seen_poi_ids or name in seen_names:
            continue
        seen_poi_ids.add(dedupe_key)
        seen_names.add(name)

        enriched = dict(candidate)
        enriched["poi"] = normalized_poi
        enriched_candidates.append(enriched)
        if len(enriched_candidates) >= max_candidates:
            break

    return enriched_candidates, warnings

