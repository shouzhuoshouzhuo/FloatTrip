## Context

The current application executes a travel-planning LangGraph inside the generator owned by `POST /api/plan/stream`. Progress is streamed directly from that request, completed itineraries are persisted only at finalization, missing-field continuation is stored in a process-local `thread_store`, and the frontend maintains one global `PlanPage`/`planPhase`. LangGraph currently protects the event loop by offloading synchronous graph nodes to an executor, but LLM, AMap, Redis, and SQLite calls are predominantly blocking and each active node occupies a thread.

The planned Chat surface changes the product boundary. A user must be able to continue a normal conversation, prepare a formal planning request, start more than one independent plan, leave or refresh the page, and later inspect or resume each task. Agent execution therefore needs a stable identity and lifecycle outside any individual HTTP connection.

The first deployment remains a single FastAPI process using SQLite. Existing itinerary data and the current planning graph must remain usable during migration.

## Goals / Non-Goals

**Goals:**

- Separate HTTP/SSE transport, run lifecycle management, and LangGraph execution.
- Represent conversations, messages, planning briefs, runs, events, and itinerary results explicitly.
- Execute independent runs as bounded asynchronous tasks without blocking Chat interaction.
- Use LangGraph-native streaming and interrupt/resume primitives.
- Persist enough state and event history to restore UI state after refresh or temporary network loss.
- Preserve the existing travel-planning behavior while synchronous I/O is migrated incrementally.
- Provide clear compatibility and rollback boundaries during migration.

**Non-Goals:**

- Introducing Kafka, RabbitMQ, Celery, Redis Streams, or a multi-service deployment in the first release.
- Providing exactly-once distributed execution or automatic cross-process task takeover.
- Exposing chain-of-thought, prompts, raw LangGraph state, or provider payloads to clients.
- Dynamically changing an already-running formal planning request.
- Allowing unlimited planning or LLM concurrency.
- Replacing the existing itinerary editor, history view, profile model, or planning quality logic.

## Decisions

### 1. Establish one-way application and runtime boundaries

The backend will use the dependency direction:

```text
API adapters -> application services -> agent runtime -> Chat/planning graphs
                                      \-> infrastructure adapters
```

`app/runtime` will own run records, scheduling, cancellation, event persistence, and stream publication. `app/planning` and the new Chat graph will not import FastAPI, `StreamingResponse`, or frontend-specific code. API routers will translate commands and runtime output into HTTP responses.

This adopts DeerFlow's Harness/App separation principle without extracting a separately published package. A package extraction would add maintenance cost before the boundary has stabilized.

### 2. Separate durable domain objects

The following objects will be stored separately:

- `Conversation`: long-lived user interaction container.
- `Message`: ordered user or assistant content in a conversation.
- `PlanningBrief`: mutable, structured requirements collected before formal execution.
- `Run`: one execution attempt with `kind`, lifecycle status, immutable request snapshot, and optional result association.
- `RunEvent`: ordered, selected lifecycle or product event associated with one run.
- `Itinerary`: completed travel artifact, retaining the existing itinerary representation.

A PlanningBrief becomes immutable for execution by copying it into `Run.request_snapshot` at submission. Later messages cannot silently mutate that snapshot.

### 3. Use a persistent run lifecycle with coroutine execution

Run status will be:

```text
queued -> running -> waiting_user -> running
                  \-> succeeded | failed | cancelled
```

Creation will persist the `queued` run before scheduling it. The application will execute an admitted run in an `asyncio.Task`; the task handle and cancellation event remain process-local, while status and metadata remain durable.

A bounded scheduler will claim queued runs and apply per-kind concurrency controls. In the first release, startup reconciliation will requeue safe `queued` records and mark orphaned `running` records failed with a recoverable explanation unless a checkpoint-specific resume path is explicitly supported. This is preferred over pretending that a process-local coroutine survived a restart.

An external task broker was considered but rejected for the first release because the application is single-node and the operational cost is not yet justified.

### 4. Use distinct concurrency keys

Concurrency is not governed solely by `conversation_id`.

- Chat runs use `chat:{conversation_id}` and execute sequentially to preserve response order.
- New formal plans use `plan:{run_id}` and may execute independently.
- Revisions use `revision:{itinerary_id}` and execute sequentially to prevent concurrent version updates.

Formal planning is further limited by configurable per-user and global semaphores. A user may create a task even when capacity is exhausted; it remains `queued`. Chat runs use a separate capacity pool so planning cannot starve ordinary conversation.

### 5. Use LangGraph `astream()` as the agent output source

Chat graphs will run with:

```text
stream_mode=["messages", "custom", "updates"], version="v2"
```

Formal planning graphs will run with:

```text
stream_mode=["custom", "updates"], version="v2"
```

The runtime will consume `updates` internally for final output and interrupt detection. Client-visible streams will expose:

- `messages`: token deltas only from the explicitly tagged or named user-facing response node.
- `custom`: safe product events written through LangGraph `get_stream_writer()`.
- `error`: sanitized runtime failure.
- `end`: terminal stream marker.

`values`, `debug`, checkpoint payloads, raw task output, internal LLM messages, and unfiltered node updates will not be forwarded to the browser.

`astream_events()` was considered but rejected as the product protocol because it exposes callback-level implementation details and produces significantly more traffic.

### 6. Separate durable event history from live notification

