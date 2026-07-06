# Spec Delta: domain-entities

## MODIFIED Requirements

### Requirement: NewTask pre-persistence record

The system SHALL provide a `NewTask` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** task record
(one that has not yet been assigned a database `task_id`). Fields:
`engine: str`, `label: str = ""`, `local_folder: str | None = None`,
`webhook_url: str | None = None`,
`webhook_custom_params: dict[str, object] = field(default_factory=dict)`,
`extra: dict[str, object] = field(default_factory=dict)`.

`NewTask` carries no identity attribute, no `_events` tuple, no
`created_at`/`updated_at` timestamps, no `status`, no `allocated_node_id`, no
`remote_folder`, and no `error`. The DB supplies `status` (DEFAULT 'TO_DO'),
`allocated_node_id` (DEFAULT NULL), `created_at`/`updated_at` (DEFAULT NOW()) on
insert; `remote_folder` is assigned post-insert by `Task.with_remote_folder`;
`error` is only ever set by `Task.fail` / `Task.reject` on a post-persistence
`Task`. It is a pure data carrier with **no lifecycle methods**
(`allocate_to`/`mark_running`/`complete`/`fail`/`reject`/
`with_remote_folder`/`with_download_results`/`with_event`/`pull_events`/
`record_event` stay on `Task` — `NewTask` is converted to a `Task` only by
`TaskRepository.insert` (see the `domain-ports` capability)).

`allocated_node_id` is bound by `Task.allocate_to(node)` after insert, not by
`NewTask` construction. A task that must be pre-bound to a node (e.g. the
never-connected-node-abandon integration test) is inserted as an unbound
`NewTask`, then `task.allocate_to(node)` + `repo.save(task)` bind it.

`NewTask` carries NO `remote_folder` and NO `error` fields: `remote_folder` is
assigned post-insert by `Task.with_remote_folder` (the remote path is constructed
from the generated `task_id`); `error` is only ever set by `Task.fail` /
`Task.reject` on a post-persistence `Task`. The two fields appear on `Task` only.

#### Scenario: NewTask has no task_id attribute
- **WHEN** a NewTask is instantiated with `label="job"` and `engine="cp2k"`
- **THEN** it has no `task_id` field; no `status` field; no `allocated_node_id` field; `local_folder`/`webhook_url` default to None, `webhook_custom_params`/`extra` default to `{}`

#### Scenario: NewTask carries no events
- **WHEN** a NewTask is instantiated
- **THEN** it has no `_events` attribute; events are collected on the persisted `Task` after `insert`

#### Scenario: NewTask has no audit timestamps
- **WHEN** a NewTask is instantiated
- **THEN** it has no `created_at` or `updated_at` attribute; those fields are DB-generated and appear only on the post-persistence `Task`

#### Scenario: NewTask has no remote_folder or error
- **WHEN** a NewTask is instantiated with `label="job"`, `engine="cp2k"`
- **THEN** it has no `remote_folder` attribute and no `error` attribute; those fields appear only on the post-persistence `Task`

#### Scenario: NewTask is the pre-persistence input shape
- **WHEN** a caller prepares a task record for insertion
- **THEN** it constructs a `NewTask` (no `task_id`, no `status`, no `allocated_node_id`), passes it to `TaskRepository.insert`, and receives a `Task` carrying the generated `TaskId` with DB-defaulted `status=TO_DO` and `allocated_node_id=None`

#### Scenario: Pre-bound task is inserted then allocate_to + save
- **WHEN** a task must be bound to a node before allocation (e.g. a never-connected-node scenario)
- **THEN** the caller inserts an unbound `NewTask`, calls `task = task.allocate_to(node)`, then `repo.save(task)` to persist `allocated_node_id` (NewTask carries no `allocated_node_id`)

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
`_events: tuple[DomainEvent, ...] = field(default=(), repr=False)`.

A `Task` SHALL always carry a `task_id: TaskId` (never `None`); it is the only
task shape that flows out of a repository. Pre-persistence task records use
`NewTask` (see the "NewTask pre-persistence record" requirement). The conversion
from `NewTask` to `Task` happens in exactly one place: `TaskRepository.insert`
(see the `domain-ports` capability).

