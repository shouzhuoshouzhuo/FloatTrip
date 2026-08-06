# langgraph-streaming Specification

## Purpose
Define the LangGraph-native event stream, durable replay behavior, client reconnection protocol, filtering, confidentiality, and product-facing events.

## Requirements

### Requirement: LangGraph-native stream source
The system SHALL use LangGraph `astream()` version 2 as the source of Agent streaming output.

#### Scenario: Stream a Chat run
- **WHEN** the runtime executes a Chat graph
- **THEN** it consumes LangGraph `messages`, `custom`, and internal `updates` stream parts

#### Scenario: Stream a formal planning run
- **WHEN** the runtime executes a formal planning graph
- **THEN** it consumes LangGraph `custom` and internal `updates` stream parts without exposing internal model token streams

### Requirement: User-visible message filtering
The system SHALL forward `messages` stream parts only from the explicitly allowlisted user-facing Chat response node or tag.

#### Scenario: Main Chat response token
- **WHEN** the allowlisted response node emits an `AIMessageChunk` containing displayable text
- **THEN** the system streams that text delta for the associated assistant message

#### Scenario: Internal intent model token
- **WHEN** an intent classifier, brief extractor, title generator, planner, or reviewer emits model output
- **THEN** the system does not forward that output as user-visible Chat text

### Requirement: Product events use custom stream output
The Chat and planning graphs SHALL use LangGraph custom stream writers for validated product events that the frontend renders as structured UI.

#### Scenario: Planning brief becomes ready
- **WHEN** the Chat graph determines that a PlanningBrief is ready for confirmation
- **THEN** it emits a validated custom event with kind `planning_brief.ready` and a safe summary

#### Scenario: Planning stage advances
- **WHEN** the planning graph enters a user-meaningful stage
- **THEN** it emits a validated `planning_run.progress` custom event without raw prompts or graph state

### Requirement: Minimal public stream protocol
The public SSE stream SHALL expose only `messages`, `custom`, sanitized `error`, heartbeat, and terminal `end` events.

#### Scenario: Internal update is produced
- **WHEN** LangGraph emits an `updates`, `values`, `tasks`, `checkpoints`, or `debug` payload
- **THEN** the runtime does not forward the raw payload to the ordinary frontend

#### Scenario: Run terminates normally
- **WHEN** the graph and runtime finalization complete
- **THEN** the SSE stream emits one terminal `end` event

#### Scenario: Run fails
- **WHEN** execution raises an unrecoverable error
- **THEN** the stream emits a sanitized `error` followed by `end`

### Requirement: Durable event replay and reconnection
The system SHALL allow an authorized client to retrieve selected persisted Run events after a sequence cursor and then subscribe to current live output without duplicating applied events.

#### Scenario: Reconnect after a dropped connection
- **WHEN** a client reconnects with the last applied event sequence
- **THEN** the system returns subsequent durable events in ascending sequence and continues with live notifications

#### Scenario: Reconnect after completion
- **WHEN** a client reconnects after the Run has already completed
- **THEN** the system returns the persisted terminal state and selected events without attempting to restart the Run

### Requirement: Event durability policy
The system SHALL persist lifecycle transitions, planning brief events, planning stage changes, interrupts, final assistant messages, errors, and result associations, while it SHALL NOT require every token delta or heartbeat to be stored.

#### Scenario: Chat token is emitted
- **WHEN** the Chat model emits a token delta
- **THEN** the delta may be live-only and the final complete assistant message is persisted

#### Scenario: Progress stage changes
- **WHEN** the formal planning stage changes
- **THEN** the new stage event is persisted before its live notification is published

### Requirement: Stream confidentiality
The system SHALL exclude chain-of-thought, system prompts, authentication secrets, raw provider responses, private profile payloads, internal exceptions, and full LangGraph state from public streams.

#### Scenario: Reviewer generates internal reasoning
- **WHEN** the Reviewer produces reasoning used by the planning graph
- **THEN** the frontend receives only an approved user-facing progress summary, not the reasoning content
