## Purpose

Defines the domain exception hierarchy for business-level error handling: a `DomainError` base class with sub-hierarchies for validation, task lifecycle, machine state, scheduling, and cloud-provider operational failures.

## Requirements

### Requirement: DomainError base class

The system SHALL provide a `DomainError(Exception)` base class for all
business-level exceptions. All domain exception classes SHALL be exposed via
`yascheduler.domain.exceptions` and `yascheduler.domain`.

#### Scenario: DomainError is catchable as Exception
- **WHEN** a `DomainError` subclass is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

### Requirement: ValidationError hierarchy

The system SHALL provide `ValidationError(DomainError)` with subclasses:
`UnsupportedEngineError` and `MissingInputFileError`.

#### Scenario: UnsupportedEngineError carries engine name
- **WHEN** `UnsupportedEngineError("gaussian")` is raised
- **THEN** the exception message contains "gaussian" and `e.engine_name == "gaussian"`

#### Scenario: MissingInputFileError carries engine and filename
- **WHEN** `MissingInputFileError("fleur", "inp.xml")` is raised
- **THEN** `e.engine_name == "fleur"` and `e.filename == "inp.xml"`

### Requirement: TaskError hierarchy

The system SHALL provide `TaskError(DomainError)` with subclasses
`TaskNotTodoError` and `TaskNotRunningError`. Each SHALL take a `TaskId` and
render the bare integer in its message.

`TaskAlreadyAllocatedError` and `TaskNotAllocatedError` are not part of the
hierarchy: allocation and the `TO_DO→RUNNING` transition are atomic, so neither
guard arises.

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
`node_id: NodeId` as the first argument and `hostname: str` as the second,
storing both as instance attributes.

The exception message format SHALL be:
`f"machine ({node_id}) at {hostname} is busy"`.

#### Scenario: MachineBusyError carries node_id and hostname
- **WHEN** `MachineBusyError(NodeId(1), "10.0.0.1")` is raised
- **THEN** `e.node_id == NodeId(1)`, `e.hostname == "10.0.0.1"`, and the exception message contains both the node_id and hostname

### Requirement: MachineConnectionError

The system SHALL provide `MachineConnectionError(DomainError)` for connection
failures when establishing SSH connections to remote machines. The constructor
SHALL take `node_id: NodeId` as the first argument, `hostname: str` as the
second, and `reason: str` as the third, storing all three as instance
attributes.

The exception message format SHALL be:
`f"cannot connect to machine ({node_id}) at {hostname}: {reason}"`.

#### Scenario: MachineConnectionError carries node_id, hostname, and reason
- **WHEN** `MachineConnectionError(NodeId(1), "10.0.0.1", "Connection refused")` is raised
- **THEN** `e.node_id == NodeId(1)`, `e.hostname == "10.0.0.1"`, `e.reason == "Connection refused"`, and the exception message contains the node_id, hostname, and reason

#### Scenario: MachineConnectionError is catchable as DomainError
- **WHEN** a `MachineConnectionError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

### Requirement: SchedulingError hierarchy

The system SHALL provide `SchedulingError(DomainError)` with subclasses
`NoCompatibleNodeError` and `CloudCapacityExhaustedError`. Each SHALL take a
`TaskId` and render the bare integer in its message.

`CloudCapacityExhaustedError` is a scheduling rule (no capacity to provision)
raised by the allocator; it SHALL remain under `SchedulingError` and SHALL NOT
be a subclass of `CloudError`.

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

`CloudError` covers operational cloud-provider failures (provider selection, VM
creation, SSH/cloud-init/engine setup). Cloud capacity planning is NOT part of
this hierarchy — see `CloudCapacityExhaustedError` under `SchedulingError`.

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