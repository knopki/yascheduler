## MODIFIED Requirements

### Requirement: Task entity with status lifecycle

The system SHALL provide a `Task` domain entity as an immutable object with
fields: `task_id: int`, `label: str`, `status: TaskStatus`, `context: TaskContext`,
`allocated_ip: str | None`.

The system SHALL provide a `Task.with_context(context: TaskContext) -> Task`
method that returns a new `Task` with `context` replaced wholesale. The
method SHALL perform no field merge, no validation guard, and no status
transition — it is a pure wholesale context replacement, mirroring the
guard-free `record_event`.

#### Scenario: Task creation
- **WHEN** a Task is instantiated with status TO_DO
- **THEN** fields are immutable and hashable

#### Scenario: Allocate task to a node
- **WHEN** `task.allocate_to("10.0.0.1")` is called on a TO_DO task
- **THEN** a new Task is returned with `allocated_ip="10.0.0.1"` and original status preserved

#### Scenario: Allocate already-allocated task
- **WHEN** `task.allocate_to("10.0.0.2")` is called on a task with `allocated_ip` already set
- **THEN** `TaskAlreadyAllocatedError` is raised

#### Scenario: Transition to RUNNING — success
- **WHEN** `task.mark_running()` is called on a TO_DO task with `allocated_ip` set
- **THEN** a new Task is returned with `status=RUNNING`

#### Scenario: mark_running on unallocated task
- **WHEN** `task.mark_running()` is called on a task with `allocated_ip=None`
- **THEN** `TaskNotAllocatedError` is raised

#### Scenario: mark_running on non-TO_DO task
- **WHEN** `task.mark_running()` is called on a task with status other than TO_DO
- **THEN** `TaskNotTodoError` is raised

#### Scenario: Transition to DONE
- **WHEN** `task.complete()` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`

#### Scenario: Complete non-running task
- **WHEN** `task.complete()` is called on a non-RUNNING task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: Fail task with reason
- **WHEN** `task.fail("disk full")` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE` and `context.error="disk full"`

#### Scenario: Fail non-running task
- **WHEN** `task.fail("disk full")` is called on a non-RUNNING task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: with_context replaces context wholesale
- **WHEN** `task.with_context(new_context)` is called with a `TaskContext` differing from `task.context`
- **THEN** a new Task is returned with `context is new_context` and all other fields (status, allocated_ip, _events) preserved unchanged

#### Scenario: with_context preserves events
- **WHEN** `task.with_context(new_context)` is called on a task with prior recorded events
- **THEN** the returned Task retains the same `_events` tuple as the original

#### Scenario: with_context chains with with_event
- **WHEN** `task.with_context(new_context).with_event(TaskCreated, engine_name=new_context.engine)` is called
- **THEN** a Task is returned with the new context and the `TaskCreated` event appended to `_events`

#### Scenario: with_context performs no status validation
- **WHEN** `task.with_context(new_context)` is called on a Task in any status (TO_DO, RUNNING, or DONE)
- **THEN** no error is raised and a new Task with the new context is returned regardless of status