Selected lifecycle and product events will be persisted in `run_events` with a monotonically increasing sequence scoped to `run_id`. The runtime will persist an event before publishing its live notification.

Live subscribers will use an in-process stream bridge in the first release. On connection or reconnection, the API will first return persisted events after the client's cursor and then continue with live notifications. Final assistant messages are durable; token deltas are live-only, with throttled message snapshots allowed if needed for mid-generation refresh recovery.

Run-local sequence numbers avoid unnecessary SQLite contention when multiple runs belong to the same conversation. Conversation message ordering remains a separate monotonic sequence.

### 7. Use LangGraph checkpointers for human interaction

Missing requirements and planning decisions will use LangGraph `interrupt()` and `Command(resume=...)`. When an interrupt is observed, the runtime will:

1. persist the checkpoint through the configured LangGraph checkpointer;
2. mark the Run `waiting_user`;
3. persist and publish a safe custom event describing the required input.

Resume commands must identify both `run_id` and the outstanding interaction identifier. Duplicate resume submissions must be rejected or handled idempotently.

The current process-local `thread_store` and independent `pending_modifications` table will remain during compatibility migration, then be removed once all continuation paths use the unified model.

### 8. Keep runtime events distinct from business results

Run events describe execution and UI updates. The itinerary remains the authoritative completed artifact. A successful planning run stores `result_itinerary_id`; it does not embed the entire itinerary in the run row.

Profile updating will be triggered after an itinerary is committed. It may become an internal consumer of `planning.itinerary_created`, but its failure will not change a successful planning run to failed.

### 9. Introduce APIs around resources rather than requests

The application will add APIs for conversations, messages, planning briefs, run status/control, event history, and streaming. Run creation returns immediately with the resource identity and current status. A separate endpoint subscribes to an existing run.

The legacy `/api/plan/stream` endpoint will remain during migration and can internally adapt to the new runtime. It will be deprecated only after the Chat and planning task-card flows use the resource APIs.

### 10. Migrate blocking I/O independently from the lifecycle refactor

The runtime contract is asynchronous, but existing synchronous planning nodes may initially execute through LangGraph's executor behavior or explicit `asyncio.to_thread()` boundaries. Subsequent work will convert:

- `llm.invoke()` to `await llm.ainvoke()`;
- `urllib.request` to a shared `httpx.AsyncClient`;
- `time.sleep()` to `await asyncio.sleep()`;
- per-day `ThreadPoolExecutor` work to bounded async tasks;
- blocking persistence calls to async adapters where beneficial.

This sequence avoids combining a correctness-sensitive lifecycle migration with a full provider rewrite.

## Risks / Trade-offs

- **[Process-local execution is not durable]** A server restart terminates coroutine tasks. → Persist every status transition, reconcile orphaned tasks visibly, and defer automatic resume until checkpoint/idempotency behavior is proven.
- **[SQLite write contention]** Multiple runs can update status and events concurrently. → Use short transactions, WAL mode, run-local event sequences, batched/throttled progress writes, and bounded concurrency.
- **[Live/durable stream race]** Events could be missed between replay and subscription. → Establish the subscription cursor under the stream bridge and deduplicate by persisted event sequence; test the replay-to-live handoff explicitly.
- **[Internal information leakage]** LangGraph `messages` and `updates` can contain internal LLM calls or state. → Allowlist the response node/tag and map custom payloads through validated public schemas.
- **[Nested concurrency overload]** Multiple plans and per-day meal requests can multiply LLM calls. → Apply separate run, LLM, and AMap semaphores and eliminate unbounded per-run thread pools.
- **[Ambiguous follow-up messages]** A conversation may contain several active plans. → Require explicit `related_run_id`/`related_itinerary_id` binding for control and revision actions, and ask for clarification when no unique target exists.
- **[Large migration surface]** Runtime, APIs, persistence, and frontend state all change. → Deliver behind compatibility adapters in staged increments and keep the legacy planning endpoint operational until parity tests pass.

## Migration Plan

1. Add database migrations and repositories for conversations, messages, planning briefs, runs, and run events without changing existing endpoints.
2. Add Run Manager, scheduler, event store, and in-memory stream bridge with lifecycle and concurrency tests.
3. Adapt the existing planning graph to a Planning Worker and LangGraph-native `custom` progress output; keep synchronous provider calls behind safe async boundaries.
4. Route the legacy planning endpoint through the Runtime while preserving its current response shape.
5. Add resource-oriented run status, cancel, resume, events, and stream APIs.
6. Add Conversation/Chat APIs and frontend state capable of rendering messages, planning briefs, and multiple independent run cards.
7. Move missing-field and modification confirmation flows to interrupt/resume.
8. Remove the old process-local continuation paths after production data and behavior have migrated.
9. Independently convert blocking provider calls to true async I/O and tune concurrency limits.

Rollback keeps the legacy endpoint and existing itinerary tables intact. New tables are additive. Before removing compatibility paths, rollback consists of disabling Runtime-backed routing and returning planning traffic to the existing stream implementation.

## Open Questions

- Should a queued run survive application restart and be automatically requeued by default, or require explicit user retry in the first release?
- What initial global planning and LLM concurrency limits match provider quotas in the deployment environment?
- How long should completed run events and assistant message snapshots be retained?
- Should a user instruction aimed at a running plan default to “restart now” or “apply as a revision after completion” in the Chat UI?
