## Purpose

Defines the domain entity model for yascheduler: Task lifecycle, Node records, ConnectedMachine state, Engine specifications, and related value objects — all immutable with encapsulated business rules.

## Requirements

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

### Requirement: Node persistent record

The system SHALL provide a `Node` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** node record
(one that has been assigned a database `node_id`). Fields: `node_id: NodeId`,
`ip: str`, `ncpus: int`, `enabled: bool`, `cloud: str | None`, `username: str`,
`port: int`.

A `Node` SHALL always carry a `node_id: NodeId` (never `None`); it is the only
node shape that flows out of a repository. Pre-persistence node records use
`NewNode` (see the "NewNode pre-persistence record" requirement). The conversion
from `NewNode` to `Node` happens in exactly one place:
`NodeRepository.insert` (see the `domain-ports` capability).

`node_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `node_id`, `ip`, `ncpus` carry no defaults; the remaining
fields follow with their defaults. Construction at all in-repo call sites uses
keyword arguments, so the reorder is source-compatible.

After migration 003, `ip` is no longer `UNIQUE` on `yascheduler_nodes`
(migration 003 dropped the `UNIQUE` constraint; tmp/pending rows now carry
`ip=""` as a sentinel — multiple rows can share `""` after a node is removed).
`NodeRepository` mutators (`enable`/`disable`/`remove`/`update`) key on
`node_id`, not `ip`. The ip-keyed lookup methods (`get(ip: str)`,
`get_by_ips(ips: list[str])`) are REMOVED — all lookups are `node_id`-keyed
(`get_by_id`, `get_by_ids`) after the `ssh-rekey-node-id` change. `node_id` is
the primary identity; `ip` is an attribute (the transport address).

#### Scenario: Node creation with defaults

- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `ip="10.0.0.1"`, `ncpus=4`, and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None

#### Scenario: Node always carries node_id

- **WHEN** a Node is obtained from any `NodeRepository` read or insert (`get_by_id`, `get_by_ids`, `list_enabled`, `list_disabled`, `list_all`, `insert`)
- **THEN** `node.node_id` is a `NodeId` instance (never `None`)

#### Scenario: NewNode is the pre-persistence input shape

- **WHEN** a caller prepares a node record for insertion
- **THEN** it constructs a `NewNode` (no `node_id`), passes it to `NodeRepository.insert`, and receives a `Node` carrying the generated `NodeId`
### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as an immutable
`@dataclass(frozen=True)` object with fields (identity first):
`node_id: NodeId`, `ip: str`, `platform: str`, `ncpus: int`,
`state: MachineState = MachineState.FREE`, `free_since: float | None = None`.

`node_id` is the first field (identity first). It identifies which `Node`
this connected machine represents. `occupy()`/`release()`/`replace()` SHALL
carry `node_id` through automatically (frozen dataclass — `replace(self,
state=…)` preserves all non-overridden fields, including `node_id`). The
construction site is `SSHMachineRepository._connect_impl`, which passes
`node_id=node.node_id` from the `Node` parameter of `connect`.

`ip` is the transport address (the asyncssh host). It is read at connect
time and exposed via `MachineSession.ip` for transport-level concerns
(`MachineConnectionError`, CLI display, logging). It is NOT the identity —
two `ConnectedMachine` instances with the same `ip` but different `node_id`
are distinct (the dup-IP configuration behind different jump hosts).

`MachineBusyError(self.ip)` is raised by `occupy()` when the machine is
already BUSY — the error keeps `ip` for operator-facing messages (the
address is what the operator recognizes).

#### Scenario: Machine is compatible with platform list

- **WHEN** `machine.is_compatible(("linux", "debian-12"))` is called on a FREE machine with `platform="debian-12"`
- **THEN** returns True

#### Scenario: Busy machine is not compatible

- **WHEN** `machine.is_compatible(("linux",))` is called on a BUSY machine
- **THEN** returns False

#### Scenario: Occupy free machine

- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY` and the same `node_id`, `ip`, `platform`, `ncpus` (only `state` is overridden; `replace()` carries the rest)

