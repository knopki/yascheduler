## MODIFIED Requirements

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