## 1. Persistence Foundation

- [x] 1.1 Add SQLite migrations for `conversations`, `messages`, `planning_briefs`, `runs`, and `run_events`, including ownership, status, kind, sequence, retry/result linkage, and timestamps
- [x] 1.2 Enable and verify SQLite WAL mode and the indexes required for conversation ordering, queued-run selection, active-run lookup, and run-event replay
- [x] 1.3 Implement repositories for conversations and ordered messages with owner isolation and cursor-based history reads
- [x] 1.4 Implement the PlanningBrief repository with collecting/ready/submitted/discarded transitions and immutable submission snapshots
- [x] 1.5 Implement Run and RunEvent repositories with atomic status transitions, run-local event sequence assignment, and `after_seq` queries
- [x] 1.6 Add repository tests covering ownership, sequence monotonicity, immutable snapshots, concurrent event writes, and rollback on failed transactions

## 2. Agent Runtime Core

- [x] 2.1 Define validated Run kinds, statuses, transition rules, disconnect policies, public error payloads, and custom-event schemas
- [x] 2.2 Implement RunManager creation, lookup, status transition, result association, idempotent cancellation, retry linkage, and startup reconciliation
- [x] 2.3 Implement an in-process StreamBridge with per-run subscription, heartbeat, end signaling, bounded retention, and cursor-aware deduplication
- [x] 2.4 Implement durable-first event publication so selected events are committed before live subscribers are notified
- [x] 2.5 Implement the asynchronous scheduler with deterministic queue ordering and separate Chat, formal-planning, LLM, and AMap capacity controls
- [x] 2.6 Implement concurrency keys for ordered Chat turns, independent formal plans, and serialized revisions of the same itinerary
- [x] 2.7 Add runtime tests for lifecycle transitions, cancellation races, capacity release, queued admission, Chat isolation from planning capacity, and orphan reconciliation

## 3. LangGraph Native Streaming

- [x] 3.1 Add a reusable Runtime worker that executes compiled graphs through `astream(..., version="v2")` and consumes `messages`, `custom`, and internal `updates`
- [x] 3.2 Add allowlist filtering so only the tagged or named Chat response node can publish user-visible message deltas
- [x] 3.3 Add validated LangGraph custom stream payloads for planning brief updates, planning progress, waiting-user prompts, and itinerary completion
- [x] 3.4 Add runtime handling for LangGraph interrupts and final updates without forwarding raw updates, values, tasks, checkpoints, debug data, or internal model output
- [x] 3.5 Add stream-confidentiality tests that reject chain-of-thought, prompts, raw provider data, profile internals, stack traces, and full graph state
- [x] 3.6 Add replay-to-live handoff tests covering reconnect during execution, reconnect after completion, duplicate cursors, and terminal end delivery

## 4. Existing Planning Graph Integration

- [x] 4.1 Create a PlanningWorker adapter that converts an immutable travel-plan Run snapshot into the existing `TravelPlanState`
- [x] 4.2 Replace product progress derived from `astream_events()` with stable LangGraph custom progress events while keeping internal graph node names private
- [x] 4.3 Move itinerary persistence out of the SSE request closure into runtime finalization and associate the committed itinerary with the successful Run
- [x] 4.4 Trigger profile updating only after itinerary commit and ensure profile failures do not change the successful Run outcome
- [x] 4.5 Route the legacy `/api/plan/stream` behavior through the Runtime compatibility adapter without changing its current client-visible result contract
- [x] 4.6 Add parity tests comparing Runtime-backed planning results, progress stages, missing-field behavior, modifications, and itinerary persistence with the legacy path

## 5. Conversation and Chat Agent

- [x] 5.1 Add a Chat graph that classifies ordinary Chat, planning exploration, formal-plan creation intent, plan revision intent, and run-control intent
- [x] 5.2 Add a user-facing `respond` node tagged for `messages` streaming and keep all classifier, brief extractor, title, and planning model output internal
- [x] 5.3 Implement PlanningBrief creation and incremental update from conversation messages without duplicating the active brief
- [x] 5.4 Implement required-field readiness rules, documented optional defaults, and a custom `planning_brief.ready` confirmation payload
- [x] 5.5 Implement explicit direct-start validation and idempotent brief submission that creates exactly one formal PlanningRun
- [x] 5.6 Implement related-run and related-itinerary binding plus clarification when a plan-control or revision message has multiple plausible targets
- [x] 5.7 Add Chat and PlanningBrief tests for ordinary questions, incomplete requests, multi-turn completion, explicit confirmation, direct start, immutable snapshots, and ambiguous follow-ups

## 6. Resource-Oriented APIs

