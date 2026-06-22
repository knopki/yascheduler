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
`TaskAlreadyAllocatedError`, `TaskNotAllocatedError`, `TaskNotTodoError`,
`TaskNotRunningError`.

#### Scenario: TaskAlreadyAllocatedError carries task_id
- **WHEN** `TaskAlreadyAllocatedError(42)` is raised
- **THEN** `e.task_id == 42`

#### Scenario: TaskNotAllocatedError carries task_id
- **WHEN** `TaskNotAllocatedError(42)` is raised
- **THEN** `e.task_id == 42`

#### Scenario: TaskNotTodoError carries task_id
- **WHEN** `TaskNotTodoError(42)` is raised
- **THEN** `e.task_id == 42`

#### Scenario: TaskNotRunningError carries task_id
- **WHEN** `TaskNotRunningError(42)` is raised
- **THEN** `e.task_id == 42`

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
SHALL NOT be a subclass of `CloudError`.

#### Scenario: NoCompatibleNodeError carries task_id and platforms
- **WHEN** `NoCompatibleNodeError(42, ["linux", "debian-12"])` is raised
- **THEN** `e.task_id == 42` and `e.platforms == ["linux", "debian-12"]`

#### Scenario: CloudCapacityExhaustedError carries task_id
- **WHEN** `CloudCapacityExhaustedError(42)` is raised
- **THEN** `e.task_id == 42`

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

### Requirement: CloudError is not re-exported from yascheduler.adapters.cloud

The system SHALL NOT export `CloudError` from `yascheduler.adapters.cloud`;
the new root remains accessible only via `yascheduler.domain`. The adapter
module's existing re-exports (`CloudAllocateError`, `CloudSetupError`) are
unchanged.

#### Scenario: adapters.cloud does not re-export CloudError

- **WHEN** a module attempts `from yascheduler.adapters.cloud import CloudError`
- **THEN** the import raises `ImportError`

#### Scenario: adapters.cloud still re-exports the leaf cloud exceptions

- **WHEN** a module imports `from yascheduler.adapters.cloud import CloudAllocateError, CloudSetupError`
- **THEN** both classes are available

### Requirement: Domain error classes are in yascheduler.domain.exceptions

The system SHALL expose all domain exception classes from
`yascheduler.domain.exceptions`.

#### Scenario: Import domain exceptions
- **WHEN** a module imports `from yascheduler.domain.exceptions import DomainError, ValidationError`
- **THEN** the classes are available
