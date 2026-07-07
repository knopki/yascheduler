## Purpose

Defines the domain entity model for yascheduler: Task lifecycle, Node records, ConnectedMachine state, Engine specifications, and related value objects — all immutable with encapsulated business rules.

## Requirements

### Requirement: TaskId value object

The system SHALL provide a `TaskId` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/model.py` wrapping a single
field `value: int`. `TaskId` SHALL:

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

#### Scenario: Allocate task to a node
- **WHEN** `task.allocate_to(node)` is called on a TO_DO task with a `Node` carrying `node_id=NodeId(7)`
- **THEN** a new Task is returned with `allocated_node_id=NodeId(7)` and original status preserved

#### Scenario: Transition to RUNNING
- **WHEN** `task.mark_running()` is called on a TO_DO task with `allocated_node_id` set
- **THEN** a new Task is returned with `status=RUNNING`

#### Scenario: Transition to DONE
- **WHEN** `task.complete()` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`; `error` is NOT touched (remains whatever it was — `None` on the success path)

#### Scenario: Fail task with reason
- **WHEN** `task.fail("disk full")` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE` and `error="disk full"`

#### Scenario: Reject task with reason
- **WHEN** `task.reject("unsupported engine")` is called on a TO_DO task
- **THEN** a new Task is returned with `status=DONE` and `error="unsupported engine"`

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

#### Scenario: Occupy free machine
- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY` and the same `node_id`, `ip`, `platform`, `ncpus`

#### Scenario: Release machine
- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE`, `free_since` set to current timestamp, and the same `node_id`, `ip`, `platform`, `ncpus`

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

### Requirement: Task.with_remote_folder

The system SHALL provide a `Task.with_remote_folder(self, remote_folder: str) -> Task`
method that returns a new `Task` with `remote_folder` set and all other fields
preserved. The method SHALL perform no status validation and no side effect — it is
a pure copy-with used at submit time, after `TaskRepository.insert` generates the
`task_id` and the remote path is constructed from it.

#### Scenario: with_remote_folder sets the field
- **WHEN** `task.with_remote_folder("/remote/20240101_000000_7")` is called on a Task with `remote_folder=None`
- **THEN** a new Task is returned with `remote_folder="/remote/20240101_000000_7"` and all other fields preserved unchanged

### Requirement: Task.with_download_results

The system SHALL provide a
`Task.with_download_results(self, *, local_folder: str, remote_folder: str) -> Task`
method (keyword-only) that returns a new `Task` with `local_folder` and
`remote_folder` set and all other fields preserved. The method SHALL NOT update
`extra`. The method SHALL perform no status validation and no side effect — it is
a pure copy-with used at consume time, after `download_outputs` returns.

The call site MAY pass values equal to the existing field values — calling with
the same values is a no-op-equivalent and is not an error.

#### Scenario: with_download_results sets both fields
- **WHEN** `task.with_download_results(local_folder="/local/out", remote_folder="/remote/out")` is called on a Task with `local_folder=None`, `remote_folder=None`
- **THEN** a new Task is returned with `local_folder="/local/out"`, `remote_folder="/remote/out"`, and all other fields preserved unchanged

### Requirement: NodeId value object

The system SHALL provide a `NodeId` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/model.py` wrapping a single
field `value: int`. `NodeId` SHALL:

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
`NodeRepository.insert`. The tmp-node row inserted by `_select_and_insert_tmp`
is reused as the real node's identity: `clouds.allocate(provider, tmp_node_id)`
returns a `Node` carrying `node_id == tmp_node_id` (the cloud adapter does NOT
return a `NewNode`; the row already exists). The caller then flips
`enabled=TRUE` and sets `ip`/`ncpus` via `uow.nodes.update(node)`.

#### Scenario: NewNode has no node_id attribute
- **WHEN** a NewNode is instantiated with `ip="[IP]"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None

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

#### Scenario: EngineRepository is unhashable
- **WHEN** `hash(repo)` is called on an `EngineRepository` instance
- **THEN** `TypeError` is raised (frozen dataclass with `Mapping` field is unhashable; `__hash__` is not defined)

### Requirement: Engine INI parser in entrypoints

The system SHALL provide `parse_engine_section(sec: SectionProxy, engines_dir: PurePath) -> Engine`,
`parse_engines(cfg: ConfigParser, engines_dir: PurePath) -> EngineRepository`,
and `engine_valid_fields() -> Sequence[str]` as free functions in
`entrypoints/config_parser.py`. The validators `_check_spawn`, `_check_check_`,
`_check_at_least_one_elem` SHALL run parser-side (raising `ValueError` on
invalid INI), not in `Engine.__post_init__`.

`engine_valid_fields()` SHALL return the valid INI keys for an `[engine.*]`
section, including the deploy alias fields (`deploy_local_files`,
`deploy_local_archive`, `deploy_remote_archive`) and excluding the `name` and
`deployable` dataclass fields.

#### Scenario: parse_engine_section builds Engine from INI
- **WHEN** `parse_engine_section(cfg["engine.fleur"], engines_dir)` is called with a section containing `spawn`, `input_files`, `output_files`, `platforms`, `check_cmd`, `deploy_local_archive=fleur.tar`
- **THEN** an `Engine` is returned with `name="fleur"`, `deployable=(LocalArchiveDeploy(file=engines_dir/"fleur"/"fleur.tar"),)`, and the other fields populated from the section

#### Scenario: parse_engine_section rejects unknown spawn placeholders
- **WHEN** `parse_engine_section` is called with a `spawn` value containing `{unknown_placeholder}`
- **THEN** `ValueError` is raised by the parser-side `_check_spawn` validator

#### Scenario: parse_engine_section rejects missing check methods
- **WHEN** `parse_engine_section` is called with neither `check_cmd` nor `check_pname` set
- **THEN** `ValueError` is raised by the parser-side `_check_check_` validator

#### Scenario: parse_engines collects all engine sections
- **WHEN** `parse_engines(cfg, engines_dir)` is called with a `ConfigParser` containing `[engine.fleur]` and `[engine.cp2k]` sections
- **THEN** an `EngineRepository` is returned with `data` containing both engines keyed by name

#### Scenario: engine_valid_fields returns INI key list
- **WHEN** `engine_valid_fields()` is called
- **THEN** the returned sequence includes `spawn`, `input_files`, `output_files`, `platforms`, `platform_packages`, `check_cmd`, `check_pname`, `check_cmd_code`, `sleep_interval`, `deploy_local_files`, `deploy_local_archive`, `deploy_remote_archive` and excludes `name` and `deployable`
