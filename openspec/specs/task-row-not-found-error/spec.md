# task-row-not-found-error

## Purpose

Persistence-adapter exception raised when a repository UPDATE targets a non-existent row — a programming-error / contract precondition violation, not a domain exception.

## Requirements

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