## MODIFIED Requirements

### Requirement: TaskError hierarchy

The system SHALL provide `TaskError(DomainError)` with subclasses
`TaskNotTodoError` and `TaskNotRunningError`. Each SHALL take a `TaskId` and
render the bare integer in its message.

#### Scenario: TaskNotTodoError carries TaskId
- **WHEN** `TaskNotTodoError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskNotRunningError carries TaskId
- **WHEN** `TaskNotRunningError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskError messages render bare integer
- **WHEN** `str(TaskNotTodoError(TaskId(42)))` is evaluated
- **THEN** the result contains `"42"` (NOT `"TaskId(value=42)"`)

### Requirement: MachineBusyError

The system SHALL provide `MachineBusyError(DomainError)` for operations
attempted on a busy machine. The constructor SHALL take
`node_id: NodeId` as the sole argument and store it as an instance attribute.

The exception message format SHALL be:
`f"machine ({node_id}) is busy"`.

#### Scenario: MachineBusyError carries node_id only

- **WHEN** `MachineBusyError(NodeId(1))` is raised
- **THEN** `e.node_id == NodeId(1)`, the exception message contains the bare integer `"1"` (NOT `"NodeId(value=1)"`), the exception does NOT have a `hostname` attribute, and the message format is `"machine (1) is busy"`

#### Scenario: MachineBusyError is catchable as DomainError

- **WHEN** a `MachineBusyError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

### Requirement: SchedulingError hierarchy

The system SHALL provide `SchedulingError(DomainError)` with subclasses
`NoCompatibleNodeError` and `CloudCapacityExhaustedError`. Each SHALL take a
`TaskId` and render the bare integer in its message.

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

### Requirement: CloudError hierarchy

The system SHALL provide `CloudError(DomainError)` as an intermediate root for
operational cloud-provider failures, with subclasses `CloudAllocateError` and
`CloudSetupError`. `CloudError` and its subclasses SHALL be catchable via
`except DomainError`.

`CloudError` SHALL be exported from `yascheduler.domain` (NOT from
`yascheduler.infra.cloud`). The leaf classes `CloudAllocateError` and
`CloudSetupError` remain re-exported from `yascheduler.infra.cloud`.

#### Scenario: CloudError is a DomainError

- **WHEN** the class hierarchy is inspected
- **THEN** `issubclass(CloudError, DomainError)` is true

#### Scenario: CloudAllocateError subclasses CloudError

- **WHEN** `CloudAllocateError("create failed")` is raised
- **THEN** it is caught by `except CloudError`, `except DomainError`, and
  `except Exception`
- **AND** `issubclass(CloudAllocateError, CloudError)` is true

#### Scenario: CloudSetupError subclasses CloudError

- **WHEN** `CloudSetupError("setup failed")` is raised
- **THEN** it is caught by `except CloudError`, `except DomainError`, and
  `except Exception`
- **AND** `issubclass(CloudSetupError, CloudError)` is true

#### Scenario: Cloud exceptions carry a free-form message

- **WHEN** `CloudAllocateError("Unknown provider: foo")` is raised
- **THEN** `str(e)` equals `"Unknown provider: foo"`

#### Scenario: CloudError is not a SchedulingError

- **WHEN** the class hierarchy is inspected
- **THEN** `issubclass(CloudError, SchedulingError)` is false

#### Scenario: Import CloudError from domain.exceptions

- **WHEN** a module imports `from yascheduler.domain.exceptions import CloudError`
- **THEN** the class is available

#### Scenario: Import CloudError from domain package

- **WHEN** a module imports `from yascheduler.domain import CloudError`
- **THEN** the class is available and present in `yascheduler.domain.__all__`

#### Scenario: infra.cloud does not re-export CloudError

- **WHEN** a module attempts `from yascheduler.infra.cloud import CloudError`
- **THEN** the import raises `ImportError`

#### Scenario: infra.cloud still re-exports the leaf cloud exceptions

- **WHEN** a module imports `from yascheduler.infra.cloud import CloudAllocateError, CloudSetupError`
- **THEN** both classes are available

#### Scenario: Import domain exceptions

- **WHEN** a module imports `from yascheduler.domain.exceptions import DomainError, ValidationError`
- **THEN** the classes are available
