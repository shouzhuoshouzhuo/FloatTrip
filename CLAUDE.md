# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Chinese-language AI travel-planning assistant ("AI 旅游规划助手"). A FastAPI backend runs a **LangGraph multi-agent pipeline** that turns a one-sentence trip request into a day-by-day itinerary with timed attractions and lunch/dinner picks, using **DeepSeek** for the LLM agents and **AMap (高德)** REST APIs as the real-world POI data source. A static vanilla-JS frontend renders the plan. All prompts, comments, and user-facing text are in Chinese.

## Commands

```bash
pip install -r requirements.txt        # install deps
python run.py                          # serve at http://localhost:8765 (frontend + API)
```

There is **no test suite, linter, or build step**. The `frontend/` files are served statically by the backend — no separate frontend build.

Secrets live in `.env.local` (gitignored; see `.env.example`). Required: `AMAP_API_KEY`, `DEEPSEEK_API_KEY`. Optional: `DEEPSEEK_MODEL` (default `deepseek-v4-flash`), `HTTPS_PROXY`. Env loading is centralized in `app/core/env.py::load_local_env` — it only fills *missing* keys and never overrides the real environment. Do not add `python-dotenv` or scatter env reads; go through that one function.

## Architecture

### Request flow
`POST /api/plan` (`app/main.py`) → `app/planning/graph.py::run` builds and invokes the compiled LangGraph → returns `{success, missing_fields, history, plan}`. The route is sync; FastAPI runs it in a threadpool. Static frontend is mounted at `/` **after** the API routes (order matters in `main.py`).

### The LangGraph pipeline (`app/planning/`)
Single source of state is `TravelPlanState` (`schemas.py`) — a Pydantic model threaded through every node. Nodes return **partial dicts** that LangGraph merges into state; `history` is append-only and is built with `state.history + [note]` in each node (narration shown to the user).

Graph wiring (`graph.py::build_graph`):

```
START → intent ─(missing fields?)→ END                 # short-circuit, asks user to clarify
              └→ attraction_search → planner → reviewer
                                       ↑          │
                                       └──────────┘       # loop until approved OR max_review_rounds
                                                  └→ meal_search → meal_recommend → finalize → END
```

- **intent** — DeepSeek extracts destination/dates/preferences. Relative dates ("明天/下周末") are resolved against `date.today()` injected into the prompt. Missing destination/dates populate `missing_fields`, which routes straight to `END` (no plan produced).
- **attraction_search** — AMap keyword search builds the candidate spot pool, filtered by `min_rating`. **This pool is the closed world**: every later agent may only choose names that appear in it.
- **planner ⇄ reviewer loop** — Planner drafts a timed per-day route from the pool; Reviewer approves or returns `route_modify_opinion` for another round. Reviewer decisions are grounded in **deterministic pre-checks** computed in Python (`helpers.py`: `day_proximity_report`, `open_time_violations`, `unknown_spots`) and fed to the LLM as objective facts — the LLM judges, the code supplies the evidence. Any spot outside the candidate pool (`unknown_spots`) is a hard reject regardless of the LLM's vote. The loop is bounded by `max_review_rounds`; `graph.py` sets `recursion_limit = 2*max_review_rounds + 10` to match.
- **meal_search → meal_recommend** — For each day, AMap *around*-search finds restaurants near anchor spots (lunch = last morning spot, dinner = first evening / last afternoon spot, per `helpers.py`). LLM picks one per meal from those candidates; a **deterministic fallback** in `nodes.py` swaps the dinner pick if it duplicates lunch.
- **finalize** — Assembles `final_plan`: interleaves lunch/dinner into each day's timeline, attaches photos/ratings/open-times, and computes haversine distances between adjacent stops.

### Provider & core layers
- `app/providers/amap/` — AMap REST client. `poi.py` does text search, around search, and POI→dict normalization; all AMap calls retry on rate-limit `info` codes (`client.py::AMAP_RATE_LIMIT_INFOS`).
- `app/core/http.py` — shared `http_get_json` (stdlib urllib, retry/backoff) and `redact_url` (strips `key`/`token` before any URL is logged or raised in an error). DeepSeek calls instead go through httpx in `app/llm/deepseek.py`.
- `app/llm/deepseek.py` — DeepSeek client factory via `langchain_openai.ChatOpenAI` pointed at `https://api.deepseek.com`. `build_structured_deepseek(schema)` binds a Pydantic schema with `method="function_calling", strict=True` and disables thinking mode.

## Conventions & gotchas

- **Structured LLM output**: every agent uses a Pydantic schema from `schemas.py` bound via `build_structured_deepseek`. Always invoke through `helpers.py::invoke_structured`, never `llm.invoke` directly — DeepSeek's function-calling occasionally returns `None`, and the helper retries then raises a clear error instead of an `AttributeError`.
- **Spot identity is by name, not object identity.** State is serialized/deserialized across LangGraph steps, so two "same" spot dicts won't be `is`-equal. Match on `name` (see the comment in `finalize_node`). When adding spot-matching logic, compare names.
- **The candidate pool is authoritative.** Planner/Reviewer/Meal agents must only reference names present in `state.pois` (attractions) or the day's restaurant candidates. Prompts enforce this and `unknown_spots` verifies it — keep both in sync if you change schemas.
- Prompts are centralized in `app/planning/prompts.py`. The agent *behavior* lives there as much as in the node code; tune both together.
- Tuning knobs come from the `PlanRequest` body and flow as `**overrides` into `TravelPlanState`: `max_per_day`, `min_rating`, `max_spots`, `max_review_rounds`, and `model_name`.
- Models are factory-built per node via `make_*_node(model_name)` closures so each agent gets its own temperature (intent/reviewer/meal `0`, planner `0.3`).
