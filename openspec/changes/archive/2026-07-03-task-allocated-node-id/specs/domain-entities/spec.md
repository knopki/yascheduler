## MODIFIED Requirements

### Requirement: NewTask pre-persistence record

The system SHALL provide a `NewTask` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** task record
(one that has not yet been assigned a database `task_id`). Fields:
`label: str`, `context: TaskContext`, `status: TaskStatus = TaskStatus.TO_DO`,
`allocated_ip: str | None = None`, `allocated_node_id: NodeId | None = None`.

`NewTask` mirrors the non-`task_id`/non-`_events` fields of `Task` with identical
defaults. It carries no identity attribute and no `_events` tuple; it is a pure
data carrier with **no lifecycle methods** (`allocate_to`/`mark_running`/
`complete`/`fail`/`reject`/`with_context`/`with_event`/`pull_events`/
`record_event` stay on `Task` — they are nonsensical on an unpersisted task). It
is converted to a `Task` only by `TaskRepository.insert` (see the `domain-ports`
capability).

`allocated_node_id` is `None` on a `NewTask` (no node is bound until
allocation). It is written by `Task.allocate_to` (see the "Task entity with
status lifecycle" requirement), not by `NewTask` construction.

#### Scenario: NewTask has no task_id attribute
- **WHEN** a NewTask is instantiated with `label="job"` and `context=ctx`
- **THEN** it has no `task_id` field; `status` defaults to `TaskStatus.TO_DO`, `allocated_ip` defaults to None, `allocated_node_id` defaults to None

#### Scenario: NewTask carries no events
- **WHEN** a NewTask is instantiated
- **THEN** it has no `_events` attribute; events are collected on the persisted `Task` after `insert`

#### Scenario: NewTask is the pre-persistence input shape
- **WHEN** a caller prepares a task record for insertion
- **THEN** it constructs a `NewTask` (no `task_id`, `allocated_node_id=None`), passes it to `TaskRepository.insert`, and receives a `Task` carrying the generated `TaskId`

#### Scenario: NewTask carries allocated_node_id for pre-bound tasks
- **WHEN** a `NewTask` is constructed with `allocated_node_id=NodeId(5)` (e.g. a pre-bound task in a future flow)
- **THEN** the field is carried through `TaskRepository.insert` to the resulting `Task.allocated_node_id`

### Requirement: Task entity with status lifecycle

The system SHALL provide a `Task` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** task record
(one that has been assigned a database `task_id`). Fields: `task_id: TaskId`
(first field, identity first), `label: str`, `context: TaskContext`,
`status: TaskStatus = TaskStatus.TO_DO`, `allocated_ip: str | None = None`,
`allocated_node_id: NodeId | None = None`,
`_events: tuple[DomainEvent, ...] = field(default=(), repr=False)`.

A `Task` SHALL always carry a `task_id: TaskId` (never `None`); it is the only
task shape that flows out of a repository. Pre-persistence task records use
`NewTask` (see the "NewTask pre-persistence record" requirement). The conversion
from `NewTask` to `Task` happens in exactly one place: `TaskRepository.insert`
(see the `domain-ports` capability).

`task_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `task_id`, `label`, `context` carry no defaults; the remaining
fields follow with their defaults. Construction at all in-repo call sites uses
keyword arguments, so the reorder is source-compatible. The `task_id=0` sentinel
becomes unrepresentable: `Task`'s `task_id: TaskId` field is required, and
`TaskId(0)` raises `ValueError` in `__post_init__`.

`allocated_node_id` is `None` for unallocated tasks (TO_DO with no node bound)
and for tasks whose node was deleted (the DB FK is `ON DELETE SET NULL`). It is
set by `allocate_to(node)` alongside `allocated_ip`; the two fields SHALL be
bound together in a single `allocate_to` call. The read path continues to use
`allocated_ip` until Surface A (`ssh-rekey-node-id`) switches the read sites to
`allocated_node_id`.

The lifecycle methods (`allocate_to`, `mark_running`, `complete`, `fail`,
`reject`, `with_context`, `with_event`, `pull_events`, `record_event`) are
unchanged in behavior except `allocate_to` (signature change below). `with_event`
constructs events with `task_id=self.task_id` (now a `TaskId` — no `.value`
extraction needed); event subclasses carry `task_id: TaskId` (see the
`domain-events` capability).

#### Scenario: Task creation
- **WHEN** a Task is instantiated with `task_id=TaskId(1)`, `label="job"`, `context=ctx`, and status TO_DO
- **THEN** fields are immutable and hashable; `allocated_node_id` defaults to None

#### Scenario: Task always carries TaskId
- **WHEN** a Task is obtained from any `TaskRepository` read or insert (`get`, `insert`, `list_by_status`, `list_by_jobs`)
- **THEN** `task.task_id` is a `TaskId` instance (never `None`, never a bare `int`)

#### Scenario: Allocate task to a node
- **WHEN** `task.allocate_to(node)` is called on a TO_DO task with a `Node` carrying `node_id=NodeId(7)` and `ip="10.0.0.1"`
- **THEN** a new Task is returned with `allocated_ip="10.0.0.1"`, `allocated_node_id=NodeId(7)`, and original status preserved

#### Scenario: Allocate already-allocated task
- **WHEN** `task.allocate_to(node)` is called on a task with `allocated_ip` already set
- **THEN** `TaskAlreadyAllocatedError` is raised (carrying `task.task_id: TaskId`); neither `allocated_ip` nor `allocated_node_id` is changed

#### Scenario: Transition to RUNNING — success
- **WHEN** `task.mark_running()` is called on a TO_DO task with `allocated_ip` set
- **THEN** a new Task is returned with `status=RUNNING`

#### Scenario: mark_running on unallocated task
- **WHEN** `task.mark_running()` is called on a task with `allocated_ip=None`
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
- **THEN** a new Task is returned with `context is new_context` and all other fields (`task_id`, `status`, `allocated_ip`, `allocated_node_id`, `_events`) preserved unchanged

#### Scenario: with_context preserves events
- **WHEN** `task.with_context(new_context)` is called on a task with prior recorded events
- **THEN** the returned Task retains the same `_events` tuple as the original

#### Scenario: with_context chains with with_event
- **WHEN** `task.with_context(new_context).with_event(TaskCreated, engine_name=new_context.engine)` is called
- **THEN** a Task is returned with the new context and the `TaskCreated` event (carrying `task_id: TaskId`) appended to `_events`

#### Scenario: with_context performs no status validation
- **WHEN** `task.with_context(new_context)` is called on a Task in any status (TO_DO, RUNNING, or DONE)
- **THEN** no error is raised and a new Task with the new context is returned regardless of status

#### Scenario: with_event passes TaskId to the event
- **WHEN** `task.with_event(TaskCreated, engine_name=ctx.engine)` is called on a Task whose `task_id` is `TaskId(7)`
- **THEN** the constructed `TaskCreated` event has `event.task_id == TaskId(7)` (the `TaskId` is passed through, not unwrapped to `int`)