`task_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `task_id`, `label`, `engine`, `remote_folder`, `local_folder`,
`webhook_url`, `webhook_custom_params`, `error`, `extra`, `created_at`,
`updated_at` carry no defaults; the remaining fields (`status`,
`allocated_node_id`, `_events`) follow with their defaults. Construction at all
in-repo call sites uses keyword arguments, so the reorder is source-compatible.
The `task_id=0` sentinel is unrepresentable: `Task`'s `task_id: TaskId` field is
required, and `TaskId(0)` raises `ValueError` in `__post_init__`.

`allocated_node_id` is `None` for unallocated tasks (TO_DO with no node bound)
and for tasks whose node was deleted (the DB FK is `ON DELETE SET NULL`). It is
set by `allocate_to(node)`. `allocated_ip` is removed from `Task`; the node
transport address is obtained from the resolved `Node.ip` via `nodes_by_id`
(see the `cli` capability).

The lifecycle methods (`allocate_to`, `mark_running`, `complete`, `fail`,
`reject`, `with_remote_folder`, `with_download_results`, `with_event`,
`pull_events`, `record_event`) operate on the typed fields directly (no
`TaskContext` indirection). `with_event` constructs events with
`task_id=self.task_id` (a `TaskId` — no `.value` extraction needed) and reads
`webhook_url=self.webhook_url`, `webhook_custom_params=self.webhook_custom_params`
(was `self.context.X`); event subclasses carry `task_id: TaskId` (see the
`domain-events` capability).

#### Scenario: Task creation
- **WHEN** a Task is instantiated with `task_id=TaskId(1)`, `label="job"`, `engine="cp2k"`, and status TO_DO
- **THEN** fields are immutable and hashable; `allocated_node_id` defaults to None, `remote_folder`/`local_folder`/`webhook_url`/`error` are the provided values (None unless set), `webhook_custom_params`/`extra` are the provided dicts

#### Scenario: Task always carries TaskId
- **WHEN** a Task is obtained from any `TaskRepository` read or insert (`get`, `insert`, `list_by_status`, `list_by_jobs`)
- **THEN** `task.task_id` is a `TaskId` instance (never `None`, never a bare `int`)

#### Scenario: Allocate task to a node
- **WHEN** `task.allocate_to(node)` is called on a TO_DO task with a `Node` carrying `node_id=NodeId(7)`
- **THEN** a new Task is returned with `allocated_node_id=NodeId(7)` and original status preserved

#### Scenario: Allocate already-allocated task
- **WHEN** `task.allocate_to(node)` is called on a task with `allocated_node_id` already set
- **THEN** `TaskAlreadyAllocatedError` is raised (carrying `task.task_id: TaskId`); `allocated_node_id` is not changed

#### Scenario: Transition to RUNNING — success
- **WHEN** `task.mark_running()` is called on a TO_DO task with `allocated_node_id` set
- **THEN** a new Task is returned with `status=RUNNING`

#### Scenario: mark_running on unallocated task
- **WHEN** `task.mark_running()` is called on a task with `allocated_node_id=None`
- **THEN** `TaskNotAllocatedError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: mark_running on non-TO_DO task
- **WHEN** `task.mark_running()` is called on a task with status other than TO_DO
- **THEN** `TaskNotTodoError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: Transition to DONE
- **WHEN** `task.complete()` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`; `error` is NOT touched (remains whatever it was — `None` on the success path)

#### Scenario: Complete non-running task
- **WHEN** `task.complete()` is called on a non-RUNNING task
- **THEN** `TaskNotRunningError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: Fail task with reason
- **WHEN** `task.fail("disk full")` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE` and `error="disk full"` (the nested `context.replace(error=reason)` is replaced by a direct `replace(self, status=DONE, error=reason)`)