#### Scenario: Occupy busy machine raises error

- **WHEN** `machine.occupy()` is called on a BUSY machine
- **THEN** `MachineBusyError` is raised (carrying `self.ip`)

#### Scenario: Release machine

- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE`, `free_since` set to current timestamp, and the same `node_id`, `ip`, `platform`, `ncpus`

#### Scenario: ConnectedMachine carries node_id

- **WHEN** a `ConnectedMachine` is constructed at `SSHMachineRepository._connect_impl` from `Node(node_id=NodeId(7), ip="10.0.0.1", …)`
- **THEN** the resulting `ConnectedMachine` has `node_id == NodeId(7)` and `ip == "10.0.0.1"`

#### Scenario: Two machines sharing an ip are distinct

- **WHEN** two `ConnectedMachine` instances are constructed with `ip="10.0.0.1"` but different `node_id` (`NodeId(1)` and `NodeId(2)`)
- **THEN** they are distinct entities (different `node_id`); both can be registered in `_sessions` under their respective `NodeId` keys without collision
### Requirement: Engine value object

The system SHALL provide an `Engine` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/engine.py` (re-exported from
`yascheduler.domain.model` and `yascheduler.domain`) with fields:
`name: str`, `spawn: str`, `input_files: tuple[str, ...] = ()`,
`output_files: tuple[str, ...] = ()`, `platforms: tuple[str, ...] = ()`,
`check_cmd: str | None = None`, `check_pname: str | None = None`,
`deployable: tuple[Deploy, ...] = ()`, `platform_packages: tuple[str, ...] = ()`,
`check_cmd_code: int = 0`, `sleep_interval: int = 10`.

The 4 fields `deployable`, `platform_packages`, `check_cmd_code`,
`sleep_interval` SHALL have defaults so existing
`Engine(name=..., spawn=..., input_files=..., platforms=...)` constructor
calls continue to work without modification.

`Engine` SHALL NOT import `ConfigParser` or `SectionProxy` and SHALL NOT carry
`from_config_parser_section` or `get_valid_config_parser_fields` methods; INI
parsing is provided by `entrypoints/config_parser.py::parse_engine_section`
and `parse_engines`.

#### Scenario: Validate inputs when all files present
- **WHEN** `engine.validate_inputs(ctx)` is called and all `input_files` exist in `ctx.extra`
- **THEN** no exception is raised

#### Scenario: Validate inputs when file missing
- **WHEN** `engine.validate_inputs(ctx)` is called and a required input file is missing from `ctx.extra`
- **THEN** `MissingInputFileError` is raised

#### Scenario: Engine constructed with defaults for the 4 merge fields
- **WHEN** `Engine(name="cp2k", spawn="cp2k", input_files=("inp",))` is constructed without `deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval`
- **THEN** `deployable == ()`, `platform_packages == ()`, `check_cmd_code == 0`, `sleep_interval == 10`

#### Scenario: Engine is immutable
- **WHEN** `engine.name = "other"` is attempted on an `Engine` instance
- **THEN** `FrozenInstanceError` is raised (frozen dataclass)

#### Scenario: Engine has no INI parser methods
- **WHEN** `Engine` is inspected for class attributes
- **THEN** it has no `from_config_parser_section` classmethod and no `get_valid_config_parser_fields` classmethod

### Requirement: ProcessResult value object

The system SHALL provide a `ProcessResult` value object as an immutable object
with fields: `exit_code: int`, `stdout: str`, `stderr: str`.

#### Scenario: ProcessResult with defaults
- **WHEN** a ProcessResult is instantiated with `exit_code=0`
- **THEN** `stdout` and `stderr` default to empty string

### Requirement: MachineState enum

The system SHALL provide a `MachineState` enum with values `FREE` and `BUSY`.

#### Scenario: MachineState members
- **WHEN** `MachineState.FREE` and `MachineState.BUSY` are accessed
- **THEN** they are distinct enum members

### Requirement: Domain entities are importable from yascheduler.domain.model

The system SHALL expose all domain entities from `yascheduler.domain.model`.

