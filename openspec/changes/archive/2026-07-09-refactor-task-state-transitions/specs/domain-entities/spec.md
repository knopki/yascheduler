## MODIFIED Requirements

### Requirement: Task entity with status lifecycle

The system SHALL provide a `Task` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** task record
(one that has been assigned a database `task_id`). Fields: `task_id: TaskId`
(first field, identity first), `label: str`, `engine: str`,
`remote_folder: str | None`, `local_folder: str | None`,
`webhook_url: str | None`, `webhook_custom_params: dict[str, object]`,
`error: str | None`, `extra: dict[str, object]`,
`created_at: datetime`, `updated_at: datetime`,
`status: TaskStatus = TaskStatus.TO_DO`,
`allocated_node_id: NodeId | None = None`,
`events: tuple[DomainEvent, ...] = field(default=(), repr=True)`.

A `Task` SHALL always carry a `task_id: TaskId` (never `None`); it is the only
task shape that flows out of a repository. Pre-persistence task records use
`NewTask` (see the "NewTask pre-persistence record" requirement). The conversion
from `NewTask` to `Task` happens in exactly one place: `TaskRepository.insert`
(see the `domain-ports` capability), which calls `materialize_task` (see the
"materialize_task free function" requirement) to attach `TaskCreated` to
`events`.

`task_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `task_id`, `label`, `engine`, `remote_folder`, `local_folder`,
`webhook_url`, `webhook_custom_params`, `error`, `extra`, `created_at`,
`updated_at` carry no defaults; the remaining fields (`status`,
`allocated_node_id`, `events`) follow with their defaults. Construction at all
in-repo call sites uses keyword arguments, so the reorder is source-compatible.
The `task_id=0` sentinel is unrepresentable: `Task`'s `task_id: TaskId` field is
required, and `TaskId(0)` raises `ValueError` in `__post_init__`.

`allocated_node_id` is `None` for unallocated tasks (TO_DO with no node bound)
and for tasks whose node was deleted (the DB FK is `ON DELETE SET NULL`). It is
set only by `run(node_id, remote_folder)` (the `TO_DO→RUNNING` transition).
`allocated_ip` is removed from `Task`; the node transport address is obtained
from the resolved `Node.ip` via `nodes_by_id` (see the `cli` capability).

The lifecycle SHALL be expressed as five atomic transition methods
(`run`, `reject`, `complete`, `fail`, `abandon`) that each validate the source
state, set all fields that change, construct and append the matching
`DomainEvent` to `events`, and return a new `Task` via `replace`. No
intermediate-state-producing mutators (`allocate_to`, `mark_running`,
`with_remote_folder`, `with_download_results`) SHALL exist. No event primitives
(`record_event`, `with_event`, `pull_events`) SHALL exist on `Task`; events are
emitted inline by the transitions and read directly off the public `events`
field by the UoW.

`events` SHALL be a public field (no leading underscore) with `repr=True`. The
UoW reads it directly in `collect_events` (see the `domain-events-and-dispatch`
capability); no `pull_events` helper exists.

`remote_folder` is `None` on a freshly-inserted TO_DO task; it is set by `run`
when the task transitions to RUNNING. `local_folder` is `None` until `complete`
or `fail` sets it from the download results. `error` is `None` until `reject`,
`fail`, or `abandon` sets it.

#### Scenario: run transitions TO_DO to RUNNING and emits TaskAllocated
- **WHEN** `task.run(node_id=NodeId(7), remote_folder="/remote/20240101_000000_7")` is called on a TO_DO task with `allocated_node_id=None`
- **THEN** a new Task is returned with `status=RUNNING`, `allocated_node_id=NodeId(7)`, `remote_folder="/remote/20240101_000000_7"`, and `events` containing one `TaskAllocated(node_id=NodeId(7), engine_name=task.engine)`

#### Scenario: run raises TaskNotTodoError on non-TO_DO
- **WHEN** `task.run(node_id=NodeId(7), remote_folder="/r")` is called on a RUNNING task
- **THEN** `TaskNotTodoError(task.task_id)` is raised and `events` is unchanged

#### Scenario: reject transitions TO_DO to DONE with error and emits TaskFailed
- **WHEN** `task.reject("unsupported engine")` is called on a TO_DO task
- **THEN** a new Task is returned with `status=DONE`, `error="unsupported engine"`, and `events` containing one `TaskFailed(reason="unsupported engine")`

#### Scenario: reject raises TaskNotTodoError on non-TO_DO
- **WHEN** `task.reject("reason")` is called on a RUNNING task
- **THEN** `TaskNotTodoError(task.task_id)` is raised

#### Scenario: complete transitions RUNNING to DONE with folders and emits TaskCompleted
- **WHEN** `task.complete(local_folder="/local/out", remote_folder="/remote/out")` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`, `local_folder="/local/out"`, `remote_folder="/remote/out"`, `error` unchanged (None on the success path), and `events` containing one `TaskCompleted(local_folder="/local/out")`

