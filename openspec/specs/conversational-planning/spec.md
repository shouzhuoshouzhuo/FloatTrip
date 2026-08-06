# conversational-planning Specification

## Purpose
Define persistent travel conversations that produce an editable planning brief and require explicit confirmation before formal planning starts.

## Requirements

### Requirement: Persistent conversations and messages
The system SHALL persist each authenticated user's conversations and ordered user-visible messages independently of active browser sessions.

#### Scenario: Restore a conversation after refresh
- **WHEN** a user refreshes or reopens an existing conversation
- **THEN** the system returns its persisted messages in stable conversation order

#### Scenario: Isolate conversations by owner
- **WHEN** a user requests a conversation owned by another user
- **THEN** the system denies access without exposing the conversation contents

### Requirement: Planning intent does not immediately start formal planning
The Chat Agent SHALL distinguish ordinary conversation from a possible formal-planning request and SHALL NOT create a formal PlanningRun solely because travel-planning intent was inferred.

#### Scenario: User asks a general travel question
- **WHEN** a user asks whether October is suitable for visiting Yunnan
- **THEN** the system responds as ordinary Chat without creating a formal planning run

#### Scenario: User expresses an incomplete planning intention
- **WHEN** a user asks for a Yunnan itinerary without the required date information
- **THEN** the system creates or updates a PlanningBrief and requests the missing required information

### Requirement: Structured planning brief
The system SHALL maintain an editable PlanningBrief containing the structured requirements collected from conversation, its readiness status, and the source conversation.

#### Scenario: Update a brief from a follow-up answer
- **WHEN** the user supplies dates requested for an existing collecting brief
- **THEN** the system updates that brief rather than creating a duplicate brief

#### Scenario: Optional preferences are absent
- **WHEN** destination and required date information are complete but optional budget or food preferences are absent
- **THEN** the brief can become ready using documented defaults

#### Scenario: Duration is present without calendar dates
- **WHEN** the user provides a destination and trip duration but no concrete start and end dates
- **THEN** the brief remains collecting and identifies the missing calendar dates required by formal planning

#### Scenario: Concrete date range completes the brief
- **WHEN** the brief contains a destination plus valid start and end dates
- **THEN** the brief becomes ready even when optional preferences are absent

### Requirement: Explicit formal-planning confirmation
The system SHALL present a user-visible summary of a ready PlanningBrief and SHALL require an explicit submit action before creating a formal PlanningRun, unless the user has issued an explicit supported direct-start command with all required information.

#### Scenario: Confirm a ready brief
- **WHEN** the user selects “开始正式规划” on a ready brief
- **THEN** the system submits the brief and creates exactly one formal PlanningRun

#### Scenario: Continue editing a ready brief
- **WHEN** the user chooses to adjust a ready brief
- **THEN** the system keeps the brief editable and does not start formal planning

### Requirement: Immutable execution snapshot
The system SHALL copy a submitted PlanningBrief into an immutable Run request snapshot, and subsequent conversation messages SHALL NOT silently mutate that running request.

#### Scenario: User adds a constraint while planning is running
- **WHEN** a user says “不要安排丽江” after the corresponding formal run has started
- **THEN** the system offers an explicit restart or later-revision action instead of modifying the active run in place

### Requirement: Explicit target binding
Messages and actions that control or revise a plan SHALL identify the related run or itinerary whenever more than one plausible target exists.

#### Scenario: Ambiguous revision request
- **WHEN** the conversation contains multiple active or completed plans and the user says “第三天松一点” without selecting one
- **THEN** the system asks the user to identify the intended plan before creating a revision run

#### Scenario: Revision from an itinerary card
- **WHEN** the user selects “继续修改” on a specific itinerary card
- **THEN** the next revision request is bound to that itinerary
