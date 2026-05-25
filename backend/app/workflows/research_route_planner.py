"""从网页调研到前端路线结果的完整旅行规划工作流。"""

from __future__ import annotations

from typing import Any

from backend.app.planning.transit_routes import build_daily_transit_route_plan
from backend.app.providers.amap import require_amap_key
from backend.app.schemas.route_plan import TripRoutePlanResponse
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.services.candidate_enrichment import enrich_candidates_with_amap
from backend.app.services.planner_logging import (
    compact_candidates_for_log,
    log_planner_event,
    new_request_id,
)
from backend.app.services.travel_research import generate_hot_candidate_pool


def build_generated_route_plan(request: TripGenerateRouteRequest) -> TripRoutePlanResponse:
    """功能：串联网页调研、候选池、POI 补坐标和真实路线规划。

    参数：
        request：前端提交的完整规划请求。
    返回值：
        返回前端可直接渲染的每日路线规划响应。
    """
    request_id = new_request_id()
    destination = request.destination.strip()
    preferences = [preference.strip() for preference in request.preferences if preference.strip()]
    candidate_pool_result = generate_hot_candidate_pool(
        destination,
        request.days,
        preferences,
        max_search_results=request.max_search_results,
        max_candidates=request.max_candidates,
    )
    research_bundle = candidate_pool_result.research_bundle
    raw_candidates = candidate_pool_result.candidates
    log_planner_event(
        "llm_raw_candidate_pool",
        request_id,
        {
            "destination": destination,
            "days": request.days,
            "preferences": preferences,
            "max_candidates": request.max_candidates,
            "stage": "候选景点池 Agent 生成多 query 搜索计划后，从网页 markdown 中抽取并按提及频率/偏好分排序的热门候选池",
            "query_plan": research_bundle.query_plan,
            "search_result_count": len(research_bundle.search_results),
            "accepted_document_count": len(research_bundle.documents),
            "warnings": research_bundle.warnings,
            "candidates": compact_candidates_for_log(raw_candidates),
        },
    )
    if request.preferred_spots:
        raw_candidates = merge_preferred_spots(raw_candidates, request.preferred_spots)
    if request.avoided_spots:
        avoided = {name.strip() for name in request.avoided_spots if name.strip()}
        raw_candidates = [
            candidate
            for candidate in raw_candidates
            if str(candidate.get("name", "")).strip() not in avoided
        ]

    api_key = require_amap_key()
    enriched_candidates, poi_warnings = enrich_candidates_with_amap(
        raw_candidates,
        destination=destination,
        api_key=api_key,
        max_candidates=request.max_candidates,
    )
    log_planner_event(
        "amap_enriched_candidate_pool",
        request_id,
        {
            "destination": destination,
            "days": request.days,
            "preferences": preferences,
            "max_candidates": request.max_candidates,
            "stage": "高德 POI 搜索和坐标补全后的候选池",
            "warnings": poi_warnings,
            "candidates": compact_candidates_for_log(enriched_candidates),
        },
    )
    required_candidates = request.days * request.min_cluster_size
    if len(enriched_candidates) < required_candidates:
        raise ValueError(
            f"网页调研后只有 {len(enriched_candidates)} 个可用景点，"
            f"不足以生成 {request.days} 天路线（至少需要 {required_candidates} 个）"
        )

    route_plan = build_daily_transit_route_plan(
        enriched_candidates,
        destination,
        request.days,
        api_key=api_key,
        min_cluster_size=request.min_cluster_size,
        request_id=request_id,
        preferences=preferences,
    )
    route_plan.candidate_count = len(enriched_candidates)
    candidate_builder = next(
        (
            str(candidate.get("candidate_builder"))
            for candidate in raw_candidates
            if candidate.get("candidate_builder")
        ),
        "unknown",
    )
    candidate_model = next(
        (str(candidate.get("model")) for candidate in raw_candidates if candidate.get("model")),
        None,
    )
    route_plan.research_summary = {
        "query_plan": research_bundle.query_plan,
        "search_result_count": len(research_bundle.search_results),
        "accepted_document_count": len(research_bundle.documents),
        "markdown_document_count": len(research_bundle.documents),
        "raw_candidate_count": len(raw_candidates),
        "enriched_candidate_count": len(enriched_candidates),
        "candidate_builder": candidate_builder,
        "model": candidate_model,
        "request_id": request_id,
        "sources": [
            {
                "title": document.title,
                "url": document.url,
                "source": document.source,
            }
            for document in research_bundle.documents[:8]
        ],
    }
    route_plan.warnings = [
        *research_bundle.warnings,
        *poi_warnings,
        *route_plan.warnings,
    ]
    return route_plan


def merge_preferred_spots(
    candidates: list[dict[str, Any]],
    preferred_spots: list[str],
) -> list[dict[str, Any]]:
    """功能：把用户指定必去景点合并进候选池并提高排序优先级。

    参数：
        candidates：网页调研抽取出的候选景点列表。
        preferred_spots：用户输入的必去景点名称列表。
    返回值：
        返回合并、去重并按分数排序后的候选景点列表。
    """
    by_name = {str(candidate.get("name", "")).strip(): dict(candidate) for candidate in candidates}
    for spot in preferred_spots:
        name = spot.strip()
        if not name:
            continue
        existing = by_name.get(name, {"name": name, "sources": []})
        existing["mention_count"] = max(int(existing.get("mention_count") or 0), 1)
        existing["preference_score"] = max(int(existing.get("preference_score") or 0), 10)
        existing["score"] = max(float(existing.get("score") or 0), 999)
        existing["user_requested"] = True
        by_name[name] = existing
    return sorted(
        by_name.values(),
        key=lambda candidate: (
            -float(candidate.get("score") or 0),
            -int(candidate.get("mention_count") or 0),
            str(candidate.get("name", "")),
        ),
    )
