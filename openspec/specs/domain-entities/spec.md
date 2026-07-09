## Purpose

Defines the domain entity model for yascheduler: Task lifecycle, Node records, ConnectedMachine state, Engine specifications, and related value objects — all immutable with encapsulated business rules.

## Requirements

### Requirement: TaskId value object

The system SHALL provide a `TaskId` value object as an immutable
`@dataclass(frozen=True)` wrapping a single field `value: int`. `TaskId` SHALL:

- validate in `__post_init__` that `value > 0`, raising `ValueError` otherwise;
- define `__str__` returning `str(self.value)`;
- be hashable (frozen dataclass) and usable as a dict key;
- NOT be equal to a bare `int` — `TaskId(5) == 5` is `False`.

At external boundaries the wrapped `.value` SHALL be unwrapped explicitly:
pg8000 SQL parameters pass `task_id.value`; JSON serialization emits
`task_id.value`; `dataclasses.asdict` over a `WebhookPayload` carrying
`task_id` emits `task_id.value`; DB-read mapping wraps
`TaskId(int(row["task_id"]))`.

`TaskId` SHALL NOT be `typing.NewType('TaskId', int)` and SHALL NOT subclass
`int`. It is the Task-side analog of `NodeId`.

#### Scenario: TaskId validates positive
- **WHEN** `TaskId(0)` or `TaskId(-3)` is constructed
- **THEN** `ValueError` is raised

### Requirement: NewTask pre-persistence record

The system SHALL provide a `NewTask` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** task record
(one that has not yet been assigned a database `task_id`). Fields:
`engine: str`, `label: str = ""`, `local_folder: str | None = None`,
`webhook_url: str | None = None`,
`webhook_custom_params: dict[str, object] = field(default_factory=dict)`,
`extra: dict[str, object] = field(default_factory=dict)`.

`NewTask` carries no identity attribute, no `events` tuple, no
`created_at`/`updated_at` timestamps, no `status`, no `allocated_node_id`, no
`remote_folder`, and no `error`. The DB supplies `status` (DEFAULT 'TO_DO'),
`allocated_node_id` (DEFAULT NULL), `created_at`/`updated_at` (DEFAULT NOW()) on
insert; `remote_folder` is assigned post-insert by `Task.run` (the TO_DO→RUNNING transition);
`error` is only ever set by `Task.reject` / `Task.fail` / `Task.abandon` on a post-persistence
`Task`. It is a pure data carrier with **no lifecycle methods**
(`run`/`reject`/`complete`/`fail`/`abandon` stay on `Task` — `NewTask` is converted to a `Task` only by
`TaskRepository.insert`).

`allocated_node_id` is bound by `Task.run(node_id, remote_folder)` after insert, not by
`NewTask` construction. A task that must be pre-bound to a node (e.g. the
never-connected-node-abandon integration test) is inserted as an unbound
`NewTask`, then `task.run(node_id, remote_folder)` + `repo.save(task)` bind it.

`NewTask` carries NO `remote_folder` and NO `error` fields: `remote_folder` is
assigned post-insert by `Task.run` (the TO_DO→RUNNING transition sets it from the
generated `task_id`); `error` is only ever set by `Task.reject` / `Task.fail` /
`Task.abandon` on a post-persistence `Task`. The two fields appear on `Task` only.

#### Scenario: NewTask is the pre-persistence input shape
- **WHEN** a caller prepares a task record for insertion
- **THEN** it constructs a `NewTask` (no `task_id`, no `status`, no `allocated_node_id`), passes it to `TaskRepository.insert`, and receives a `Task` carrying the generated `TaskId` with DB-defaulted `status=TO_DO` and `allocated_node_id=None`

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
from `NewTask` to `Task` happens in exactly one place: `TaskRepository.insert`,
which calls `materialize_task` (see the "materialize_task free function"
requirement) to attach `TaskCreated` to `events`.

`task_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `task_id`, `label`, `engine`, `remote_folder`, `local_folder`,
`webhook_url`, `webhook_custom_params`, `error`, `extra`, `created_at`,
`updated_at` carry no defaults; the remaining fields (`status`,
`allocated_node_id`, `events`) follow with their defaults. Construction at all
in-repo call sites uses keyword arguments, so the reorder is source-compatible.
`TaskId(0)` raises `ValueError` so the `task_id=0` sentinel is unrepresentable.

`allocated_node_id` is `None` for unallocated tasks (TO_DO with no node bound)
and for tasks whose node was deleted (the DB FK is `ON DELETE SET NULL`). It is
set only by `run(node_id, remote_folder)` (the `TO_DO→RUNNING` transition).
`allocated_ip` is removed from `Task`; the node transport address is obtained
from the resolved `Node.ip` via `nodes_by_id`.

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
UoW reads it directly in `collect_events`; no `pull_events` helper exists.

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
- **THEN** the `events=(...)` field appears in the repr output

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
`NodeRepository.insert`.

`node_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `node_id`, `ip`, `ncpus` carry no defaults; the remaining
fields follow with their defaults. Construction at all in-repo call sites uses
keyword arguments, so the reorder is source-compatible.

