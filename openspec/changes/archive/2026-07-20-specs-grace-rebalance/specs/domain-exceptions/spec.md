## MODIFIED Requirements

### Requirement: MachineBusyError

The system SHALL provide `MachineBusyError(DomainError)` for operations
attempted on a busy machine. The constructor SHALL take `node_id: NodeId` as
the sole argument and store it as an instance attribute.

The exception message format string lives in the `CLASS_MachineBusyError`
GRACE INVARIANTS — it is shape, not behavior. The spec keeps only the
behavioral "carries `node_id` only" contract.

#### Scenario: MachineBusyError carries node_id only

- **WHEN** `MachineBusyError(NodeId(1))` is raised
- **THEN** `e.node_id == NodeId(1)`, the exception message contains the bare integer `"1"` (NOT `"NodeId(value=1)"`), the exception does NOT have a `hostname` attribute, and the message format is `"machine (1) is busy"`

#### Scenario: MachineBusyError is catchable as DomainError

- **WHEN** a `MachineBusyError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

### Requirement: MachineConnectionError

The system SHALL provide `MachineConnectionError(DomainError)` for
connection failures when establishing SSH connections to remote machines.
The constructor SHALL take `node_id: NodeId` as the first argument,
`hostname: str` as the second, and `reason: str` as the third, storing all
three as instance attributes.

The exception message format string lives in the
`CLASS_MachineConnectionError` GRACE INVARIANTS — it is shape, not behavior.

#### Scenario: MachineConnectionError carries node_id, hostname, and reason
- **WHEN** `MachineConnectionError(NodeId(1), "10.0.0.1", "Connection refused")` is raised
- **THEN** `e.node_id == NodeId(1)`, `e.hostname == "10.0.0.1"`, `e.reason == "Connection refused"`, and the exception message contains the node_id, hostname, and reason

#### Scenario: MachineConnectionError is catchable as DomainError
- **WHEN** a `MachineConnectionError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

### Requirement: TaskError hierarchy

The system SHALL provide `TaskError(DomainError)` with subclasses
`TaskNotTodoError` and `TaskNotRunningError`. Each SHALL take a `TaskId` and
render the bare integer in its message.

The exact message format string lives in the respective `CLASS_*` GRACE
INVARIANTS.

#### Scenario: TaskNotTodoError carries TaskId
- **WHEN** `TaskNotTodoError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskNotRunningError carries TaskId
- **WHEN** `TaskNotRunningError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskError messages render bare integer
- **WHEN** `str(TaskNotTodoError(TaskId(42)))` is evaluated
- **THEN** the result contains `"42"` (NOT `"TaskId(value=42)"`)

### Requirement: SchedulingError hierarchy

The system SHALL provide `SchedulingError(DomainError)` with subclasses
`NoCompatibleNodeError` and `CloudCapacityExhaustedError`. Each SHALL take a
`TaskId` and render the bare integer in its message.

The exact message format strings live in the respective `CLASS_*` GRACE
INVARIANTS.

#### Scenario: NoCompatibleNodeError carries TaskId and platforms
- **WHEN** `NoCompatibleNodeError(TaskId(42), ["linux", "debian-12"])` is raised
- **THEN** `e.task_id == TaskId(42)` and `e.platforms == ["linux", "debian-12"]`

#### Scenario: CloudCapacityExhaustedError carries TaskId
- **WHEN** `CloudCapacityExhaustedError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)`

#### Scenario: CloudCapacityExhaustedError stays under SchedulingError
- **WHEN** the class hierarchy is inspected
- **THEN** `issubclass(CloudCapacityExhaustedError, SchedulingError)` is true
- **AND** `issubclass(CloudCapacityExhaustedError, CloudError)` is false
