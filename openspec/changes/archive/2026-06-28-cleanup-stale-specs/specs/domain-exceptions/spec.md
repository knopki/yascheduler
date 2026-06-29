## ADDED Requirements

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

#### Scenario: save raises on non-existent task_id
- **WHEN** `save(task)` is called with a `task.task_id` that does not exist in `yascheduler_tasks`
- **THEN** `TaskRowNotFoundError` is raised and the task is NOT appended to the UoW's `_saved_tasks` list

#### Scenario: update_status raises on non-existent task_id
- **WHEN** `update_status(task_id, status)` is called with a `task_id` that does not exist in `yascheduler_tasks`
- **THEN** `TaskRowNotFoundError` is raised

#### Scenario: save does not append to _saved_tasks on raise
- **WHEN** `save(task)` raises `TaskRowNotFoundError` because the target row is absent
- **THEN** the `task` argument is NOT appended to the UoW's `_saved_tasks` list, so `publish_events` will not dispatch events for a task whose DB row was never updated

#### Scenario: Backward compatibility with RuntimeError catch
- **WHEN** `TaskRowNotFoundError` is raised
- **THEN** `isinstance(exc, RuntimeError)` returns `True`

#### Scenario: Constructor carries task_id
- **WHEN** `TaskRowNotFoundError(task_id)` is constructed
- **THEN** the exception instance has a `task_id` attribute holding the int that was not found

## MODIFIED Requirements

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