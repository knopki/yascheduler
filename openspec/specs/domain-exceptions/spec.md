## Purpose

Defines the domain exception hierarchy for business-level error handling: DomainError base class with sub-hierarchies for validation, task lifecycle, machine state, and scheduling errors.

## Requirements

### Requirement: DomainError base class

The system SHALL provide a `DomainError(Exception)` base class for all
business-level exceptions.

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

The system SHALL provide `TaskError(DomainError)` with subclasses:
`TaskNotTodoError`, `TaskNotRunningError`. Each SHALL take `task_id: TaskId`
(was `int`); the `f"task {task_id} ..."` message renders the bare integer via
`TaskId.__str__`, so the message text is unchanged in appearance.

`TaskAlreadyAllocatedError` and `TaskNotAllocatedError` are REMOVED. They
guarded the `TO_DO + allocated` intermediate state produced by the prior
`allocate_to` + `mark_running` two-step. With `run` collapsing allocation
and the `TO_DO→RUNNING` transition into one atomic method, allocation is
atomic with running and neither guard arises. The remaining
`TaskNotTodoError` (raised by `run` and `reject`) and `TaskNotRunningError`
(raised by `complete`, `fail`, `abandon`) cover all five transition guards.

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
attempted on a busy machine.

#### Scenario: MachineBusyError carries IP
- **WHEN** `MachineBusyError("10.0.0.1")` is raised
- **THEN** the exception message contains the IP address

### Requirement: MachineConnectionError

The system SHALL provide `MachineConnectionError(DomainError)` for connection
failures when establishing SSH connections to remote machines.

#### Scenario: MachineConnectionError carries IP and reason
- **WHEN** `MachineConnectionError("10.0.0.1", "Connection refused")` is raised
- **THEN** `e.ip == "10.0.0.1"` and the exception message contains both the IP and reason

#### Scenario: MachineConnectionError is catchable as DomainError
- **WHEN** a `MachineConnectionError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

### Requirement: SchedulingError hierarchy

The system SHALL provide `SchedulingError(DomainError)` with subclasses:
`NoCompatibleNodeError` and `CloudCapacityExhaustedError`.
`CloudCapacityExhaustedError` is a scheduling rule (no capacity to provision)
raised by the allocator; it deliberately remains under `SchedulingError` and
SHALL NOT be a subclass of `CloudError`. `NoCompatibleNodeError` and
`CloudCapacityExhaustedError` SHALL take `task_id: TaskId` (was `int`); the
`f"... task {task_id} ..."` messages render the bare integer via
`TaskId.__str__`.

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
- **AND** the class defines no custom `__init__` beyond `Exception`

#### Scenario: CloudError is not a SchedulingError

- **WHEN** the class hierarchy is inspected
- **THEN** `issubclass(CloudError, SchedulingError)` is false

### Requirement: CloudError is exported from yascheduler.domain

The system SHALL export `CloudError` from both `yascheduler.domain.exceptions`
and the `yascheduler.domain` package (`__all__`).

#### Scenario: Import CloudError from domain.exceptions

- **WHEN** a module imports `from yascheduler.domain.exceptions import CloudError`
- **THEN** the class is available

#### Scenario: Import CloudError from domain package

- **WHEN** a module imports `from yascheduler.domain import CloudError`
- **THEN** the class is available and present in `yascheduler.domain.__all__`

### Requirement: CloudError is not re-exported from yascheduler.infra.cloud

The system SHALL NOT export `CloudError` from `yascheduler.infra.cloud`;
the new root remains accessible only via `yascheduler.domain`. The adapter
module's existing re-exports (`CloudAllocateError`, `CloudSetupError`) are
unchanged.

#### Scenario: infra.cloud does not re-export CloudError

- **WHEN** a module attempts `from yascheduler.infra.cloud import CloudError`
- **THEN** the import raises `ImportError`

#### Scenario: infra.cloud still re-exports the leaf cloud exceptions

- **WHEN** a module imports `from yascheduler.infra.cloud import CloudAllocateError, CloudSetupError`
- **THEN** both classes are available

### Requirement: Domain error classes are in yascheduler.domain.exceptions

The system SHALL expose all domain exception classes from
`yascheduler.domain.exceptions`.

#### Scenario: Import domain exceptions
- **WHEN** a module imports `from yascheduler.domain.exceptions import DomainError, ValidationError`
- **THEN** the classes are available