#### Scenario: Fail non-running task
- **WHEN** `task.fail("disk full")` is called on a non-RUNNING task
- **THEN** `TaskNotRunningError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: Reject task with reason
- **WHEN** `task.reject("unsupported engine")` is called on a TO_DO task
- **THEN** a new Task is returned with `status=DONE` and `error="unsupported engine"` (the nested `context.replace(error=reason)` is replaced by a direct `replace(self, status=DONE, error=reason)`)

#### Scenario: Reject non-todo task
- **WHEN** `task.reject("unsupported engine")` is called on a non-TO_DO task
- **THEN** `TaskNotTodoError` is raised (carrying `task.task_id: TaskId`)

#### Scenario: with_event passes TaskId to the event
- **WHEN** `task.with_event(TaskCreated, engine_name=task.engine)` is called on a Task whose `task_id` is `TaskId(7)`
- **THEN** the constructed `TaskCreated` event has `event.task_id == TaskId(7)` (the `TaskId` is passed through, not unwrapped to `int`) and `event.webhook_url == task.webhook_url`, `event.webhook_custom_params == task.webhook_custom_params` (read from the typed fields, not from a nested context)

### Requirement: Domain entities are importable from yascheduler.domain.model

The system SHALL expose all domain entities from `yascheduler.domain.model`.

#### Scenario: Import entities
- **WHEN** `from yascheduler.domain.model import Task, NewTask, TaskId, Node, NewNode, NodeId, ConnectedMachine, Engine, TaskStatus, MachineState, ProcessResult`
- **THEN** all symbols are available (including `NewTask` and `TaskId`); `TaskContext` and `TaskContextOverrides` are NO LONGER importable (removed)

## ADDED Requirements

### Requirement: Task.with_remote_folder

The system SHALL provide a `Task.with_remote_folder(self, remote_folder: str) -> Task`
method that returns a new `Task` with `remote_folder` set and all other fields
preserved. The method SHALL perform no status validation and no side effect — it is
a pure copy-with used at submit time, after `TaskRepository.insert` generates the
`task_id` and the remote path is constructed from it.

#### Scenario: with_remote_folder sets the field
- **WHEN** `task.with_remote_folder("/remote/20240101_000000_7")` is called on a Task with `remote_folder=None`
- **THEN** a new Task is returned with `remote_folder="/remote/20240101_000000_7"` and all other fields (`task_id`, `label`, `engine`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`, `status`, `allocated_node_id`, `_events`) preserved unchanged

#### Scenario: with_remote_folder performs no status validation
- **WHEN** `task.with_remote_folder("/r")` is called on a Task in any status (TO_DO, RUNNING, or DONE)
- **THEN** no error is raised and a new Task with the new `remote_folder` is returned regardless of status

### Requirement: Task.with_download_results

The system SHALL provide a
`Task.with_download_results(self, *, local_folder: str, remote_folder: str) -> Task`
method (keyword-only) that returns a new `Task` with `local_folder` and
`remote_folder` set and all other fields preserved. The method SHALL NOT update
`extra`: after the typed extraction, `extra` carries only input-file payloads and
the download path never touches them (the legacy `extra_updates` merge block in
`consume_task._decide_finalisation` was always a no-op — `meta_add` from
`download_outputs` only ever contains `remote_folder`/`local_folder`, and `error`
is appended by `_decide_finalisation` itself; none of those keys ever reached the
`extra_updates` comprehension). The method SHALL perform no status validation and
no side effect — it is a pure copy-with used at consume time, after
`download_outputs` returns.

The call site MAY pass values equal to the existing field values (it falls back to
the existing field when `meta_dict.get(...)` returns falsy). The method expresses
intent (this is the post-download update), not a delta — calling with the same
values is a no-op-equivalent and is not an error.

#### Scenario: with_download_results sets both fields
- **WHEN** `task.with_download_results(local_folder="/local/out", remote_folder="/remote/out")` is called on a Task with `local_folder=None`, `remote_folder=None`
- **THEN** a new Task is returned with `local_folder="/local/out"`, `remote_folder="/remote/out"`, and all other fields (`task_id`, `label`, `engine`, `webhook_url`, `webhook_custom_params`, `error`, `extra`, `status`, `allocated_node_id`, `_events`) preserved unchanged

#### Scenario: with_download_results does not touch extra
- **WHEN** `task.with_download_results(local_folder="/l", remote_folder="/r")` is called on a Task with `extra={"input.in": "ATOMS ..."}`
- **THEN** the returned Task has `extra={"input.in": "ATOMS ..."}` unchanged — `extra` is NOT merged, NOT cleared, NOT modified

#### Scenario: with_download_results accepts equal values
- **WHEN** `task.with_download_results(local_folder=task.local_folder, remote_folder=task.remote_folder)` is called (same values as the existing fields)
- **THEN** a new Task is returned with the same `local_folder` and `remote_folder`; no error is raised

