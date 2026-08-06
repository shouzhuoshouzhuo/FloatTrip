# agent-run-lifecycle Specification

## Purpose
Define durable agent run identity, lifecycle transitions, cancellation, retry, interaction, recovery, and result association across client reconnects.

## Requirements

### Requirement: Persistent run identity
The system SHALL assign every Chat, formal planning, and itinerary revision execution a unique Run identifier and persist the Run before execution begins.

#### Scenario: Create a planning run
- **WHEN** a ready PlanningBrief is submitted
- **THEN** the system persists a queued Run with kind `travel_plan`, owner, conversation, immutable request snapshot, and creation timestamp

#### Scenario: Return before completion
- **WHEN** a client creates a Run
- **THEN** the create operation returns the Run identifier and current status without waiting for Agent completion

### Requirement: Defined lifecycle transitions
The system SHALL expose Run status using `queued`, `running`, `waiting_user`, `succeeded`, `failed`, or `cancelled`, and SHALL persist each transition.

#### Scenario: Successful execution
- **WHEN** a queued run is admitted, executes, and produces its required result
- **THEN** its status transitions through running to succeeded

#### Scenario: Execution failure
- **WHEN** an unhandled provider, graph, or persistence error prevents result production
- **THEN** the Run becomes failed with a sanitized user-visible error and an internal diagnostic record

### Requirement: Client-independent execution
The lifecycle of a Run SHALL be independent of the lifecycle of any individual SSE connection, subject to the Run's configured disconnect policy.

#### Scenario: Continue after temporary disconnect
- **WHEN** an SSE subscriber disconnects from a Run configured to continue
- **THEN** the Run continues executing and its durable status remains queryable

#### Scenario: Refresh during execution
- **WHEN** a user refreshes the Chat page while a planning run is active
- **THEN** the application can restore the Run card from persisted Run state

#### Scenario: Refresh while waiting for input
- **WHEN** a user refreshes while a Run is `waiting_user`
- **THEN** the application restores the outstanding durable interaction, including its question and resume action, even if the browser previously persisted a later event cursor

### Requirement: Run cancellation
The system SHALL provide an idempotent cancellation operation for queued, running, and already-cancelled Runs.

#### Scenario: Cancel a queued run
- **WHEN** the owner cancels a queued run
- **THEN** it is removed from scheduling eligibility and becomes cancelled

#### Scenario: Cancel a running run
- **WHEN** the owner cancels a running run
- **THEN** the runtime requests cooperative cancellation, prevents a successful result commit after cancellation, and ultimately marks the run cancelled

#### Scenario: Repeat cancellation
- **WHEN** the owner repeats cancellation for an already-cancelled run
- **THEN** the operation succeeds without creating another transition

### Requirement: Human interaction and resume
The system SHALL represent missing input or a required human decision as `waiting_user` and SHALL resume the same Run from its LangGraph checkpoint after a valid response.

#### Scenario: Planning requires missing dates
- **WHEN** the graph interrupts because required dates are missing
- **THEN** the Run becomes waiting_user and exposes a safe structured question

#### Scenario: Resume a waiting run
- **WHEN** the owner submits a valid response for the outstanding interaction
- **THEN** the system resumes the same Run via `Command(resume=...)` and transitions it back to running

#### Scenario: Reject stale resume
- **WHEN** a response targets an interaction that is no longer outstanding
- **THEN** the system rejects it without executing the graph twice

### Requirement: Retry creates a new attempt
The system SHALL create a new Run linked to the failed or cancelled Run when the user retries, rather than changing a terminal Run back to running.

#### Scenario: Retry a failed plan
- **WHEN** the owner retries a failed planning run without changing the request
- **THEN** a new queued Run is created with `retry_of_run_id` referencing the failed Run

### Requirement: Result association
A successful formal planning or revision Run SHALL reference its resulting itinerary, while the itinerary remains the authoritative travel artifact.

#### Scenario: Formal plan completes
- **WHEN** finalization successfully commits an itinerary
- **THEN** the Run becomes succeeded and records the resulting itinerary identifier

#### Scenario: Profile update fails after completion
- **WHEN** asynchronous profile updating fails after the itinerary is committed
- **THEN** the successful planning Run and itinerary remain successful and accessible

### Requirement: Startup reconciliation
The system SHALL reconcile persisted non-terminal Runs when the single-node runtime starts.

#### Scenario: Recover queued work
- **WHEN** the runtime starts and finds a safely retryable queued Run
- **THEN** the scheduler makes it eligible for execution according to configured recovery policy

#### Scenario: Find an orphaned running run
- **WHEN** the runtime starts and finds a running Run with no live local task and no proven safe resume path
- **THEN** it marks the Run failed with a recoverable restart explanation instead of leaving it indefinitely active
