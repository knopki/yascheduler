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
`get_by_ips(ips: list[str])`) and the `list_*` methods remain ip-keyed or
unkeyed — switching them to `node_id` is a deferred non-goal until the
ip-keyed orchestrator queues that feed them are migrated. `node_id` is the
primary identity; `ip` is an attribute that happens to serve the deferred
lookup paths.

#### Scenario: Node creation with defaults
- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `ip="10.0.0.1"`, `ncpus=4`, and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None

#### Scenario: Node always carries node_id
- **WHEN** a Node is obtained from any `NodeRepository` read or insert (`get`, `get_by_id`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `insert`)
- **THEN** `node.node_id` is a `NodeId` instance (never `None`)

#### Scenario: NewNode is the pre-persistence input shape
- **WHEN** a caller prepares a node record for insertion
- **THEN** it constructs a `NewNode` (no `node_id`), passes it to `NodeRepository.insert`, and receives a `Node` carrying the generated `NodeId`

### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as an immutable
object with fields: `ip: str`, `platform: str`, `ncpus: int`,
`state: MachineState`, `free_since: float | None`.

#### Scenario: Machine is compatible with platform list
- **WHEN** `machine.is_compatible(("linux", "debian-12"))` is called on a FREE machine with `platform="debian-12"`
- **THEN** returns True

#### Scenario: Busy machine is not compatible
- **WHEN** `machine.is_compatible(("linux",))` is called on a BUSY machine
- **THEN** returns False

#### Scenario: Occupy free machine
- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY`

#### Scenario: Occupy busy machine raises error
- **WHEN** `machine.occupy()` is called on a BUSY machine
- **THEN** `MachineBusyError` is raised

#### Scenario: Release machine
- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE` and `free_since` set to current timestamp

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

### Requirement: TaskContext typed metadata

The system SHALL provide a `TaskContext` value object as an immutable object
with fields: `engine: str`, `remote_folder: str | None`, `local_folder: str | None`,
`webhook_url: str | None`, `webhook_custom_params: dict[str, object]`,
`error: str | None`, `extra: dict[str, object]`.

The system SHALL provide a
`TaskContext.replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self`
method that returns a new `TaskContext` with the given overrides applied.
`TaskContextOverrides` SHALL be a `TypedDict` with `total=False` and SHALL
contain exactly the fields actually overridden at call sites in the codebase:
`remote_folder: str | None`, `local_folder: str | None`,
`error: str | None`, `extra: dict[str, object]`. The method SHALL perform no
merge into a stored context, no validation guard, and no side effect — it is
a pure typed copy-with delegating to `dataclasses.replace(self, **overrides)`.
The method SHALL be additive-only: raw `dataclasses.replace(ctx, ...)`
continues to work.

#### Scenario: TaskContext creation with known fields
- **WHEN** a TaskContext is instantiated with `engine="fleur"` and `webhook_url="https://example.com/hook"`
- **THEN** those fields are accessible as attributes; `extra` defaults to empty dict

#### Scenario: TaskContext preserves unknown fields in extra
- **WHEN** a TaskContext is created with `extra={"fort.9": "base64data", "custom_param": 42}`
- **THEN** those values are accessible via `ctx.extra["fort.9"]` and `ctx.extra["custom_param"]`