#### Scenario: with_download_results is keyword-only
- **WHEN** `task.with_download_results("/l", "/r")` is called with positional arguments
- **THEN** `TypeError` is raised (the parameters are keyword-only via `*,`)

#### Scenario: with_download_results performs no status validation
- **WHEN** `task.with_download_results(local_folder="/l", remote_folder="/r")` is called on a Task in any status (TO_DO, RUNNING, or DONE)
- **THEN** no error is raised and a new Task with the new fields is returned regardless of status

### Requirement: Task.error column format contract

The `Task.error` field (TEXT, nullable) SHALL carry one of three shapes depending on
which write site produced it:

- `allocate_task` reject → bare human string (e.g. `"unsupported engine"`)
- `orchestrator` fail → bare human string (e.g. `"node is gone"`)
- `consume_task` download fail → `"Download error: <path>: <msg>, <path>: <msg>"`
  (a class prefix `Download error: ` followed by one or more `<path>: <msg>` pairs
  joined by `, `; entries with `path=None` render as bare `"<msg>"`, though in
  practice `path` is always a string)
- `NULL` (no error) on the success path — `complete()` does NOT touch `error`

The download-failure format combines `permanent_errors + transient_errors` exactly
as the legacy code did (the mixed case includes both lists in the error string);
this behavior is preserved deliberately.

Historical `error` values in existing rows (legacy `str(dict)` format from the old
download path, e.g. `"{'/remote/1.out': 'No such file'}"`) are passed through
verbatim by migration 010 (`metadata->>'error'`); the migration does NOT reformat
existing rows. Only new writes follow this contract.

No reader of `Task.error` parses the string structure: e2e tests use substring match
(`"No such file" in str(error)`), unit tests use bare strings, and the webhook
receives the same `reason: str` on `TaskFailed` (see the `domain-events` capability).

#### Scenario: error is NULL on success
- **WHEN** a RUNNING task is completed via `task.complete()` after a successful download
- **THEN** the resulting Task has `error=None` (complete does not touch error; it was `None` before and stays `None`)

#### Scenario: error is the bare reason on reject
- **WHEN** `task.reject("unsupported engine")` is called
- **THEN** the resulting Task has `error="unsupported engine"`

#### Scenario: error is the bare reason on orchestrator fail
- **WHEN** `task.fail("node is gone")` is called
- **THEN** the resulting Task has `error="node is gone"`

#### Scenario: error is download-formatted on consume fail
- **WHEN** `consume_task._decide_finalisation` finalises a task whose `download_outputs` returned `permanent_errors=[("/remote/1.out", OSError("No such file"))]` and `transient_errors=[]`
- **THEN** `task.error == "Download error: /remote/1.out: No such file"`

#### Scenario: error combines permanent and transient in the mixed case
- **WHEN** `consume_task._decide_finalisation` finalises a task whose `download_outputs` returned `permanent_errors=[("/remote/2.out", OSError("No such file"))]` and `transient_errors=[("/remote/1.out", SFTPRetryExc("timeout"))]`
- **THEN** `task.error == "Download error: /remote/2.out: No such file, /remote/1.out: timeout"` (both lists combined, permanent first)

#### Scenario: error stays None on retry-then-success
- **WHEN** a task's first consume attempt defers (transient-only, no save) and a later attempt downloads successfully and calls `complete()`
- **THEN** the persisted task has `error=None` (the deferral wrote nothing; the successful `complete()` does not touch `error`)

#### Scenario: migration preserves legacy error format
- **WHEN** migration 010 runs against a row with `metadata = {"error": "{'/remote/1.out': 'No such file'}"}`
- **THEN** the new row has `error = "{'/remote/1.out': 'No such file'}"` (verbatim passthrough via `metadata->>'error'`; not reformatted)

## REMOVED Requirements

### Requirement: TaskContext typed metadata

**Reason**: The `TaskContext` value object existed only to model the `metadata` JSONB
column as a domain aggregate. Once the JSONB is extracted into typed columns on
`yascheduler_tasks` (migration 010) and the typed fields are folded directly onto
`Task` / `NewTask`, the `TaskContext` indirection has no behavioral purpose and is
removed. Reads that went through `task.context.X` become `task.X`; the two mutation
sites that used `task.context.replace(...)` become `Task.with_remote_folder` and
`Task.with_download_results` (see ADDED Requirements).

