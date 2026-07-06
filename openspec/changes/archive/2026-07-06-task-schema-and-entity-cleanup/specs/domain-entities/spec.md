# Delta: domain-entities

## MODIFIED Requirements

### Requirement: NewTask pre-persistence record

The system SHALL provide a `NewTask` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** task record
(one that has not yet been assigned a database `task_id`). Fields:
`label: str`, `context: TaskContext`, `status: TaskStatus = TaskStatus.TO_DO`,
`allocated_node_id: NodeId | None = None`.

`NewTask` mirrors the non-`task_id`/non-`_events`/non-`created_at`/
non-`updated_at` fields of `Task` with identical defaults. It carries no
identity attribute, no `_events` tuple, and no `created_at`/`updated_at`
timestamp fields (those are DB-generated and only appear on the
post-persistence `Task`). It is a pure data carrier with **no lifecycle
methods** (`allocate_to`/`mark_running`/`complete`/`fail`/`reject`/
`with_context`/`with_event`/`pull_events`/`record_event` stay on `Task` — they
are nonsensical on an unpersisted task). It is converted to a `Task` only by
`TaskRepository.insert` (see the `domain-ports` capability).

`allocated_node_id` is `None` on a `NewTask` (no node is bound until
allocation). It is written by `Task.allocate_to` (see the "Task entity with
status lifecycle" requirement), not by `NewTask` construction.

#### Scenario: NewTask has no task_id attribute
- **WHEN** a NewTask is instantiated with `label="job"` and `context=ctx`
- **THEN** it has no `task_id` field; `status` defaults to `TaskStatus.TO_DO`, `allocated_node_id` defaults to None

#### Scenario: NewTask carries no events
- **WHEN** a NewTask is instantiated
- **THEN** it has no `_events` attribute; events are collected on the persisted `Task` after `insert`

#### Scenario: NewTask has no audit timestamps
- **WHEN** a NewTask is instantiated
- **THEN** it has no `created_at` or `updated_at` attribute; those fields are DB-generated and appear only on the post-persistence `Task`

#### Scenario: NewTask is the pre-persistence input shape
- **WHEN** a caller prepares a task record for insertion
- **THEN** it constructs a `NewTask` (no `task_id`, `allocated_node_id=None` by default) and passes it to `TaskRepository.insert`

### Requirement: Task entity with status lifecycle

The system SHALL provide a `Task` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** task record
(one that has been assigned a database `task_id`). Fields: `task_id: TaskId`
(first field, identity first), `label: str`, `context: TaskContext`,
`created_at: datetime`, `updated_at: datetime`,
`status: TaskStatus = TaskStatus.TO_DO`,
`allocated_node_id: NodeId | None = None`,
`_events: tuple[DomainEvent, ...] = field(default=(), repr=False)`.

A `Task` SHALL always carry a `task_id: TaskId` (never `None`); it is the only
task shape that flows out of a repository. Pre-persistence task records use
`NewTask` (see the "NewTask pre-persistence record" requirement). The conversion
from `NewTask` to `Task` happens in exactly one place: `TaskRepository.insert`
(see the `domain-ports` capability).

`task_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `task_id`, `label`, `context`, `created_at`, `updated_at`
carry no defaults; the remaining fields follow with their defaults. Construction
at all in-repo call sites uses keyword arguments, so the reorder is
source-compatible. The `task_id=0` sentinel becomes unrepresentable: `Task`'s
`task_id: TaskId` field is required, and `TaskId(0)` raises `ValueError` in
`__post_init__`.

`allocated_node_id` is `None` for unallocated tasks (TO_DO with no node bound)
and for tasks whose node was deleted (the DB FK is `ON DELETE SET NULL`). It is
set by `allocate_to(node)` and is the sole allocation signal on a `Task`. The
`allocated_ip` field is REMOVED; `allocate_to` and `mark_running` guard on
`allocated_node_id` (see scenarios).

`created_at` and `updated_at` are DB-generated (`DEFAULT NOW()` on the columns,
plus a `BEFORE UPDATE` trigger that sets `updated_at = NOW()`). They are read
from the row in `_row_to_task` (see the `postgres-persistence` capability) and
are NOT set by `Task` construction in application code. They appear only on
`Task`, never on `NewTask`.

The lifecycle methods (`allocate_to`, `mark_running`, `complete`, `fail`,
`reject`, `with_context`, `with_event`, `pull_events`, `record_event`) are
unchanged in behavior except `allocate_to` (signature change below). `with_event`
constructs events with `task_id=self.task_id` (now a `TaskId` — no `.value`
extraction needed); event subclasses carry `task_id: TaskId` (see the
`domain-events` capability).

#### Scenario: Task creation
- **WHEN** a Task is instantiated with `task_id=TaskId(1)`, `label="job"`, `context=ctx`, `created_at=...`, `updated_at=...`, and status TO_DO
- **THEN** fields are immutable and hashable; `allocated_node_id` defaults to None

#### Scenario: Task always carries TaskId
- **WHEN** a Task is obtained from any `TaskRepository` read or insert (`get`, `insert`, `list_by_status`, `list_by_jobs`)
- **THEN** `task.task_id` is a `TaskId` instance (never `None`, never a bare `int`)

#### Scenario: Task carries audit timestamps
- **WHEN** a Task is obtained from any `TaskRepository` read or insert
- **THEN** `task.created_at` and `task.updated_at` are `datetime` instances (DB-generated); they are never `None`

#### Scenario: Allocate task to a node
- **WHEN** `task.allocate_to(node)` is called on a TO_DO task with a `Node` carrying `node_id=NodeId(7)` and `ip="10.0.0.1"`
- **THEN** a new Task is returned with `allocated_node_id=NodeId(7)` and original status preserved; the `Task` carries no `allocated_ip` field

#### Scenario: Allocate already-allocated task
- **WHEN** `task.allocate_to(node)` is called on a task with `allocated_node_id` already set (not None)
- **THEN** `TaskAlreadyAllocatedError` is raised (carrying `task.task_id: TaskId`); `allocated_node_id` is not changed

#### Scenario: Transition to RUNNING — success
- **WHEN** `task.mark_running()` is called on a TO_DO task with `allocated_node_id` set (not None)
- **THEN** a new Task is returned with `status=RUNNING`

#### Scenario: mark_running on unallocated task
- **WHEN** `task.mark_running()` is called on a task with `allocated_node_id=None`
- **THEN** `TaskNotAllocatedError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: mark_running on non-TO_DO task
- **WHEN** `task.mark_running()` is called on a task with status other than TO_DO
- **THEN** `TaskNotTodoError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: Transition to DONE
- **WHEN** `task.complete()` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`

#### Scenario: Complete non-running task
- **WHEN** `task.complete()` is called on a non-RUNNING task
- **THEN** `TaskNotRunningError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: Fail task with reason
- **WHEN** `task.fail("disk full")` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE` and `context.error="disk full"`

#### Scenario: Fail non-running task
- **WHEN** `task.fail("disk full")` is called on a non-RUNNING task
- **THEN** `TaskNotRunningError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: with_context replaces context wholesale
- **WHEN** `task.with_context(new_context)` is called with a `TaskContext` differing from `task.context`
- **THEN** a new Task is returned with `context is new_context` and all other fields (`task_id`, `status`, `allocated_node_id`, `created_at`, `updated_at`, `_events`) preserved unchanged

#### Scenario: with_context preserves events
- **WHEN** `task.with_context(new_context)` is called on a task with prior recorded events
- **THEN** the returned Task retains the same `_events` tuple as the original

#### Scenario: with_context chains with with_event
- **WHEN** `task.with_context(c).with_event(e)` is called
- **THEN** the returned Task has `context=c` and `_events` ending in `e`