#!/usr/bin/env python3
"""Build a markdown travel-guide attraction pool with LangGraph."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field


LOCAL_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.local"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/beta"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_CANDIDATES = 40
DEFAULT_MAX_MARKDOWN_CHARS = 60_000
HTTP_PROXY_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


class AttractionCandidate(BaseModel):
    name: str = Field(description="合并别名后的标准景点中文名")
    preference_score: int = Field(
        ge=0,
        le=10,
        description="该景点与用户偏好的符合分，0 表示不符合，10 表示非常符合",
    )


class RankedAttractionCandidate(AttractionCandidate):
    mention_count: int = Field(
        ge=1,
        description="该景点名称在输入 markdown 攻略中由代码统计出的出现频率",
    )


class CandidatePool(BaseModel):
    candidate_pool: list[AttractionCandidate] = Field(
        description="从 markdown 攻略中识别出的候选景点池"
    )


class RankedCandidatePool(BaseModel):
    candidate_pool: list[RankedAttractionCandidate] = Field(
        description="按代码统计的 markdown 景点提及频率降序排列的候选景点池"
    )


class CandidatePoolState(TypedDict, total=False):
    markdown_guides: str
    preferences: list[str]
    max_candidates: int
    candidate_pool: CandidatePool
    ranked_candidate_pool: RankedCandidatePool


def load_local_env() -> None:
    """Load project-local environment variables without overriding the shell."""
    if not LOCAL_ENV_FILE.exists():
        return

    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_deepseek_model(model: str) -> str:
    legacy_aliases = {
        "deepseekv4flash": "deepseek-v4-flash",
        "deepseekv4pro": "deepseek-v4-pro",
    }
    return legacy_aliases.get(model.strip(), model.strip())


def parse_preferences(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


def build_prompt(markdown_guides: str, preferences: list[str], max_candidates: int) -> str:
    preference_text = "、".join(preferences) if preferences else "无明确偏好"
    return f"""
请从 FloatTrip 的 markdown 旅行攻略中抽取候选景点池。

用户偏好：{preference_text}
最多输出：{max_candidates} 个景点

抽取要求：
- 只输出真实可游玩的景点、景区、博物馆、公园、历史街区、古镇、寺庙、主题乐园、自然风景区。
- 不输出酒店、餐厅、美食菜名、商场、交通站点、行政区地址、攻略标题词、路线词、开放时间、预约和门票信息。
- 同一景点的简称、别名和全称只保留一个名称。
- name 必须选择 markdown 攻略中出现过的那个景点名称，后续程序会按 name 原文统计出现频率。
- 不要统计景点出现次数，程序会在结构化抽取后统计。
- preference_score 只衡量景点和用户偏好的符合程度，使用 0 到 10 的整数。
- 文本没有足够证据时不要猜测景点；没有可靠候选时返回空数组。

markdown 攻略：
{markdown_guides}
""".strip()


def build_structured_deepseek(model: str):
    """Create DeepSeek chat model with LangChain structured output."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY。请在环境变量或 .env.local 中配置后重试。")

    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少 httpx 或 langchain-openai。请先安装后再运行该 LangGraph 工具。"
        ) from exc

    proxy = choose_http_proxy()
    http_client = httpx.Client(proxy=proxy, trust_env=False)
    http_async_client = httpx.AsyncClient(proxy=proxy, trust_env=False)
    llm = ChatOpenAI(
        model=normalize_deepseek_model(model),
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        http_client=http_client,
        http_async_client=http_async_client,
        http_socket_options=(),
        extra_body={"thinking": {"type": "disabled"}},
    )
    return llm.with_structured_output(
        CandidatePool,
        method="function_calling",
        strict=True,
    )


def choose_http_proxy() -> str | None:
    """Prefer HTTP proxy variables so httpx does not require SOCKS support."""
    for key in HTTP_PROXY_ENV_KEYS:
        proxy = os.getenv(key, "").strip()
        if proxy.startswith(("http://", "https://")):
            return proxy
    return None


def extract_candidates_node(structured_llm):
    def extract_candidates(state: CandidatePoolState) -> CandidatePoolState:
        pool = structured_llm.invoke(
            [
                (
                    "system",
                    "你是 FloatTrip 的旅行景点候选池抽取器。必须按结构化输出 schema 返回结果。",
                ),
                (
                    "human",
                    build_prompt(
                        state["markdown_guides"],
                        state.get("preferences", []),
                        state.get("max_candidates", DEFAULT_MAX_CANDIDATES),
                    ),
                ),
            ]
        )
        return {"candidate_pool": pool}

    return extract_candidates


