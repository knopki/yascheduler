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

The system SHALL provide an `Engine` value object as an immutable object with
fields: `name: str`, `spawn: str`, `input_files: tuple[str, ...]`,
`output_files: tuple[str, ...]`, `platforms: tuple[str, ...]`,
`check_cmd: str | None`, `check_pname: str | None`.

#### Scenario: Validate inputs when all files present
- **WHEN** `engine.validate_inputs(ctx)` is called and all `input_files` exist in `ctx.extra`
- **THEN** no exception is raised

#### Scenario: Validate inputs when file missing
- **WHEN** `engine.validate_inputs(ctx)` is called and a required input file is missing from `ctx.extra`
- **THEN** `MissingInputFileError` is raised

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

#### Scenario: Round-trip preserves all data
- **WHEN** `TaskContext(engine="fleur", webhook_url="https://...", extra={"fort.9": "data"})` is serialized then deserialized
- **THEN** all known fields and extra keys are preserved

#### Scenario: None values omitted from serialized dict
- **WHEN** `TaskContext(engine="fleur")` is serialized via `to_metadata()`
- **THEN** only `engine` appears as a key; `remote_folder`, `local_folder`, etc. are absent

#### Scenario: Extra keys merged into flat dict
- **WHEN** `to_metadata()` is called on a TaskContext with `extra={"fort.9": "base64data"}`
- **THEN** the returned dict contains `"fort.9": "base64data"` as a top-level key

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