- [x] 6.1 Add authenticated conversation create/list/get and paginated message-history endpoints
- [x] 6.2 Add a message submission endpoint that persists the user message, creates a Chat Run, and immediately returns resource identifiers
- [x] 6.3 Add PlanningBrief read/update/submit/discard endpoints with owner checks and idempotent submission
- [x] 6.4 Add Run create/get/list, cancel, retry, and result-link endpoints with sanitized errors and correct terminal-state semantics
- [x] 6.5 Add Run event-history and SSE subscription endpoints supporting `after_seq`/`Last-Event-ID`, heartbeat, reconnect, and completed-run replay
- [x] 6.6 Add Run resume endpoint validating the outstanding interaction before issuing `Command(resume=...)`
- [x] 6.7 Add API authorization, validation, disconnect, idempotency, and cross-user isolation tests

## 7. Chat and Task-Card Frontend

- [x] 7.1 Add a Chat page with persistent conversation navigation, ordered message history, and a composer that remains usable while planning tasks run
- [x] 7.2 Implement frontend reducers keyed by message, PlanningBrief, and Run identifiers instead of the singleton `planPhase`
- [x] 7.3 Render LangGraph `messages` deltas into the active assistant message and reconcile them with the durable completed message
- [x] 7.4 Render PlanningBrief collecting/ready cards with missing information, editable summary, submit, continue-editing, and discard actions
- [x] 7.5 Render multiple independent Run cards for queued, running, waiting_user, succeeded, failed, and cancelled states
- [x] 7.6 Implement refresh and reconnect recovery by loading conversations, active Runs, event cursors, and resubscribing without duplicating events
- [x] 7.7 Add explicit run/itinerary context indicators for revisions and clarification UX when the target is ambiguous
- [x] 7.8 Add frontend tests for streaming text, concurrent task cards, queued status, cancellation, waiting-user resume, completion navigation, and refresh recovery

## 8. Human-in-the-Loop and Versioned Revisions

- [x] 8.1 Configure a durable LangGraph checkpointer for Chat and planning runs using stable Run/thread identifiers
- [x] 8.2 Replace missing-field process memory with `interrupt()` payloads, waiting-user Run state, and checkpointed resume
- [x] 8.3 Replace modification-warning continuation with the same interrupt/resume lifecycle and interaction idempotency checks
- [x] 8.4 Add itinerary version linkage and Revision Run creation without overwriting the base itinerary
- [x] 8.5 Enforce one committing revision per itinerary and test queued or rejected competing revisions
- [x] 8.6 Migrate or expire legacy `thread_store` and `pending_modifications` records, then remove their use after compatibility validation

## 9. Async I/O and Resource Limits

- [x] 9.1 Add shared async LLM invocation with retry semantics equivalent to `invoke_structured()` and migrate Chat nodes to `ainvoke()`
- [x] 9.2 Migrate planning LLM nodes to `ainvoke()` while preserving structured-output validation, logging, and retry behavior
- [x] 9.3 Replace blocking AMap and weather HTTP calls with a shared `httpx.AsyncClient`, async backoff, cache compatibility, and AMap concurrency limits
- [x] 9.4 Replace the per-day meal `ThreadPoolExecutor` with bounded asynchronous tasks and deterministic result ordering
- [x] 9.5 Isolate any remaining blocking SQLite, file, or legacy SDK operations behind explicit async adapter or `asyncio.to_thread()` boundaries
- [x] 9.6 Add concurrency and cancellation tests proving that one slow plan does not block another plan, ordinary Chat, or health/status endpoints

## 10. Validation, Operations, and Documentation

- [x] 10.1 Add end-to-end tests for Chat-to-brief-to-confirmation-to-itinerary, two concurrent plans, disconnect/reconnect, cancellation, failure/retry, and waiting-user resume
- [x] 10.2 Add structured metrics and logs for queued duration, run duration, active counts, stage duration, provider concurrency, cancellation, and failure reason
- [x] 10.3 Document runtime configuration defaults, concurrency limits, recovery behavior, event retention, and the absence of multi-node guarantees
- [x] 10.4 Document the module dependency boundary and add an automated check preventing planning/chat graphs from importing FastAPI or streaming adapters
- [x] 10.5 Validate legacy history, itinerary detail, manual editing, route optimization, profile updating, and authentication regressions
- [x] 10.6 Run the complete backend and frontend test suites, validate the OpenSpec change, and record any deferred production-scale work separately

## 11. Acceptance Regression Fixes

- [x] 11.1 Align PlanningBrief readiness with formal-planning date requirements so duration-only requests remain collecting until concrete start and end dates are available
- [x] 11.2 Restore the outstanding `waiting_user` interaction from durable Run events after refresh and keep its question and resume action visible after later status events
- [x] 11.3 Render submitted PlanningBriefs accurately and add backend/frontend regression coverage for readiness, refresh recovery, and submitted-state presentation