`ip` is no longer `UNIQUE` on `yascheduler_nodes` (tmp/pending rows carry
`ip=""` as a sentinel — multiple rows can share `""` after a node is removed).
`NodeRepository` mutators (`enable`/`disable`/`remove`/`update`) key on
`node_id`, not `ip`. The ip-keyed lookup methods (`get(ip: str)`,
`get_by_ips(ips: list[str])`) are REMOVED — all lookups are `node_id`-keyed
(`get_by_id`, `get_by_ids`). `node_id` is the primary identity; `ip` is an
attribute (the transport address).

#### Scenario: Node creation with defaults
- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `ip="[IP]"`, `ncpus=4`, and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None

### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as an immutable
`@dataclass(frozen=True)` object with fields (identity first):
`node_id: NodeId`, `ip: str`, `platform: str`, `ncpus: int`,
`state: MachineState = MachineState.FREE`, `free_since: float | None = None`.

`node_id` is the first field (identity first). It identifies which `Node`
this connected machine represents. `occupy()`/`release()`/`replace()` SHALL
carry `node_id` through automatically (frozen dataclass — `replace(self,
state=…)` preserves all non-overridden fields, including `node_id`). The
construction site is the machine-repository connect path, which passes
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

#### Scenario: Occupy free machine
- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY` and the same `node_id`, `ip`, `platform`, `ncpus`

#### Scenario: Release machine
- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE`, `free_since` set to current timestamp, and the same `node_id`, `ip`, `platform`, `ncpus`

### Requirement: Engine value object

The system SHALL provide an `Engine` value object as an immutable
`@dataclass(frozen=True)` (re-exported from `yascheduler.domain.model` and
`yascheduler.domain`) with fields:
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
parsing is provided by `parse_engine_section` and `parse_engines`.

#### Scenario: Engine constructed with defaults for the 4 merge fields
- **WHEN** `Engine(name="cp2k", spawn="cp2k", input_files=("inp",))` is constructed without `deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval`
- **THEN** `deployable == ()`, `platform_packages == ()`, `check_cmd_code == 0`, `sleep_interval == 10`

### Requirement: ProcessResult value object

The system SHALL provide a `ProcessResult` value object as an immutable object
with fields: `exit_code: int`, `stdout: str`, `stderr: str`.

#### Scenario: ProcessResult constructed with all fields
- **WHEN** `ProcessResult(exit_code=0, stdout="out", stderr="err")` is constructed
- **THEN** `exit_code == 0`, `stdout == "out"`, `stderr == "err"`

### Requirement: MachineState enum

The system SHALL provide a `MachineState` enum with values `FREE` and `BUSY`.

#### Scenario: MachineState has FREE and BUSY values
- **WHEN** `MachineState` is inspected
- **THEN** `MachineState.FREE` and `MachineState.BUSY` are defined

### Requirement: materialize_task free function

The system SHALL provide a `materialize_task(task: Task) -> Task` free function
that returns a new `Task` with a `TaskCreated` event appended to `events`. It
SHALL read `task_id`, `webhook_url`, `webhook_custom_params`, and `engine` off
the freshly-inserted `Task` and construct
`TaskCreated(task_id=task.task_id, webhook_url=task.webhook_url,
webhook_custom_params=task.webhook_custom_params, engine_name=task.engine)`,
then return `replace(task, events=(event,))`.

`materialize_task` is the sole `TaskCreated` emission site. It is called by
`TaskRepository.insert` on the row-mapping output. It SHALL NOT be called from
use cases or the orchestrator. It is a domain-layer function; the
infrastructure layer SHALL NOT import `TaskCreated` directly.

`replace` SHALL be used inside `materialize_task` and inside `Task` transition
methods only — not at use-case or orchestrator call sites.

#### Scenario: materialize_task attaches TaskCreated
- **WHEN** `materialize_task(task)` is called on a freshly-inserted Task with `task_id=TaskId(42)`, `engine="fleur"`, `webhook_url="https://..."`, `webhook_custom_params={}`, `events=()`
- **THEN** a new Task is returned with `events` containing one `TaskCreated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, engine_name="fleur")`

