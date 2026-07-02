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
`TaskNotRunningError`. Each SHALL take `task_id: TaskId` (was `int`); the
`f"task {task_id} ..."` message renders the bare integer via `TaskId.__str__`,
so the message text is unchanged in appearance.

#### Scenario: TaskAlreadyAllocatedError carries TaskId
- **WHEN** `TaskAlreadyAllocatedError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskNotAllocatedError carries TaskId
- **WHEN** `TaskNotAllocatedError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskNotTodoError carries TaskId
- **WHEN** `TaskNotTodoError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskNotRunningError carries TaskId
- **WHEN** `TaskNotRunningError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskError messages render bare integer
- **WHEN** `str(TaskAlreadyAllocatedError(TaskId(42)))` is evaluated
- **THEN** the result is `"task 42 is already allocated to a node"` (NOT `"task TaskId(value=42) ..."`)

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

### Requirement: UnitOfWorkNotInitializedError exception class

The system SHALL provide a `UnitOfWorkNotInitializedError` exception class in
`yascheduler.infra.persistence.exceptions` that inherits from `RuntimeError`.
It SHALL be raised when `PostgresUnitOfWork` API methods are called without
entering the `async with` context. It is a persistence-adapter exception (a
sibling of `TaskRowNotFoundError`), not a domain exception, and is grouped here
with the project's exception hierarchy for discoverability.

#### Scenario: Accessing tasks property without entering context
- **WHEN** `uow.tasks` is accessed on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Accessing nodes property without entering context
- **WHEN** `uow.nodes` is accessed on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Calling commit without entering context
- **WHEN** `uow.commit()` is called on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Calling rollback without entering context
- **WHEN** `uow.rollback()` is called on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Backward compatibility with RuntimeError catch
- **WHEN** `UnitOfWorkNotInitializedError` is raised
- **THEN** `isinstance(exc, RuntimeError)` returns `True`

### Requirement: TaskRowNotFoundError exception class

The system SHALL provide a `TaskRowNotFoundError` exception class in
`yascheduler.infra.persistence.exceptions` that inherits from `RuntimeError`.
It SHALL be raised by `PostgresTaskRepository.save()` and
`PostgresTaskRepository.update_status()` when an `UPDATE ... WHERE task_id`
statement affects 0 rows (the targeted `task_id` does not exist in
`yascheduler_tasks`). It is a programming-error / contract precondition
violation signaling that the caller violated the repository's row-existence
precondition; it is NOT a domain exception and SHALL NOT be caught for
recovery logic. It is a sibling of `UnitOfWorkNotInitializedError`.

`TaskRowNotFoundError` SHALL take `task_id: TaskId` (was `int`); the
`f"task row not found for task_id={task_id}"` message renders the bare integer
via `TaskId.__str__`.

#### Scenario: save raises on non-existent task_id
- **WHEN** `save(task)` is called with a `task.task_id` (a `TaskId`) that does not exist in `yascheduler_tasks`
- **THEN** `TaskRowNotFoundError` is raised and the task is NOT appended to the UoW's `_saved_tasks` list

#### Scenario: update_status raises on non-existent task_id
- **WHEN** `update_status(task_id, status)` is called with a `task_id: TaskId` that does not exist in `yascheduler_tasks`
- **THEN** `TaskRowNotFoundError` is raised (carrying the `TaskId`)

#### Scenario: save does not append to _saved_tasks on raise
- **WHEN** `save(task)` raises `TaskRowNotFoundError` because the target row is absent
- **THEN** the `task` argument is NOT appended to the UoW's `_saved_tasks` list, so `publish_events` will not dispatch events for a task whose DB row was never updated

#### Scenario: Backward compatibility with RuntimeError catch
- **WHEN** `TaskRowNotFoundError` is raised
- **THEN** `isinstance(exc, RuntimeError)` returns `True`

#### Scenario: Constructor carries TaskId
- **WHEN** `TaskRowNotFoundError(TaskId(42))` is constructed
- **THEN** the exception instance has a `task_id` attribute holding the `TaskId` that was not found, and `str(e)` contains `"42"` (rendered via `TaskId.__str__`)

### Requirement: Domain error classes are in yascheduler.domain.exceptions

The system SHALL expose all domain exception classes from
`yascheduler.domain.exceptions`.

#### Scenario: Import domain exceptions
- **WHEN** a module imports `from yascheduler.domain.exceptions import DomainError, ValidationError`
- **THEN** the classes are available