#### Scenario: replace returns a new immutable TaskContext with a single field overridden
- **WHEN** `ctx.replace(remote_folder="/r/new")` is called on a `TaskContext` with `remote_folder=None`
- **THEN** a new `TaskContext` is returned with `remote_folder="/r/new"` and all other fields (`engine`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`) preserved unchanged from the original

#### Scenario: replace returns a new immutable TaskContext with multiple fields overridden
- **WHEN** `ctx.replace(local_folder="/l", remote_folder="/r", extra={"k": "v"})` is called on a `TaskContext`
- **THEN** the returned `TaskContext` has `local_folder="/l"`, `remote_folder="/r"`, `extra={"k": "v"}`, and all non-overridden fields preserved unchanged

#### Scenario: replace leaves the original unchanged
- **WHEN** `ctx.replace(error="boom")` is called and the original `ctx.error` is inspected afterward
- **THEN** the returned TaskContext has `error="boom"` and the original `ctx.error` is unchanged (frozen dataclass)

#### Scenario: replace accepts no overrides and returns an equal copy
- **WHEN** `ctx.replace()` is called with no arguments
- **THEN** a new `TaskContext` is returned equal to the original (`==` holds) but not identical (`is` does not hold)

#### Scenario: replace type-checks override field names
- **WHEN** a caller writes `ctx.replace(remot_folder="/r")` (typo)
- **THEN** the type checker rejects the call with an unknown-argument error (the `TaskContextOverrides` TypedDict does not contain `remot_folder`); the call does not silently create a spurious field

#### Scenario: replace overrides only the 4 declared fields
- **WHEN** the set of keys in `TaskContextOverrides.__annotations__` is inspected
- **THEN** it equals exactly `{"remote_folder", "local_folder", "error", "extra"}` — the fields actually overridden at call sites in the codebase; `engine`, `webhook_url`, `webhook_custom_params` are excluded

#### Scenario: replace is additive-only
- **WHEN** `dataclasses.replace(ctx, remote_folder="/r")` is called directly (raw stdlib call, not the method)
- **THEN** it continues to work and returns a new `TaskContext` with `remote_folder="/r"` — the method's existence does not prohibit the raw primitive

### Requirement: TaskContext JSONB serialization

The system SHALL provide `TaskContext.to_metadata() -> dict` and
`TaskContext.from_metadata(mapping) -> TaskContext` for JSONB round-trip
persistence.

Known fields (`engine`, `remote_folder`, `local_folder`, `webhook_url`,
`webhook_custom_params`, `error`) are serialized as top-level keys with
`None` values omitted. Unknown keys are preserved in `extra` and merged
into the flat dict on serialization. On deserialization, keys not matching
known fields populate `extra`.

`from_metadata` SHALL validate the types of the 4 `str | None` known fields
(`remote_folder`, `local_folder`, `webhook_url`, `error`) at the JSONB
boundary: a value that is neither `str` nor `None` SHALL raise `TypeError`
with a message identifying the field name and the offending type. The
`engine` field SHALL be coerced via `str(metadata.get("engine", ""))` (a
missing `engine` defaults to the empty string; a non-str value is coerced
through `str()`). The `webhook_custom_params` field SHALL be assigned only
when the metadata value is a `dict` (per the existing
`isinstance(wcp, dict)` guard); a non-dict value SHALL fall back to an
empty dict (preserving existing behavior — no `TypeError` for this field).

The 4 `str | None` field validations SHALL be routed through a single
module-private `_get_opt_str(metadata, key) -> str | None` helper (or
equivalent narrowing) that returns `None` for a missing key, returns the
`str` for a `str` value, and raises `TypeError` for any other type. This
removes the `# type: ignore[arg-type]` annotations on those 4 assignments;
the 5th previously-ignored assignment (`webhook_custom_params`) drops its
`# type: ignore` because the existing `isinstance(wcp, dict)` guard narrows
`object` to `dict`, which is assignable to `dict[str, object]`.

The `TypeError` is the defensive boundary behavior — a non-str value under a
str-typed key indicates upstream JSONB corruption (a botched migration, a
hand-edited row, a serialization bug). Failing fast at the deserialization
boundary, with the field name and offending type in the message, enables
quick diagnosis; silently coercing or passing through would shift the crash
to a downstream consumer's `.upper()` call where the corruption origin is
untraceable.

#### Scenario: Round-trip preserves all data
- **WHEN** `TaskContext(engine="fleur", webhook_url="https://...", extra={"fort.9": "data"})` is serialized then deserialized
- **THEN** all known fields and extra keys are preserved

#### Scenario: None values omitted from serialized dict
- **WHEN** `TaskContext(engine="fleur")` is serialized via `to_metadata()`
- **THEN** only `engine` appears as a key; `remote_folder`, `local_folder`, etc. are absent

#### Scenario: Extra keys merged into flat dict
- **WHEN** `to_metadata()` is called on a TaskContext with `extra={"fort.9": "base64data"}`
- **THEN** the returned dict contains `"fort.9": "base64data"` as a top-level key

#### Scenario: from_metadata raises TypeError on non-str remote_folder
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "remote_folder": 123})` is called (an int value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name `remote_folder` and the offending type `int` (or `int`-derived name)

#### Scenario: from_metadata raises TypeError on non-str local_folder
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "local_folder": ["a", "b"]})` is called (a list value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name `local_folder`

#### Scenario: from_metadata raises TypeError on non-str webhook_url
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "webhook_url": {"k": "v"}})` is called (a dict value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name `webhook_url`

#### Scenario: from_metadata raises TypeError on non-str error
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "error": 4.5})` is called (a float value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name `error`

#### Scenario: from_metadata accepts None for str-or-None fields
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "remote_folder": None, "error": None})` is called
- **THEN** a `TaskContext` is returned with `remote_folder=None`, `error=None`, and `engine="fleur"` (no `TypeError` — `None` is permitted for the `str | None` fields)

#### Scenario: from_metadata coerces engine to str
- **WHEN** `TaskContext.from_metadata({"engine": 42})` is called (an int `engine` value)
- **THEN** a `TaskContext` is returned with `engine="42"` (the `str()` coercion applies; no `TypeError` for the `engine` field)

#### Scenario: from_metadata accepts dict for webhook_custom_params
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "webhook_custom_params": {"k": "v"}})` is called
- **THEN** a `TaskContext` is returned with `webhook_custom_params={"k": "v"}` (the existing `isinstance(wcp, dict)` guard accepts a dict)

