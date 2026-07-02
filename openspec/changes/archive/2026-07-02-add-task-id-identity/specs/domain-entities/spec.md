## ADDED Requirements

### Requirement: TaskId value object

The system SHALL provide a `TaskId` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/model.py` wrapping a single
field `value: int`. `TaskId` SHALL:

- validate in `__post_init__` that `value > 0`, raising `ValueError` otherwise
  (`yascheduler_tasks.task_id SERIAL PRIMARY KEY` starts at 1, so a non-positive
  value indicates a bug);
- define `__str__` returning `str(self.value)` so CLI rendering and logging
  produce the bare integer string (not the dataclass `repr`
  `TaskId(value=5)`);
- be hashable (frozen dataclass) and usable as a dict key;
- NOT be equal to a bare `int` — `TaskId(5) == 5` is `False`. This is the
  type-safety point of a dedicated value object: callers cannot accidentally
  mix a `TaskId` with an unrelated `int`.

At external boundaries the wrapped `.value` SHALL be unwrapped explicitly:
pg8000 SQL parameters pass `task_id.value` (pg8000 cannot adapt a dataclass);
JSON serialization emits `task_id.value`; `dataclasses.asdict` over a
`WebhookPayload` carrying `task_id` emits `task_id.value` (else `asdict` recurses
into the `TaskId` dataclass and produces `{"task_id": {"value": 42}, ...}` — a
wire-shape break); DB-read mapping wraps `TaskId(int(row["task_id"]))`.

`TaskId` SHALL NOT be `typing.NewType('TaskId', int)` (erased to `int` at
runtime, no validation, no methods) and SHALL NOT subclass `int` (defeats
value-object ergonomics and the explicit "frozen dataclass with value: int"
design). It is the Task-side analog of `NodeId`.

#### Scenario: TaskId validates positive
- **WHEN** `TaskId(0)` or `TaskId(-3)` is constructed
- **THEN** `ValueError` is raised

#### Scenario: TaskId str renders the bare integer
- **WHEN** `str(TaskId(5))` or `f"{TaskId(5)}"` is evaluated
- **THEN** the result is `"5"` (NOT `"TaskId(value=5)"`)

#### Scenario: TaskId is not equal to int
- **WHEN** `TaskId(5) == 5` is evaluated
- **THEN** the result is `False`

#### Scenario: TaskId is hashable
- **WHEN** `hash(TaskId(5))` is evaluated or `TaskId(5)` is used as a dict key
- **THEN** it succeeds (frozen dataclass is hashable)

#### Scenario: TaskId wraps DB-generated serial on read
- **WHEN** a row with `task_id = 7` is read from `yascheduler_tasks`
- **THEN** `_row_to_task` constructs `TaskId(int(row["task_id"]))` → `TaskId(7)`

### Requirement: NewTask pre-persistence record

The system SHALL provide a `NewTask` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** task record
(one that has not yet been assigned a database `task_id`). Fields:
`label: str`, `context: TaskContext`, `status: TaskStatus = TaskStatus.TO_DO`,
`allocated_ip: str | None = None`.

`NewTask` mirrors the non-`task_id`/non-`_events` fields of `Task` with identical
defaults. It carries no identity attribute and no `_events` tuple; it is a pure
data carrier with **no lifecycle methods** (`allocate_to`/`mark_running`/
`complete`/`fail`/`reject`/`with_context`/`with_event`/`pull_events`/
`record_event` stay on `Task` — they are nonsensical on an unpersisted task). It
is converted to a `Task` only by `TaskRepository.insert` (see the `domain-ports`
capability).

#### Scenario: NewTask has no task_id attribute
- **WHEN** a NewTask is instantiated with `label="job"` and `context=ctx`
- **THEN** it has no `task_id` field; `status` defaults to `TaskStatus.TO_DO`, `allocated_ip` defaults to None

#### Scenario: NewTask carries no events
- **WHEN** a NewTask is instantiated
- **THEN** it has no `_events` attribute; events are collected on the persisted `Task` after `insert`

#### Scenario: NewTask is the pre-persistence input shape
- **WHEN** a caller prepares a task record for insertion
- **THEN** it constructs a `NewTask` (no `task_id`), passes it to `TaskRepository.insert`, and receives a `Task` carrying the generated `TaskId`

## MODIFIED Requirements

### Requirement: Task entity with status lifecycle

The system SHALL provide a `Task` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** task record
(one that has been assigned a database `task_id`). Fields: `task_id: TaskId`
(first field, identity first), `label: str`, `context: TaskContext`,
`status: TaskStatus = TaskStatus.TO_DO`, `allocated_ip: str | None = None`,
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

The lifecycle methods (`allocate_to`, `mark_running`, `complete`, `fail`,
`reject`, `with_context`, `with_event`, `pull_events`, `record_event`) are
unchanged in behavior. `with_event` constructs events with
`task_id=self.task_id` (now a `TaskId` — no `.value` extraction needed); event
subclasses carry `task_id: TaskId` (see the `domain-events` capability).

#### Scenario: Task creation
- **WHEN** a Task is instantiated with `task_id=TaskId(1)`, `label="job"`, `context=ctx`, and status TO_DO
- **THEN** fields are immutable and hashable

#### Scenario: Task always carries TaskId
- **WHEN** a Task is obtained from any `TaskRepository` read or insert (`get`, `insert`, `list_by_status`, `list_by_jobs`)
- **THEN** `task.task_id` is a `TaskId` instance (never `None`, never a bare `int`)

#### Scenario: Allocate task to a node
- **WHEN** `task.allocate_to("10.0.0.1")` is called on a TO_DO task
- **THEN** a new Task is returned with `allocated_ip="10.0.0.1"` and original status preserved

#### Scenario: Allocate already-allocated task
- **WHEN** `task.allocate_to("10.0.0.2")` is called on a task with `allocated_ip` already set
- **THEN** `TaskAlreadyAllocatedError` is raised (carrying `task.task_id: TaskId`)

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
- **THEN** a new Task is returned with `context is new_context` and all other fields (`task_id`, `status`, `allocated_ip`, `_events`) preserved unchanged

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

### Requirement: Domain entities are importable from yascheduler.domain.model

The system SHALL expose all domain entities from `yascheduler.domain.model`.

#### Scenario: Import entities
- **WHEN** `from yascheduler.domain.model import Task, NewTask, TaskId, Node, ConnectedMachine, TaskContext, Engine, TaskStatus, MachineState, ProcessResult`
- **THEN** all symbols are available (including the new `NewTask` and `TaskId`)