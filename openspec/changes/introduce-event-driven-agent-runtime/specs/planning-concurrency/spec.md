## ADDED Requirements

### Requirement: Independent formal planning runs
The system SHALL allow one user to create more than one independent formal planning run without requiring an existing run to finish first.

#### Scenario: Start a second plan
- **WHEN** a user has one running formal plan and submits a different ready PlanningBrief
- **THEN** the system creates a distinct Run for the second plan instead of returning the first plan's progress

### Requirement: Bounded planning admission
The scheduler SHALL enforce configurable per-user and global limits for simultaneously running formal planning runs while still accepting excess work as queued.

#### Scenario: User capacity is available
- **WHEN** a queued planning run is below both user and global limits
- **THEN** the scheduler admits it and transitions it to running

#### Scenario: User capacity is exhausted
- **WHEN** a user submits another plan after reaching the per-user running limit
- **THEN** the new Run remains queued and its position or queued status is visible

#### Scenario: Capacity becomes available
- **WHEN** a running planning run reaches a terminal or waiting state and capacity is released
- **THEN** the scheduler admits an eligible queued run according to deterministic queue ordering

### Requirement: Chat remains responsive during planning
The runtime SHALL allocate Chat execution separately from formal planning capacity so that active or queued plans do not prevent normal conversation.

#### Scenario: Chat while two plans are active
- **WHEN** a user sends an ordinary Chat message while their formal planning capacity is full
- **THEN** the Chat Run remains eligible to execute and stream its response

### Requirement: Ordered Chat turns
The runtime SHALL serialize Chat runs within the same conversation unless an explicit interruption policy is selected.

#### Scenario: Two Chat messages arrive quickly
- **WHEN** two user messages are submitted to the same conversation before the first response completes
- **THEN** the system processes them in conversation order or explicitly interrupts the first according to the selected policy

### Requirement: Serialized itinerary revisions
The runtime SHALL prevent concurrent revision runs from committing competing versions of the same base itinerary.

#### Scenario: Revision already running
- **WHEN** a second revision request targets an itinerary that already has a running revision
- **THEN** the system queues or rejects the second revision according to the documented revision policy

#### Scenario: Revision commits
- **WHEN** a revision run completes successfully
- **THEN** it creates a new itinerary version linked to the base version without overwriting the previous version

### Requirement: Bounded provider concurrency
The runtime SHALL enforce separate configurable limits for LLM calls and AMap calls, including calls created concurrently within one planning run.

#### Scenario: Multi-day meal recommendation
- **WHEN** meal recommendations for several days are eligible to execute concurrently
- **THEN** the runtime executes them asynchronously without exceeding the configured LLM-call limit

#### Scenario: Run cancellation releases capacity
- **WHEN** a running planning run is cancelled and its task settles
- **THEN** its run, LLM, and provider capacity permits are released for other eligible work