#### Scenario: from_metadata falls back to empty dict for non-dict webhook_custom_params
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "webhook_custom_params": "not-a-dict"})` is called (a str value under the dict-typed key)
- **THEN** a `TaskContext` is returned with `webhook_custom_params={}` (the existing `isinstance` guard falls back to the empty-dict default; no `TypeError` for this field)

#### Scenario: No type: ignore on the 5 from_metadata field assignments
- **WHEN** `yascheduler/domain/model.py::TaskContext.from_metadata` is inspected for `# type: ignore` annotations on the `remote_folder`, `local_folder`, `webhook_url`, `error`, and `webhook_custom_params` assignments
- **THEN** zero `# type: ignore` annotations are present on those 5 assignments (the 4 `str | None` fields route through `_get_opt_str`; `webhook_custom_params` drops its over-cautious ignore because the existing `isinstance` guard already narrows to `dict`, which is assignable to `dict[str, object]`)

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
- **WHEN** `from yascheduler.domain.model import Task, NewTask, TaskId, Node, NewNode, NodeId, ConnectedMachine, TaskContext, Engine, TaskStatus, MachineState, ProcessResult`
- **THEN** all symbols are available (including the new `NewTask` and `TaskId`)

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
is the empty-string sentinel (see the `Node` "persistent record" requirement
for the invariant); the default `ncpus=0` reflects that a tmp node has no CPU
information until a real VM is provisioned.

`NewNode` carries no identity attribute; it is converted to a `Node` only by
`NodeRepository.insert`. `CloudProvisioner.allocate` returns a `NewNode` (a
freshly-built VM that has not been persisted) with a real `ip` and `ncpus`
populated from the provisioned VM; the caller persists it via `insert` and
receives the `Node`.

#### Scenario: NewNode has no node_id attribute
- **WHEN** a NewNode is instantiated with `ip="10.0.0.1"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None

#### Scenario: NewNode tmp-reservation defaults
- **WHEN** `NewNode(cloud="aws", enabled=False)` is instantiated
- **THEN** `ip` defaults to `""` (empty-string sentinel), `ncpus` defaults to `0`, `username` defaults to `"root"`, `port` defaults to `22`

#### Scenario: CloudProvisioner.allocate returns NewNode with real ip
- **WHEN** `CloudProvisioner.allocate("aws")` is called
- **THEN** it returns a `NewNode` with a real `ip` (the provisioned VM's address) and `ncpus` populated from the VM; the caller passes it to `NodeRepository.insert` to obtain a persisted `Node`

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