#### Scenario: Import entities
- **WHEN** `from yascheduler.domain.model import Task, NewTask, TaskId, Node, NewNode, NodeId, ConnectedMachine, Engine, TaskStatus, MachineState, ProcessResult`
- **THEN** all symbols are available (including `NewTask` and `TaskId`); `TaskContext` and `TaskContextOverrides` are NO LONGER importable (removed)

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

### Requirement: NodeId value object

The system SHALL provide a `NodeId` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/model.py` wrapping a single
field `value: int`. `NodeId` SHALL:

- validate in `__post_init__` that `value > 0`, raising `ValueError` otherwise
  (`yascheduler_nodes.node_id SERIAL PRIMARY KEY` starts at 1, so a non-positive
  value indicates a bug);
- define `__str__` returning `str(self.value)` so CLI rendering and logging
  produce the bare integer string (not the dataclass `repr`
  `NodeId(value=5)`);
- be hashable (frozen dataclass) and usable as a dict key;
- NOT be equal to a bare `int` — `NodeId(5) == 5` is `False`. This is the
  type-safety point of a dedicated value object: callers cannot accidentally
  mix a `NodeId` with an unrelated `int`.

At external boundaries the wrapped `.value` SHALL be unwrapped explicitly:
pg8000 SQL parameters pass `node_id.value` (pg8000 cannot adapt a dataclass);
JSON serialization emits `node_id.value`; argparse wraps `NodeId(int(s))` after
a `str.isdigit()` discriminator check; DB-read mapping wraps
`NodeId(int(row["node_id"]))`.

`NodeId` SHALL NOT be `typing.NewType('NodeId', int)` (erased to `int` at
runtime, no validation, no methods) and SHALL NOT subclass `int` (defeats
value-object ergonomics and the explicit "frozen dataclass with value: int"
design).

#### Scenario: NodeId validates positive
- **WHEN** `NodeId(0)` or `NodeId(-3)` is constructed
- **THEN** `ValueError` is raised

#### Scenario: NodeId str renders the bare integer
- **WHEN** `str(NodeId(5))` or `f"{NodeId(5)}"` is evaluated
- **THEN** the result is `"5"` (NOT `"NodeId(value=5)"`)

#### Scenario: NodeId is not equal to int
- **WHEN** `NodeId(5) == 5` is evaluated
- **THEN** the result is `False`

#### Scenario: NodeId is hashable
- **WHEN** `hash(NodeId(5))` is evaluated or `NodeId(5)` is used as a dict key
- **THEN** it succeeds (frozen dataclass is hashable)

#### Scenario: NodeId wraps DB-generated serial on read
- **WHEN** a row with `node_id = 7` is read from `yascheduler_nodes`
- **THEN** `_row_to_node` constructs `NodeId(int(row["node_id"]))` → `NodeId(7)`

### Requirement: NewNode pre-persistence record

The system SHALL provide a `NewNode` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** node record
(one that has not yet been assigned a database `node_id`). Fields:
`ip: str = ""`, `ncpus: int = 0`, `enabled: bool = True`,
`cloud: str | None = None`, `username: str = "root"`, `port: int = 22`.

`NewNode` mirrors the non-`node_id` fields of `Node` with identical defaults,
**except** that `ip` and `ncpus` carry defaults (`""` and `0`) so the
tmp-reservation call site can construct a tmp node without naming them:
`NewNode(cloud=selected_name, enabled=False)`. Field types are unchanged
(`ip: str`, `ncpus: int`) — no `Optional` is introduced. The default `ip=""`
is the empty-string sentinel; the default `ncpus=0` reflects that a tmp node
has no CPU information until a real VM is provisioned.

`NewNode` carries no identity attribute; it is converted to a `Node` only by
`NodeRepository.insert`. The tmp-node row inserted by `_select_and_insert_tmp`
is reused as the real node's identity: `clouds.allocate(provider, tmp_node_id)`
returns a `Node` carrying `node_id == tmp_node_id` (the cloud adapter does NOT
return a `NewNode`; the row already exists). The caller then flips
`enabled=TRUE` and sets `ip`/`ncpus` via `uow.nodes.update(node)`.

#### Scenario: NewNode has no node_id attribute

- **WHEN** a NewNode is instantiated with `ip="10.0.0.1"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None

