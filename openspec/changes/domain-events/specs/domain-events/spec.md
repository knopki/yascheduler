## ADDED Requirements

### Requirement: Event base type

The system SHALL define an `Event` type as a union of all domain event
dataclasses, usable as a protocol base for the message bus.

#### Scenario: All events are dataclasses
- **WHEN** any event type is instantiated
- **THEN** it is a frozen dataclass with no methods

### Requirement: TaskCreated event

The system SHALL provide a `TaskCreated` event with fields: `task_id: int`,
`engine_name: str`, `webhook_url: str | None`, `custom_params: dict[str, object]`.

#### Scenario: Event carries submission data
- **WHEN** `TaskCreated(task_id=42, engine_name="fleur", webhook_url="https://...", custom_params={})` is created
- **THEN** all fields are accessible as attributes

### Requirement: TaskAllocated event

The system SHALL provide a `TaskAllocated` event with fields: `task_id: int`,
`node_ip: str`, `engine_name: str`.

#### Scenario: Event carries allocation data
- **WHEN** `TaskAllocated(task_id=42, node_ip="10.0.0.1", engine_name="fleur")` is created
- **THEN** `event.node_ip == "10.0.0.1"`

### Requirement: TaskCompleted event

The system SHALL provide a `TaskCompleted` event with fields: `task_id: int`,
`local_folder: str`, `has_errors: bool`.

#### Scenario: Clean completion
- **WHEN** `TaskCompleted(task_id=42, local_folder="/data/...", has_errors=False)` is created
- **THEN** `has_errors` is False

#### Scenario: Completion with errors
- **WHEN** `TaskCompleted(task_id=42, local_folder="/data/...", has_errors=True)` is created
- **THEN** `has_errors` is True

### Requirement: TaskFailed event

The system SHALL provide a `TaskFailed` event with fields: `task_id: int`,
`reason: str`.

#### Scenario: Event carries failure reason
- **WHEN** `TaskFailed(task_id=42, reason="unsupported engine")` is created
- **THEN** `event.reason == "unsupported engine"`

### Requirement: TaskAbandoned event

The system SHALL provide a `TaskAbandoned` event with fields: `task_id: int`,
`node_ip: str`.

#### Scenario: Event carries abandoned node IP
- **WHEN** `TaskAbandoned(task_id=42, node_ip="10.0.0.1")` is created
- **THEN** `event.node_ip == "10.0.0.1"`

### Requirement: Events importable from application

The system SHALL expose all event types from `yascheduler.application.events`.

#### Scenario: Import events
- **WHEN** `from yascheduler.application.events import TaskCreated, TaskAllocated` is executed
- **THEN** both classes are available