#### Scenario: complete raises TaskNotRunningError on non-RUNNING
- **WHEN** `task.complete(local_folder="/l", remote_folder="/r")` is called on a TO_DO task
- **THEN** `TaskNotRunningError(task.task_id)` is raised

#### Scenario: fail transitions RUNNING to DONE with error and partial folders and emits TaskFailed
- **WHEN** `task.fail("disk full", local_folder="/local/partial", remote_folder="/remote/partial")` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`, `error="disk full"`, `local_folder="/local/partial"`, `remote_folder="/remote/partial"`, and `events` containing one `TaskFailed(reason="disk full")`

#### Scenario: fail raises TaskNotRunningError on non-RUNNING
- **WHEN** `task.fail("reason", local_folder="/l", remote_folder="/r")` is called on a TO_DO task
- **THEN** `TaskNotRunningError(task.task_id)` is raised

#### Scenario: abandon transitions RUNNING to DONE with error and emits TaskAbandoned when node_id is not None
- **WHEN** `task.abandon(node_id=NodeId(7))` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`, `error="node is gone"`, folders unchanged, and `events` containing one `TaskAbandoned(node_id=NodeId(7))`

#### Scenario: abandon emits no event when node_id is None (double-abandon edge)
- **WHEN** `task.abandon(node_id=None)` is called on a RUNNING task whose `allocated_node_id` was nulled by an FK cascade
- **THEN** a new Task is returned with `status=DONE`, `error="node is gone"`, folders unchanged, and `events` empty (no `TaskAbandoned` emitted — there is no node to abandon)

#### Scenario: abandon raises TaskNotRunningError on non-RUNNING
- **WHEN** `task.abandon(node_id=NodeId(7))` is called on a TO_DO task
- **THEN** `TaskNotRunningError(task.task_id)` is raised

#### Scenario: events field is public and shown in repr
- **WHEN** `repr(task)` is evaluated on a Task with one recorded event
- **THEN** the `events=(...)` field appears in the repr output (was hidden when the field was `_events` with `repr=False`)

## ADDED Requirements

### Requirement: materialize_task free function

The system SHALL provide a `materialize_task(task: Task) -> Task` free function
in `yascheduler/domain/model.py` that returns a new `Task` with a `TaskCreated`
event appended to `events`. It SHALL read `task_id`, `webhook_url`,
`webhook_custom_params`, and `engine` off the freshly-inserted `Task` (produced
by `_row_to_task`) and construct
`TaskCreated(task_id=task.task_id, webhook_url=task.webhook_url,
webhook_custom_params=task.webhook_custom_params, engine_name=task.engine)`,
then return `replace(task, events=(event,))`.

`materialize_task` is the sole `TaskCreated` emission site. It is called by
`PostgresTaskRepository.insert` (see the `postgres-persistence` capability) on
the `_row_to_task` output. It SHALL NOT be called from use cases or the
orchestrator. It is a domain-layer function; the infrastructure layer SHALL NOT
import `TaskCreated` directly.

`replace` SHALL be used inside `materialize_task` and inside `Task` transition
methods only — not at use-case or orchestrator call sites.

#### Scenario: materialize_task attaches TaskCreated
- **WHEN** `materialize_task(task)` is called on a freshly-inserted Task with `task_id=TaskId(42)`, `engine="fleur"`, `webhook_url="https://..."`, `webhook_custom_params={}`, `events=()`
- **THEN** a new Task is returned with `events` containing one `TaskCreated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, engine_name="fleur")`

#### Scenario: materialize_task preserves all other fields
- **WHEN** `materialize_task(task)` is called on a Task
- **THEN** the returned Task has the same `task_id`, `label`, `engine`, `remote_folder`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`, `created_at`, `updated_at`, `status`, `allocated_node_id` as the input

## REMOVED Requirements

### Requirement: Task.with_remote_folder
**Reason**: `remote_folder` is now set by the `run` transition at allocate time, not by a post-insert copy-with at submit time. The method was a field setter that produced an intermediate state.
**Migration**: Call `task.run(node_id, remote_folder)` to set `remote_folder` and transition to RUNNING in one atomic call. The DB column is NULL for TO_DO tasks (already valid per the schema DEFAULT NULL).

### Requirement: Task.with_download_results
**Reason**: `local_folder` and `remote_folder` are now set by the `complete` and `fail` transitions as keyword-only params, absorbing the copy-with into the terminal transition. The method was a field setter that produced an intermediate state.
**Migration**: Call `task.complete(local_folder=..., remote_folder=...)` or `task.fail(reason, local_folder=..., remote_folder=...)` to set both folders and transition to DONE in one atomic call.