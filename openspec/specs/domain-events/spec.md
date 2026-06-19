## Purpose

Defines the domain event types emitted by the Task aggregate and use cases to signal task lifecycle transitions (creation, allocation, completion, failure, abandonment). Events are immutable value objects carrying webhook delivery metadata on the base class.

## Requirements

### Requirement: Event base type with webhook fields

The system SHALL define a `DomainEvent` frozen dataclass base with fields
`task_id: int`, `webhook_url: str | None`, and
`webhook_custom_params: dict[str, object]`. An `Event` type alias SHALL be
defined as a union of all domain event subclasses.

#### Scenario: All events carry webhook URL
- **WHEN** any event type is instantiated
- **THEN** it is a frozen dataclass with `webhook_url` and `webhook_custom_params`
  accessible as attributes

### Requirement: TaskCreated event

The system SHALL provide a `TaskCreated(DomainEvent)` event with field:
`engine_name: str`.

#### Scenario: Event carries submission data
- **WHEN** `TaskCreated(task_id=42, webhook_url="https://...", webhook_custom_params={}, engine_name="fleur")` is created
- **THEN** all fields are accessible as attributes

### Requirement: TaskAllocated event

The system SHALL provide a `TaskAllocated(DomainEvent)` event with fields:
`node_ip: str`, `engine_name: str`.

#### Scenario: Event carries allocation data
- **WHEN** `TaskAllocated(task_id=42, webhook_url="https://...", webhook_custom_params={}, node_ip="10.0.0.1", engine_name="fleur")` is created
- **THEN** `event.node_ip == "10.0.0.1"`

### Requirement: TaskCompleted event

The system SHALL provide a `TaskCompleted(DomainEvent)` event with fields:
`local_folder: str`, `has_errors: bool`.

#### Scenario: Clean completion
- **WHEN** `TaskCompleted(task_id=42, webhook_url="https://...", webhook_custom_params={}, local_folder="/data/...", has_errors=False)` is created
- **THEN** `has_errors` is False

#### Scenario: Completion with errors
- **WHEN** `TaskCompleted(task_id=42, webhook_url="https://...", webhook_custom_params={}, local_folder="/data/...", has_errors=True)` is created
- **THEN** `has_errors` is True

### Requirement: TaskFailed event

The system SHALL provide a `TaskFailed(DomainEvent)` event with field:
`reason: str`.

#### Scenario: Event carries failure reason
- **WHEN** `TaskFailed(task_id=42, webhook_url="https://...", webhook_custom_params={}, reason="unsupported engine")` is created
- **THEN** `event.reason == "unsupported engine"`

### Requirement: TaskAbandoned event

The system SHALL provide a `TaskAbandoned(DomainEvent)` event with field:
`node_ip: str`.

#### Scenario: Event carries abandoned node IP
- **WHEN** `TaskAbandoned(task_id=42, webhook_url="https://...", webhook_custom_params={}, node_ip="10.0.0.1")` is created
- **THEN** `event.node_ip == "10.0.0.1"`

### Requirement: Events importable from domain

The system SHALL expose all event types from `yascheduler.domain.events`.

#### Scenario: Import events
- **WHEN** `from yascheduler.domain.events import TaskCreated, TaskAllocated` is executed
- **THEN** both classes are available
