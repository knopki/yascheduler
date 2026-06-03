## ADDED Requirements

### Requirement: Task entity with status lifecycle

The system SHALL provide a `Task` domain entity as a frozen dataclass with
fields: `task_id: int`, `label: str`, `status: TaskStatus`, `context: TaskContext`,
`allocated_ip: str | None`.

#### Scenario: Task creation
- **WHEN** a Task is instantiated with status TO_DO
- **THEN** fields are immutable and hashable

#### Scenario: Allocate task to a node
- **WHEN** `task.allocate_to("10.0.0.1")` is called on a TO_DO task
- **THEN** a new Task is returned with `allocated_ip="10.0.0.1"` and original status preserved

#### Scenario: Allocate already-allocated task
- **WHEN** `task.allocate_to("10.0.0.2")` is called on a task with status RUNNING
- **THEN** `TaskAlreadyAllocatedError` is raised

#### Scenario: Transition to RUNNING
- **WHEN** `task.mark_running()` is called on a TO_DO task
- **THEN** a new Task is returned with `status=RUNNING`

#### Scenario: Transition to DONE
- **WHEN** `task.complete()` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE`

#### Scenario: Complete non-running task
- **WHEN** `task.complete()` is called on a TO_DO task
- **THEN** `TaskNotAllocatedError` is raised

#### Scenario: Fail task with reason
- **WHEN** `task.fail("disk full")` is called on a RUNNING task
- **THEN** a new Task is returned with `status=DONE` and `context.error="disk full"`

### Requirement: Node persistent record

The system SHALL provide a `Node` domain entity as a frozen dataclass with
fields: `ip: str`, `ncpus: int`, `enabled: bool`, `cloud: str | None`,
`username: str`, `port: int`.

#### Scenario: Node creation with defaults
- **WHEN** a Node is instantiated with `ip="10.0.0.1"` and `ncpus=4` and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None

### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as a frozen
dataclass with fields: `ip: str`, `platform: str`, `ncpus: int`,
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
- **THEN** a new ConnectedMachine is returned with `state=FREE` and `free_since` set to current monotonic time

### Requirement: Engine value object

The system SHALL provide an `Engine` value object as a frozen dataclass with
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

The system SHALL provide a `TaskContext` value object as a frozen dataclass
with fields: `engine: str`, `remote_folder: str | None`, `local_folder: str | None`,
`webhook_url: str | None`, `webhook_custom_params: dict[str, object]`,
`error: str | None`, `extra: dict[str, object]`.

#### Scenario: TaskContext creation with known fields
- **WHEN** a TaskContext is instantiated with `engine="fleur"` and `webhook_url="https://example.com/hook"`
- **THEN** those fields are accessible as attributes; `extra` defaults to empty dict

#### Scenario: TaskContext preserves unknown fields in extra
- **WHEN** a TaskContext is created with `extra={"fort.9": "base64data", "custom_param": 42}`
- **THEN** those values are accessible via `ctx.extra["fort.9"]` and `ctx.extra["custom_param"]`

### Requirement: ProcessResult value object

The system SHALL provide a `ProcessResult` value object as a frozen dataclass
with fields: `exit_code: int`, `stdout: str`, `stderr: str`.

#### Scenario: ProcessResult with defaults
- **WHEN** a ProcessResult is instantiated with `exit_code=0`
- **THEN** `stdout` and `stderr` default to empty string

### Requirement: MachineState enum

The system SHALL provide a `MachineState` enum with values `FREE` and `BUSY`.

#### Scenario: MachineState values
- **WHEN** `MachineState.FREE` is compared to `MachineState.BUSY`
- **THEN** they are not equal