def count_name_mentions(markdown_guides: str, name: str) -> int:
    """Count literal attraction-name mentions in markdown guide text."""
    return markdown_guides.count(name.strip()) if name.strip() else 0


def rank_candidate_pool(
    pool: CandidatePool,
    markdown_guides: str,
    max_candidates: int,
) -> RankedCandidatePool:
    counted_by_name: dict[str, RankedAttractionCandidate] = {}
    for candidate in pool.candidate_pool:
        name = candidate.name.strip()
        mention_count = count_name_mentions(markdown_guides, name)
        if not name or mention_count < 1:
            continue
        previous = counted_by_name.get(name)
        preference_score = max(
            candidate.preference_score,
            previous.preference_score if previous else 0,
        )
        counted_by_name[name] = RankedAttractionCandidate(
            name=name,
            preference_score=preference_score,
            mention_count=mention_count,
        )
    sorted_candidates = sorted(
        counted_by_name.values(),
        key=lambda candidate: (
            -candidate.mention_count,
            -candidate.preference_score,
            candidate.name,
        ),
    )
    return RankedCandidatePool(candidate_pool=sorted_candidates[:max_candidates])


def sort_candidates_node(state: CandidatePoolState) -> CandidatePoolState:
    return {
        "ranked_candidate_pool": rank_candidate_pool(
            state["candidate_pool"],
            state["markdown_guides"],
            state.get("max_candidates", DEFAULT_MAX_CANDIDATES),
        )
    }


def build_graph(structured_llm):
    graph_builder = StateGraph(CandidatePoolState)
    graph_builder.add_node("extract_candidates", extract_candidates_node(structured_llm))
    graph_builder.add_node("sort_candidates", sort_candidates_node)
    graph_builder.add_edge(START, "extract_candidates")
    graph_builder.add_edge("extract_candidates", "sort_candidates")
    graph_builder.add_edge("sort_candidates", END)
    return graph_builder.compile()


def build_output(
    markdown_file: Path,
    preferences: list[str],
    model: str,
    pool: RankedCandidatePool,
) -> dict[str, object]:
    return {
        "schema_version": "markdown_candidate_pool.v1",
        "provider": "langgraph_markdown_candidate_pool",
        "candidate_builder": "deepseek_structured_output",
        "model": normalize_deepseek_model(model),
        "source_markdown": str(markdown_file),
        "preferences": preferences,
        "candidate_pool": [
            candidate.model_dump() for candidate in pool.candidate_pool
        ],
    }


def read_markdown(markdown_file: Path, max_chars: int) -> str:
    markdown = markdown_file.read_text(encoding="utf-8").strip()
    if not markdown:
        raise RuntimeError(f"markdown 攻略为空：{markdown_file}")
    return markdown[:max_chars]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用 LangGraph + DeepSeek 结构化输出 markdown 攻略候选景点池。"
    )
    parser.add_argument("markdown_file", type=Path, help="包含旅行攻略的 markdown 文件")
    parser.add_argument("--preferences", default="", help="用户偏好，逗号分隔")
    parser.add_argument(
        "--model",
        default=os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        help=f"DeepSeek 模型，默认 {DEFAULT_DEEPSEEK_MODEL}",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help=f"最多保留多少候选景点，默认 {DEFAULT_MAX_CANDIDATES}",
    )
    parser.add_argument(
        "--max-markdown-chars",
        type=int,
        default=DEFAULT_MAX_MARKDOWN_CHARS,
        help=f"最多送入 LLM 的 markdown 字符数，默认 {DEFAULT_MAX_MARKDOWN_CHARS}",
    )
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()

    try:
        if args.max_candidates < 1:
            raise RuntimeError("--max-candidates 必须大于 0")
        markdown_guides = read_markdown(args.markdown_file, args.max_markdown_chars)
        preferences = parse_preferences(args.preferences)
        graph = build_graph(build_structured_deepseek(args.model))
        result = graph.invoke(
            {
                "markdown_guides": markdown_guides,
                "preferences": preferences,
                "max_candidates": args.max_candidates,
            }
        )
        output = build_output(
            args.markdown_file,
            preferences,
            args.model,
            result["ranked_candidate_pool"],
        )
    except Exception as exc:
        print(f"LangGraph markdown 候选池生成失败：{exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