#### Scenario: NewNode tmp-reservation defaults

- **WHEN** `NewNode(cloud="aws", enabled=False)` is instantiated
- **THEN** `ip` defaults to `""` (empty-string sentinel), `ncpus` defaults to `0`, `username` defaults to `"root"`, `port` defaults to `22`

#### Scenario: CloudProvisioner.allocate returns Node reusing tmp_node_id

- **WHEN** `CloudProvisioner.allocate("aws", tmp_node_id=NodeId(7))` is called
- **THEN** it returns a `Node` with `node_id == NodeId(7)` (the tmp_node_id), a real `ip` (the provisioned VM's address), and `ncpus` populated from the VM; the caller passes it to `NodeRepository.update` to flip `enabled=TRUE` and persist `ip`/`ncpus`
### Requirement: EngineRepository domain collection

The system SHALL provide an `EngineRepository` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/engine.py` (re-exported from
`yascheduler.domain.model` and `yascheduler.domain`) with a single field
`data: Mapping[str, Engine]` (default empty dict). `EngineRepository` SHALL
NOT inherit from `UserDict`, SHALL NOT define `__hash__`, and SHALL NOT carry
an `engines_dir` field.

`EngineRepository` SHALL provide: `get(name: str) -> Engine | None`,
`__getitem__(name: str) -> Engine`, `__contains__(name: object) -> bool`,
`values() -> ValuesView[Engine]`,
`filter(fn: Callable[[Engine], bool]) -> EngineRepository`,
`filter_platforms(platforms: Sequence[str]) -> EngineRepository`,
`get_platform_packages() -> list[str]`.

`filter` and `filter_platforms` SHALL return a new frozen `EngineRepository`
instance; the original SHALL NOT be mutated.

#### Scenario: EngineRepository constructed with data
- **WHEN** `EngineRepository(data={"fleur": engine})` is constructed
- **THEN** `repo["fleur"] is engine`, `repo.get("fleur") is engine`, `"fleur" in repo` is True, `repo.get("missing") is None`, and `list(repo.values()) == [engine]`

#### Scenario: filter returns new frozen instance
- **WHEN** `repo.filter(lambda e: "linux" in e.platforms)` is called on an `EngineRepository` with two engines (one linux, one windows)
- **THEN** a new `EngineRepository` is returned containing only the linux engine; the original `repo` is unchanged and still contains both engines

#### Scenario: filter_platforms returns new frozen instance
- **WHEN** `repo.filter_platforms(("linux",))` is called on an `EngineRepository` with engines whose `platforms` include `("linux",)` and `("windows",)`
- **THEN** a new `EngineRepository` is returned containing only engines with `linux` in their platforms; the original is unchanged

#### Scenario: get_platform_packages collects unique packages
- **WHEN** `repo.get_platform_packages()` is called on an `EngineRepository` with two engines whose `platform_packages` are `("fleur", "python")` and `("python", "mpi")`
- **THEN** the returned list contains each unique package exactly once (order-independent)

#### Scenario: EngineRepository has no engines_dir field
- **WHEN** an `EngineRepository` instance is inspected for attributes
- **THEN** it has no `engines_dir` attribute; the field does not exist on the class

#### Scenario: EngineRepository is unhashable
- **WHEN** `hash(repo)` is called on an `EngineRepository` instance
- **THEN** `TypeError` is raised (frozen dataclass with `Mapping` field is unhashable; `__hash__` is not defined)

### Requirement: Engine domain types importable from yascheduler.domain.model

The system SHALL re-export `Engine`, `EngineRepository`,
`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`, and `Deploy`
from `yascheduler.domain.model` for backward compatibility with existing
`from yascheduler.domain.model import Engine` imports.

#### Scenario: Import Engine and EngineRepository from domain.model
- **WHEN** `from yascheduler.domain.model import Engine, EngineRepository` is executed
- **THEN** both symbols resolve without ImportError (re-exported from `domain/engine.py`)
