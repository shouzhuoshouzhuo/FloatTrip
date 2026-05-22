#!/usr/bin/env python3
"""
Shared SearchCorpus schema helpers for FloatTrip tools.

Search providers should normalize their raw results into this shape before any
LLM or rule-based candidate extraction runs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SEARCH_CORPUS_SCHEMA_VERSION = "search_corpus.v1"


@dataclass(frozen=True)
class SearchDocument:
    document_id: str
    provider: str
    query: str
    title: str
    url: str
    site_name: str = ""
    published_at: str = ""
    content: str = ""
    snippet: str = ""
    rank: int = 0
    scores: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchCorpus:
    destination: str
    days: int
    preferences: list[str]
    queries: list[str]
    providers: list[str]
    documents: list[SearchDocument]
    raw_responses: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SEARCH_CORPUS_SCHEMA_VERSION


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_url(url: str) -> str:
    return url.split("#", 1)[0].strip()


def search_corpus_to_dict(corpus: SearchCorpus) -> dict[str, Any]:
    return asdict(corpus)


def write_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def load_search_corpus(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("SearchCorpus 文件必须是 JSON object")
    if payload.get("schema_version") != SEARCH_CORPUS_SCHEMA_VERSION:
        raise RuntimeError(f"SearchCorpus schema_version 必须是 {SEARCH_CORPUS_SCHEMA_VERSION}")
    if not isinstance(payload.get("documents"), list):
        raise RuntimeError("SearchCorpus 文件缺少 documents 数组")
    return payload


def dedupe_documents(documents: list[SearchDocument]) -> list[SearchDocument]:
    seen_urls: set[str] = set()
    deduped: list[SearchDocument] = []
    for document in documents:
        normalized_url = normalize_url(document.url)
        if not normalized_url or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduped.append(document)
    return deduped