**Migration**:
- `task.context.engine` → `task.engine`
- `task.context.remote_folder` → `task.remote_folder`
- `task.context.local_folder` → `task.local_folder`
- `task.context.webhook_url` → `task.webhook_url`
- `task.context.webhook_custom_params` → `task.webhook_custom_params`
- `task.context.error` → `task.error`
- `task.context.extra` → `task.extra`
- `task.with_context(ctx)` (wholesale context replace) → `task.with_remote_folder(...)` or `task.with_download_results(...)` (named methods at the two real mutation sites)
- `task.context.replace(remote_folder=...)` (submit-time) → `task.with_remote_folder(...)`
- `task.context.replace(local_folder=..., remote_folder=..., extra={...})` (consume-time) → `task.with_download_results(local_folder=..., remote_folder=...)` (extra no longer merged — see the ADDED Requirement for rationale)
- `TaskContext.from_metadata(mapping)` (deserialization in `_row_to_task`) → typed column reads from the DB row
- `TaskContext.to_metadata()` (serialization in `insert`/`save`) → typed column writes to the DB row
- `TaskContext` / `TaskContextOverrides` symbols removed from `yascheduler.domain.__init__` exports

The `TaskContext` / `TaskContextOverrides` symbols are NOT part of the public API
(AGENTS.md: `TaskContext` is an internal domain detail); removal does not break the
public interface stability contract.

### Requirement: TaskContext JSONB serialization

**Reason**: `TaskContext.to_metadata()` / `TaskContext.from_metadata()` were the
JSONB round-trip pair for the `metadata` JSONB column. With the column extracted into
typed columns plus `extra` JSONB (migration 010), there is no single `metadata` JSONB
to round-trip. Persistence now reads/writes typed columns directly; the `extra` JSONB
is read/written as a `dict` via pg8000's native JSONB adaptation (no manual
`json.dumps`/`json.loads` on the `extra` column). The facade reconstruction
(`_task_to_dict` in `client.py`, see the `package-facades` capability) rebuilds the
flat `metadata` dict for the public `queue_get_tasks*` shape from the typed fields
plus `extra` — that is a read-time projection, not a `TaskContext` method.

**Migration**:
- `_row_to_task` (postgres.py): `TaskContext.from_metadata(row["metadata"])` → read typed columns from the row dict; `extra` via `row["extra"]` (already a dict from pg8000 JSONB adaptation, or `json.loads` if returned as str)
- `insert` (postgres.py): `json.dumps(new_task.context.to_metadata())` bound to `:metadata` → bind typed columns directly (`:engine`, `:remote_folder`, `:local_folder`, `:webhook_url`, `:error`, `:webhook_custom_params`, `:extra`)
- `save` (postgres.py): same as `insert` for the typed columns
- `_task_to_dict` (client.py): `t.context.to_metadata()` → inline reconstruction `{k: v for k, v in (typed fields with None omitted) if ...} | t.extra`
- `_get_opt_str` helper: removed (no longer needed without `from_metadata`)
- The `# type: ignore[arg-type]` annotations that `_get_opt_str` was introduced to eliminate are also removed (no `from_metadata` field assignments exist)

### Requirement: with_context method on Task

**Reason**: `Task.with_context` was the wholesale context-replace primitive, used at
two sites: `submit_task` (to set `remote_folder` after insert) and `consume_task` (to
set `local_folder`/`remote_folder`/`extra` after download). Post-extraction, each site
has a named method (`with_remote_folder`, `with_download_results`) that expresses its
intent precisely. A generic `with_context` has no remaining caller and is removed.

**Migration**:
- `submit_task.py:89-90`: `task.with_context(context).with_event(...)` (where `context = task.context.replace(remote_folder=remote_folder)`) → `task.with_remote_folder(remote_folder).with_event(...)`
- `consume_task.py:131,137`: `task.with_context(updated_context)` → `task.with_download_results(local_folder=..., remote_folder=...)` (the `updated_context` construction and the `extra_updates` merge block are deleted; see the `use-cases` delta for the full call-site rewrite)