## ADDED Requirements

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
`TaskAlreadyAllocatedError` and `TaskNotAllocatedError`.

#### Scenario: TaskAlreadyAllocatedError carries task_id
- **WHEN** `TaskAlreadyAllocatedError(42)` is raised
- **THEN** `e.task_id == 42`

#### Scenario: TaskNotAllocatedError carries task_id
- **WHEN** `TaskNotAllocatedError(42)` is raised
- **THEN** `e.task_id == 42`

### Requirement: MachineBusyError

The system SHALL provide `MachineBusyError(DomainError)` for operations
attempted on a busy machine.

#### Scenario: MachineBusyError carries IP
- **WHEN** `MachineBusyError("10.0.0.1")` is raised
- **THEN** the exception message contains the IP address

### Requirement: SchedulingError hierarchy

The system SHALL provide `SchedulingError(DomainError)` with subclasses:
`NoCompatibleNodeError` and `CloudCapacityExhaustedError`.

#### Scenario: NoCompatibleNodeError carries task_id and platforms
- **WHEN** `NoCompatibleNodeError(42, ["linux", "debian-12"])` is raised
- **THEN** `e.task_id == 42` and `e.platforms == ["linux", "debian-12"]`

#### Scenario: CloudCapacityExhaustedError carries task_id
- **WHEN** `CloudCapacityExhaustedError(42)` is raised
- **THEN** `e.task_id == 42`

### Requirement: Domain error classes are in yascheduler.domain.exceptions

The system SHALL expose all domain exception classes from
`yascheduler.domain.exceptions`.

#### Scenario: Import domain exceptions
- **WHEN** a module imports `from yascheduler.domain.exceptions import DomainError, ValidationError`
- **THEN** the classes are available