#### Scenario: materialize_task preserves all other fields
- **WHEN** `materialize_task(task)` is called on a Task
- **THEN** the returned Task has the same `task_id`, `label`, `engine`, `remote_folder`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`, `created_at`, `updated_at`, `status`, `allocated_node_id` as the input

### Requirement: NodeId value object

The system SHALL provide a `NodeId` value object as an immutable
`@dataclass(frozen=True)` wrapping a single field `value: int`. `NodeId` SHALL:

- validate in `__post_init__` that `value > 0`, raising `ValueError` otherwise;
- define `__str__` returning `str(self.value)`;
- be hashable (frozen dataclass) and usable as a dict key;
- NOT be equal to a bare `int` — `NodeId(5) == 5` is `False`.

At external boundaries the wrapped `.value` SHALL be unwrapped explicitly:
pg8000 SQL parameters pass `node_id.value`; JSON serialization emits
`node_id.value`; argparse wraps `NodeId(int(s))` after a `str.isdigit()`
discriminator check; DB-read mapping wraps `NodeId(int(row["node_id"]))`.

`NodeId` SHALL NOT be `typing.NewType('NodeId', int)` and SHALL NOT subclass
`int`. It is the Node-side analog of `TaskId`.

#### Scenario: NodeId validates positive
- **WHEN** `NodeId(0)` or `NodeId(-3)` is constructed
- **THEN** `ValueError` is raised

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
`NodeRepository.insert`. The tmp-node row is reused as the real node's
identity: `clouds.allocate(provider, tmp_node_id)` returns a `Node` carrying
`node_id == tmp_node_id` (the cloud adapter does NOT return a `NewNode`; the
row already exists). The caller then flips `enabled=TRUE` and sets `ip`/`ncpus`
via `uow.nodes.update(node)`.

#### Scenario: NewNode has no node_id attribute
- **WHEN** a NewNode is instantiated with `ip="[IP]"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None

### Requirement: EngineRepository domain collection

The system SHALL provide an `EngineRepository` value object as an immutable
`@dataclass(frozen=True)` (re-exported from `yascheduler.domain.model` and
`yascheduler.domain`) with a single field `data: Mapping[str, Engine]` (default
empty dict). `EngineRepository` SHALL NOT inherit from `UserDict`, SHALL NOT
define `__hash__`, and SHALL NOT carry an `engines_dir` field.

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

#### Scenario: EngineRepository is unhashable
- **WHEN** `hash(repo)` is called on an `EngineRepository` instance
- **THEN** `TypeError` is raised (frozen dataclass with `Mapping` field is unhashable; `__hash__` is not defined)

### Requirement: Engine INI parser in entrypoints

The system SHALL provide `parse_engine_section(sec: SectionProxy, engines_dir: PurePath) -> Engine`,
`parse_engines(cfg: ConfigParser, engines_dir: PurePath) -> EngineRepository`,
and `engine_valid_fields() -> Sequence[str]` as free functions. The validators
SHALL run parser-side (raising `ValueError` on invalid INI), not in
`Engine.__post_init__`.

`engine_valid_fields()` SHALL return the valid INI keys for an `[engine.*]`
section, including the deploy alias fields (`deploy_local_files`,
`deploy_local_archive`, `deploy_remote_archive`) and excluding the `name` and
`deployable` dataclass fields.

#### Scenario: parse_engine_section builds Engine from INI
- **WHEN** `parse_engine_section(cfg["engine.fleur"], engines_dir)` is called with a section containing `spawn`, `input_files`, `output_files`, `platforms`, `check_cmd`, `deploy_local_archive=fleur.tar`
- **THEN** an `Engine` is returned with `name="fleur"`, `deployable=(LocalArchiveDeploy(file=engines_dir/"fleur"/"fleur.tar"),)`, and the other fields populated from the section

#### Scenario: parse_engine_section rejects unknown spawn placeholders
- **WHEN** `parse_engine_section` is called with a `spawn` value containing `{unknown_placeholder}`
- **THEN** `ValueError` is raised by the parser-side validator

#### Scenario: parse_engine_section rejects missing check methods
- **WHEN** `parse_engine_section` is called with neither `check_cmd` nor `check_pname` set
- **THEN** `ValueError` is raised by the parser-side validator

#### Scenario: parse_engines collects all engine sections
- **WHEN** `parse_engines(cfg, engines_dir)` is called with a `ConfigParser` containing `[engine.fleur]` and `[engine.cp2k]` sections
- **THEN** an `EngineRepository` is returned with `data` containing both engines keyed by name

#### Scenario: engine_valid_fields returns INI key list
- **WHEN** `engine_valid_fields()` is called
- **THEN** the returned sequence includes `spawn`, `input_files`, `output_files`, `platforms`, `platform_packages`, `check_cmd`, `check_pname`, `check_cmd_code`, `sleep_interval`, `deploy_local_files`, `deploy_local_archive`, `deploy_remote_archive` and excludes `name` and `deployable`
