## Why

The current planning flow binds one long-running LangGraph execution to one browser-owned SSE request and one singleton planning page, so users cannot reliably continue chatting, start another plan, reconnect after refresh, or resume a planning decision. Introducing a persistent event-driven Agent Runtime now establishes the execution and interaction foundation required for the planned Chat experience without replacing the existing travel-planning graph.

## What Changes

- Introduce persistent conversations, messages, planning briefs, agent runs, and run events as separate lifecycle objects.
- Add a Run Manager and bounded asynchronous scheduler so Chat runs and formal travel-planning runs execute independently from HTTP/SSE connections.
- Execute each active run as an independently cancellable coroutine while enforcing configurable per-user and global planning concurrency limits.
- Use LangGraph's native `astream()` output with `messages` for user-visible Chat text, `custom` for product events, and internal `updates`/interrupt handling.
- Convert SSE from the owner of planning execution into a resumable subscriber to an existing run.
- Add durable run status and selected event history so refreshes and temporary disconnections can restore task cards and completed output.
- Add a conversational planning lifecycle in which Chat builds an editable PlanningBrief, requests explicit confirmation, and only then creates a formal PlanningRun.
- Use LangGraph interrupt/resume for missing requirements and human decisions instead of process-local continuation state.
- Preserve the existing travel-planning graph and itinerary persistence behind a runtime execution adapter while legacy synchronous I/O is migrated incrementally to async APIs.
- Deprecate the process-local `thread_store` and the separate `pending_modifications` continuation semantics after their responsibilities move to conversations, planning briefs, runs, and checkpoints.

## Capabilities

### New Capabilities

- `conversational-planning`: Persistent Chat conversations collect and confirm structured travel requirements before starting formal planning.
- `agent-run-lifecycle`: Persistent run creation, status transitions, cancellation, interruption, resume, retry, and result association independent of client connections.
- `langgraph-streaming`: LangGraph-native streaming, safe frontend event projection, SSE subscription, reconnection, and event replay.
- `planning-concurrency`: Bounded concurrent execution of independent plans while preserving ordering for Chat turns and revisions of the same itinerary.

### Modified Capabilities

None.

## Impact

- Backend: new runtime, conversation, scheduling, event storage, and streaming modules; adaptations to `app/main.py`, `app/planning/graph.py`, planning continuation handling, and API routers.
- Database: new conversation, message, planning brief, run, and run-event tables plus migrations; existing itinerary and profile tables remain authoritative for completed travel artifacts.
- Frontend: a Chat surface, persistent message history, planning brief cards, independently updating planning task cards, reconnect logic, and removal of the singleton `planPhase` assumption.
- APIs: new conversation, message, planning brief, run status, run control, event history, and run stream endpoints; the existing `/api/plan/stream` remains available during migration.
- Runtime behavior: planning continues when configured to survive an SSE disconnect, but a single-node process restart initially reconciles orphaned running tasks to a visible failure unless they are safely resumable from a checkpoint.
- Dependencies: no Kafka, Celery, or external message broker is required for the first single-node implementation; SQLite remains the initial durable store.
