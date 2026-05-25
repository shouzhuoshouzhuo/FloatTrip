"""旅行规划流程人类易读日志服务。

功能：
    为后端规划链路提供集中日志写入能力，把每次调用中的 LLM 候选景点池、
    地理聚类结果等关键中间数据记录到 backend/logs 目录，日志内容保持人类易读，
    便于本地调试和问题追溯。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR_ENV_KEY = "FLOATTRIP_BACKEND_LOG_DIR"
PLANNER_EVENTS_FILE = "planner_events.log"


def new_request_id() -> str:
    """功能：生成一次规划调用使用的请求追踪 ID。

    参数：
        无。
    返回值：
        返回去掉连字符的 UUID 字符串。
    """
    return uuid.uuid4().hex


def planner_log_dir() -> Path:
    """功能：获取后端规划日志目录。

    参数：
        无。
    返回值：
        优先返回 FLOATTRIP_BACKEND_LOG_DIR 指定目录，否则返回 backend/logs。
    """
    configured_dir = os.getenv(LOG_DIR_ENV_KEY, "").strip()
    return Path(configured_dir).expanduser() if configured_dir else DEFAULT_LOG_DIR


def planner_events_log_file() -> Path:
    """功能：获取规划事件日志文件路径。

    参数：
        无。
    返回值：
        返回 planner_events.log 的完整路径。
    """
    return planner_log_dir() / PLANNER_EVENTS_FILE


def log_planner_event(
    event_type: str,
    request_id: str,
    payload: dict[str, Any],
) -> None:
    """功能：把规划链路事件追加写入人类易读日志文件。

    参数：
        event_type：事件类型，例如 llm_candidate_pool 或 cluster_result。
        request_id：一次规划调用的请求追踪 ID。
        payload：需要记录的结构化事件内容。
    返回值：
        无返回值；日志写入失败时静默跳过，避免影响用户主流程。
    """
    try:
        log_file = planner_events_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as file:
            file.write(render_planner_event(event_type, request_id, payload))
    except OSError:
        return


def render_planner_event(
    event_type: str,
    request_id: str,
    payload: dict[str, Any],
) -> str:
    """功能：把规划事件渲染成人类易读文本。

    参数：
        event_type：事件类型，例如 llm_candidate_pool 或 cluster_result。
        request_id：一次规划调用的请求追踪 ID。
        payload：需要记录的结构化事件内容。
    返回值：
        返回可直接追加到日志文件的多行文本。
    """
    title = event_title(event_type)
    lines = [
        "",
        "=" * 88,
        f"时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"请求ID：{request_id}",
        f"事件：{title}",
        "-" * 88,
    ]
    if event_type in {
        "llm_raw_candidate_pool",
        "llm_candidate_pool",
        "amap_enriched_candidate_pool",
        "cluster_input_candidate_pool",
    }:
        lines.extend(render_candidate_pool(payload))
    elif event_type == "cluster_result":
        lines.extend(render_cluster_result(payload))
    else:
        lines.extend(render_generic_payload(payload))
    lines.append("=" * 88)
    return "\n".join(lines) + "\n"


def event_title(event_type: str) -> str:
    """功能：把事件类型转换成中文标题。

    参数：
        event_type：事件类型字符串。
    返回值：
        返回人类易读的中文事件标题。
    """
    titles = {
        "llm_raw_candidate_pool": "1/4 LLM/raw 候选池",
        "llm_candidate_pool": "1/4 LLM/raw 候选池",
        "amap_enriched_candidate_pool": "2/4 高德 enriched 候选池",
        "cluster_input_candidate_pool": "3/4 聚类输入候选池",
        "cluster_result": "4/4 聚类输出",
    }
    return titles.get(event_type, event_type)


def render_candidate_pool(payload: dict[str, Any]) -> list[str]:
    """功能：渲染候选景点池日志正文。

    参数：
        payload：包含目的地、天数、偏好、阶段说明和候选景点列表的日志数据。
    返回值：
        返回多行文本列表。
    """
    candidates = payload.get("candidates", [])
    lines = [
        f"目的地：{payload.get('destination') or '-'}",
        f"天数：{payload.get('days') or '-'}",
        f"偏好：{format_list(payload.get('preferences'))}",
        f"阶段：{payload.get('stage') or '-'}",
        f"警告：{format_list(payload.get('warnings'))}",
        f"搜索词：{format_list(payload.get('query_plan'))}",
        f"搜索结果数：{payload.get('search_result_count') if payload.get('search_result_count') is not None else '-'}",
        f"有效网页数：{payload.get('accepted_document_count') if payload.get('accepted_document_count') is not None else '-'}",
        f"候选数量：{len(candidates) if isinstance(candidates, list) else 0}",
        "候选列表：",
    ]
    if not isinstance(candidates, list) or not candidates:
        lines.append("  （空）")
        return lines

    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            lines.append(f"  {index}. {candidate}")
            continue
        lines.extend(render_candidate_lines(candidate, index, indent="  "))
    return lines


def render_cluster_result(payload: dict[str, Any]) -> list[str]:
    """功能：渲染地理聚类结果日志正文。

    参数：
        payload：包含目的地、天数、聚类参数和聚类结果的日志数据。
    返回值：
        返回多行文本列表。
    """
    clusters = payload.get("clusters", [])
    lines = [
        f"目的地：{payload.get('destination') or '-'}",
        f"天数：{payload.get('days') or '-'}",
        f"偏好：{format_list(payload.get('preferences'))}",
        f"最小簇大小：{payload.get('min_cluster_size') or '-'}",
        f"聚类数量：{len(clusters) if isinstance(clusters, list) else 0}",
        "聚类详情：",
    ]
    if not isinstance(clusters, list) or not clusters:
        lines.append("  （空）")
        return lines

    for cluster in clusters:
        if not isinstance(cluster, dict):
            lines.append(f"  - {cluster}")
            continue
        lines.append(
            f"  - 簇 {cluster.get('cluster_id')} | 半径 {cluster.get('radius_km')} km"
        )
        medoid = cluster.get("medoid")
        if isinstance(medoid, dict):
            lines.append(f"    中心点：{format_candidate_summary(medoid)}")
        candidates = cluster.get("candidates", [])
        lines.append("    景点：")
        if not isinstance(candidates, list) or not candidates:
            lines.append("      （空）")
            continue
        for index, candidate in enumerate(candidates, start=1):
            if isinstance(candidate, dict):
                lines.append(f"      {index}. {format_candidate_summary(candidate)}")
            else:
                lines.append(f"      {index}. {candidate}")
    return lines


def render_generic_payload(payload: dict[str, Any]) -> list[str]:
    """功能：渲染未知事件类型的通用日志正文。

    参数：
        payload：任意日志数据字典。
    返回值：
        返回键值形式的多行文本列表。
    """
    return [f"{key}：{value}" for key, value in payload.items()]


def render_candidate_lines(
    candidate: dict[str, Any],
    index: int,
    *,
    indent: str,
) -> list[str]:
    """功能：渲染单个候选景点的多行日志文本。

    参数：
        candidate：单个候选景点摘要字典。
        index：候选景点序号。
        indent：行首缩进字符串。
    返回值：
        返回单个候选景点的多行文本列表。
    """
    lines = [f"{indent}{index}. {format_candidate_summary(candidate)}"]
    sources = candidate.get("sources", [])
    if isinstance(sources, list) and sources:
        source_titles = [
            str(source.get("title") or source.get("url") or source)
            if isinstance(source, dict)
            else str(source)
            for source in sources[:3]
        ]
        lines.append(f"{indent}   来源：{format_list(source_titles)}")
    return lines


def format_candidate_summary(candidate: dict[str, Any]) -> str:
    """功能：把候选景点摘要压缩成单行可读文本。

    参数：
        candidate：单个候选景点摘要字典。
    返回值：
        返回包含名称、分数、提及网页数和 POI 坐标的单行文本。
    """
    parts = [
        str(candidate.get("name") or "-"),
        f"提及网页数={candidate.get('mention_count') if candidate.get('mention_count') is not None else '-'}",
        f"偏好分={candidate.get('preference_score') if candidate.get('preference_score') is not None else '-'}",
        f"总分={candidate.get('score') if candidate.get('score') is not None else '-'}",
    ]
    poi = candidate.get("poi")
    if isinstance(poi, dict):
        location = poi.get("location")
        location_text = ""
        if isinstance(location, dict):
            location_text = f" | 坐标=({location.get('lng')}, {location.get('lat')})"
        parts.append(
            f"POI={poi.get('name') or '-'} / {poi.get('district') or '-'}{location_text}"
        )
    return " | ".join(parts)


def format_list(value: Any) -> str:
    """功能：把列表值格式化为中文逗号分隔文本。

    参数：
        value：可能是列表、元组、集合或普通值的任意对象。
    返回值：
        返回人类易读的文本；空值返回“-”。
    """
    if isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value if str(item)]
        return "、".join(items) if items else "-"
    return str(value) if value else "-"


def compact_candidates_for_log(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """功能：压缩候选景点池日志字段，保留调试需要的核心信息。

    参数：
        candidates：候选景点字典列表。
    返回值：
        返回只包含名称、提及次数、偏好分、总分、来源和 POI 摘要的候选列表。
    """
    return [
        {
            "name": candidate.get("name"),
            "mention_count": candidate.get("mention_count"),
            "preference_score": candidate.get("preference_score"),
            "score": candidate.get("score"),
            "candidate_builder": candidate.get("candidate_builder"),
            "model": candidate.get("model"),
            "user_requested": candidate.get("user_requested"),
            "sources": candidate.get("sources", []),
            "poi": compact_poi_for_log(candidate.get("poi")),
        }
        for candidate in candidates
    ]


def compact_clusters_for_log(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """功能：压缩地理聚类结果日志字段，记录每天中心点、半径和候选景点。

    参数：
        clusters：cluster_candidates_by_days 返回的聚类结果。
    返回值：
        返回适合写入日志的聚类摘要列表。
    """
    return [
        {
            "cluster_id": cluster.get("cluster_id"),
            "radius_km": cluster.get("radius_km"),
            "medoid": compact_candidate_for_log(cluster.get("medoid")),
            "candidates": compact_candidates_for_log(
                list(cluster.get("candidates", []))
                if isinstance(cluster.get("candidates"), list)
                else []
            ),
        }
        for cluster in clusters
    ]


def compact_candidate_for_log(candidate: Any) -> dict[str, Any] | None:
    """功能：压缩单个候选景点日志字段。

    参数：
        candidate：可能是候选景点字典的任意值。
    返回值：
        候选合法时返回压缩字典，否则返回 None。
    """
    if not isinstance(candidate, dict):
        return None
    return compact_candidates_for_log([candidate])[0]


def compact_poi_for_log(poi: Any) -> dict[str, Any] | None:
    """功能：压缩高德 POI 日志字段。

    参数：
        poi：可能是高德 POI 字典的任意值。
    返回值：
        POI 合法时返回核心字段字典，否则返回 None。
    """
    if not isinstance(poi, dict):
        return None
    return {
        "id": poi.get("id"),
        "name": poi.get("name"),
        "type": poi.get("type"),
        "province": poi.get("province"),
        "city": poi.get("city"),
        "district": poi.get("district"),
        "address": poi.get("address"),
        "location": poi.get("location"),
    }
