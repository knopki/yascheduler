## Purpose

Defines the domain entity model for yascheduler: Task lifecycle, Node records, ConnectedMachine state, Engine specifications, and related value objects — all immutable with encapsulated business rules.

## Requirements

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

### Requirement: Node persistent record

The system SHALL provide a `Node` domain entity as an immutable object with
fields: `ip: str`, `ncpus: int`, `enabled: bool`, `cloud: str | None`,
`username: str`, `port: int`.

#### Scenario: Node creation with defaults
- **WHEN** a Node is instantiated with `ip="10.0.0.1"` and `ncpus=4` and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None

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
- **WHEN** `from yascheduler.domain.model import Task, Node, ConnectedMachine, TaskContext, Engine, TaskStatus, MachineState, ProcessResult`
- **THEN** all symbols are available

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
