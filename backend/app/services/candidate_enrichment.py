"""候选景点高德 POI 补全服务。

功能：
    将网页调研和模型抽取得到的候选景点名称，补齐高德地点 ID、类型、行政区、
    地址和经纬度，生成后续地理聚类与交通路线规划可直接使用的候选结构。
"""

from __future__ import annotations

import re
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
    """功能：为排序后的候选景点补齐高德 POI 数据。

    参数：
        candidates：网页调研和模型抽取得到的候选景点字典列表。
        destination：目的地城市或行政区，用于限制高德地点搜索范围。
        api_key：高德 Web 服务 Key。
        max_candidates：最多返回的已补全候选景点数量。
        search_offset：每个关键词从高德读取的 POI 候选数量。
    返回值：
        返回二元组：已补齐 poi 字段的候选景点列表、POI 搜索或匹配警告列表。
    """
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
        except Exception as exc:
            warnings.append(f"{name} 高德 POI 搜索失败：{exc}")
            continue
        poi = choose_destination_poi(name, pois, destination)
        if not poi:
            warnings.append(f"{name} 未匹配到目的地行政区内的高德 POI")
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


def choose_destination_poi(
    candidate_name: str,
    pois: list[dict[str, Any]],
    destination: str,
) -> dict[str, Any] | None:
    """功能：从高德搜索结果中选择行政区匹配的 POI。

    参数：
        candidate_name：LLM 抽取出的候选景点名称。
        pois：高德地点搜索返回的原始 POI 列表。
        destination：用户指定目的地城市或行政区。
    返回值：
        返回第一个符合目的地行政区的 POI；没有则返回 None。
    """
    del candidate_name
    for poi in pois:
        if not isinstance(poi, dict):
            continue
        normalized_poi = amap.normalize_poi(poi)
        if not poi_in_destination(normalized_poi, destination):
            continue
        return poi
    return None


def poi_in_destination(poi: dict[str, Any], destination: str) -> bool:
    """功能：判断 POI 行政区字段是否属于用户指定目的地。

    参数：
        poi：已归一化的高德 POI 字典。
        destination：用户指定目的地城市、区县名或 adcode。
    返回值：
        POI 的省、市、区或 adcode 与目的地匹配时返回 True。
    """
    normalized_destination = normalize_admin_text(destination)
    if not normalized_destination:
        return True

    adcode = str(poi.get("adcode") or "").strip()
    if normalized_destination.isdigit():
        return adcode.startswith(normalized_destination[:4])

    admin_values = (
        normalize_admin_text(str(poi.get("province") or "")),
        normalize_admin_text(str(poi.get("city") or "")),
        normalize_admin_text(str(poi.get("district") or "")),
    )
    return any(
        value == normalized_destination
        or value.startswith(normalized_destination)
        or normalized_destination.startswith(value)
        for value in admin_values
        if value
    )


def normalize_admin_text(value: str) -> str:
    """功能：归一化行政区文本，便于城市名和高德 cityname 对齐。

    参数：
        value：目的地或 POI 行政区字段。
    返回值：
        返回去空白和常见行政区后缀后的文本。
    """
    text = re.sub(r"\s+", "", value)
    for suffix in ("特别行政区", "自治州", "地区", "盟", "市", "省", "区", "县"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text
