"""Full trip planning workflow from web research to routed itinerary."""

from __future__ import annotations

from typing import Any

from backend.app.planning.transit_routes import build_daily_transit_route_plan
from backend.app.providers.amap import require_amap_key
from backend.app.schemas.route_plan import TripRoutePlanResponse
from backend.app.schemas.trip_request import TripGenerateRouteRequest
from backend.app.services.candidate_enrichment import enrich_candidates_with_amap
from backend.app.services.travel_research import collect_research, extract_candidate_pool


def build_generated_route_plan(request: TripGenerateRouteRequest) -> TripRoutePlanResponse:
    """Generate a map-ready route plan starting with web research."""
    destination = request.destination.strip()
    preferences = [preference.strip() for preference in request.preferences if preference.strip()]
    research_bundle = collect_research(
        destination,
        request.days,
        preferences,
        max_results=request.max_search_results,
    )
    raw_candidates = extract_candidate_pool(
        research_bundle,
        destination,
        preferences,
        max_candidates=request.max_candidates,
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
    )
    route_plan.candidate_count = len(enriched_candidates)
    route_plan.research_summary = {
        "query_plan": research_bundle.query_plan,
        "search_result_count": len(research_bundle.search_results),
        "accepted_document_count": len(research_bundle.documents),
        "raw_candidate_count": len(raw_candidates),
        "enriched_candidate_count": len(enriched_candidates),
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
    """Merge user-requested spots into the ranked candidate pool."""
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

