## Purpose

Defines the domain entity model for yascheduler: Task lifecycle, Node records, ConnectedMachine state, Engine specifications, and related value objects — all immutable with encapsulated business rules.

## Requirements

### Requirement: TaskId value object

The system SHALL provide a `TaskId` value object as an immutable wrapper
around a positive integer that validates its constructor input and renders
as the bare integer. `TaskId` is hashable and usable as a dict key.

The wrapped value SHALL be unwrapped explicitly at every external boundary
(SQL parameters, JSON serialization, CLI argument parsing).

#### Scenario: TaskId validates positive
- **WHEN** `TaskId(0)` or `TaskId(-3)` is constructed
- **THEN** `ValueError` is raised

### Requirement: NodeId value object

The system SHALL provide a `NodeId` value object as an immutable wrapper
around a positive integer that validates its constructor input and renders
as the bare integer. `NodeId` is hashable and usable as a dict key.

The wrapped value SHALL be unwrapped explicitly at every external boundary
(SQL parameters, JSON serialization, CLI argument parsing).

#### Scenario: NodeId validates positive
- **WHEN** `NodeId(0)` or `NodeId(-3)` is constructed
- **THEN** `ValueError` is raised

### Requirement: NewTask pre-persistence record

The system SHALL provide a `NewTask` domain entity as an immutable
pre-persistence task record — the input shape to `TaskRepository.insert`. It
carries no identity and no lifecycle; the conversion to a `Task` happens in
exactly one place — `TaskRepository.insert` — which attaches the generated
identity, the DB-defaulted `status=TO_DO`, and `allocated_node_id=None`.

#### Scenario: NewTask is the pre-persistence input shape
- **WHEN** a caller prepares a task record for insertion
- **THEN** it constructs a `NewTask` (no `task_id`, no `status`, no `allocated_node_id`), passes it to `TaskRepository.insert`, and receives a `Task` carrying the generated `TaskId` with DB-defaulted `status=TO_DO` and `allocated_node_id=None`

### Requirement: Task entity with status lifecycle

The system SHALL provide a `Task` domain entity as an immutable
post-persistence task record (carrying a `TaskId`). The entity owns its
lifecycle: five atomic transition methods (`run`, `reject`, `complete`,
`fail`, `abandon`) each validate the source state, set the fields that
change, construct and append the matching `DomainEvent` to `events`, and
return a new `Task` via `replace`.

`Task` is the only task shape that flows out of a repository. The `events`
field is public; the unit-of-work reads it directly for event collection.

`allocated_node_id` is `None` for unallocated tasks (TO_DO with no node
bound) and for tasks whose node was deleted. It is set only by `run`.

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
- **WHEN** `task.abandon(node_id=None)` is called on a RUNNING task whose allocated node was deleted, leaving `allocated_node_id=None`
- **THEN** a new Task is returned with `status=DONE`, `error="node is gone"`, folders unchanged, and `events` empty (no `TaskAbandoned` emitted — there is no node to abandon)

#### Scenario: abandon raises TaskNotRunningError on non-RUNNING
- **WHEN** `task.abandon(node_id=NodeId(7))` is called on a TO_DO task
- **THEN** `TaskNotRunningError(task.task_id)` is raised

#### Scenario: events field is public and shown in repr
- **WHEN** `repr(task)` is evaluated on a Task with one recorded event
- **THEN** the `events=(...)` field appears in the repr output

### Requirement: Node persistent record

The system SHALL provide a `Node` domain entity as an immutable
post-persistence node record (carrying a `NodeId`). `Node` is the only node
shape that flows out of a repository. Pre-persistence node records use
`NewNode`; the conversion happens in exactly one place —
`NodeRepository.insert`.

`ncpus: int | None` SHALL be interpreted as **operator-set static config**,
not a discovery cache:

- `None` means "no operator limit — the orchestrator discovers the CPU count at
  spawn via `session.get_cpu_cores()` (memoized per session)".
- `N > 0` means "operator-set static value — used directly at spawn, no remote
  discovery".

`jump_host` / `jump_port` / `jump_username` are authoritative SSH
connection-identity fields. They SHALL be populated exactly once at node
creation and SHALL NOT be re-resolved at connect time:

- Static nodes (`yasetnode` add-path): stamped from `config.remote.*` at
  `NewNode` construction.
- Cloud nodes (cloud allocator): stamped atomically from one source in the
  `replace(node, enabled=True, ...)` call that flips `enabled` — the matching
  `CloudConfig` (`prefix == node.cloud`) if it sets BOTH `jump_host` and
  `jump_username` (then `CloudConfig.jump_port` supplies `jump_port`),
  otherwise from `config.remote.*`. The three jump fields SHALL all come from
  the same source; a node SHALL NOT mix cloud `jump_host` with remote
  `jump_port`.

`jump_host = None` means "no tunnel" (direct connection).

#### Scenario: Node creation with defaults

- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `hostname="[IP]"`, `ncpus=4`, and `enabled=True`
- **THEN** the remaining fields take their documented defaults

#### Scenario: Static node stamps jump from remote defaults at creation

- **WHEN** `yasetnode` constructs a `NewNode` for a static node while `config.remote.jump_host="bastion.example.com"`, `config.remote.jump_username="jumper"`, `config.remote.jump_port=2222`
- **THEN** the resulting `NewNode.jump_host == "bastion.example.com"`, `NewNode.jump_username == "jumper"`, and `NewNode.jump_port == 2222` are persisted by `insert`, and the tmp row used for the connect-setup verification already carries them

#### Scenario: Cloud node stamps jump from matching CloudConfig at creation

- **WHEN** the cloud allocator runs `replace(node, enabled=True, ...)` for a node with `cloud="hetzner"`, and the `hetzner` `CloudConfig` has `jump_host="jump.example.com"`, `jump_username="jumper"`, `jump_port=2222`
- **THEN** the persisted `Node.jump_host == "jump.example.com"`, `Node.jump_username == "jumper"`, and `Node.jump_port == 2222`

#### Scenario: Cloud node falls back to remote defaults when CloudConfig has no jump

- **WHEN** the cloud allocator runs `replace(node, enabled=True, ...)` for a node whose matching `CloudConfig` does NOT set both `jump_host` and `jump_username`, and `config.remote.jump_host` is set with `config.remote.jump_port=2222`
- **THEN** the persisted `Node.jump_host` / `jump_username` / `jump_port` come from `config.remote.*`

#### Scenario: Cloud node does not mix cloud jump_host with remote jump_port

- **WHEN** the cloud allocator runs `replace(node, enabled=True, ...)` for a node whose matching `CloudConfig` sets `jump_host` but NOT `jump_username`, and `config.remote.jump_port=2222`
- **THEN** the persisted `Node.jump_host`, `Node.jump_username`, AND `Node.jump_port` ALL come from `config.remote.*` (the cloud leg is not half-authoritative)

#### Scenario: Node ncpus None means discover at spawn

- **WHEN** a Node is instantiated with `ncpus=None`
- **THEN** the orchestrator resolves the CPU count at spawn via `session.get_cpu_cores()` (memoized per session) rather than using a stored value

#### Scenario: Node ncpus positive means operator-set static config

- **WHEN** a Node is instantiated with `ncpus=8`
- **THEN** the orchestrator uses `8` directly at spawn and does NOT call `session.get_cpu_cores()`

### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as an immutable
runtime record of a connected machine. It carries the `node_id` (preserved
across `occupy()`/`release()` transitions), the runtime-discovered
`platform`, and the runtime-only `state` / `free_since` (which SHALL NOT be
persisted and SHALL NOT propagate to `Node`).

`MachineBusyError(self.node_id)` is raised by `occupy()` when the machine is
already BUSY — the error carries the `node_id` (identity).

#### Scenario: Machine is compatible with platform list
- **WHEN** `machine.is_compatible(("linux", "debian-12"))` is called on a FREE machine with `platform="debian-12"`
- **THEN** returns True

#### Scenario: Occupy free machine
- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY` and the same `node_id`, `platform`

#### Scenario: Occupy busy machine raises MachineBusyError carrying node_id only
- **WHEN** `machine.occupy()` is called on a BUSY machine
- **THEN** `MachineBusyError(self.node_id)` is raised; the exception carries `node_id` (identity) and does NOT carry a `hostname` attribute

#### Scenario: Release machine
- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE`, `free_since` set to current timestamp, and the same `node_id`, `platform`

### Requirement: Engine value object

The system SHALL provide an `Engine` value object as an immutable record
(re-exported from `yascheduler.domain.model` and `yascheduler.domain`).

#### Scenario: Engine constructed with defaults for the 4 merge fields
- **WHEN** `Engine(name="cp2k", spawn="cp2k", input_files=("inp",))` is constructed without `deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval`
- **THEN** `deployable == ()`, `platform_packages == ()`, `check_cmd_code == 0`, `sleep_interval == 10`

### Requirement: ProcessResult value object

The system SHALL provide a `ProcessResult` value object as an immutable
  record.

#### Scenario: ProcessResult constructed with all fields
- **WHEN** `ProcessResult(exit_code=0, stdout="out", stderr="err")` is constructed
- **THEN** `exit_code == 0`, `stdout == "out"`, `stderr == "err"`

### Requirement: MachineState enum

The system SHALL provide a `MachineState` enum with the FREE and BUSY
values.

#### Scenario: MachineState has FREE and BUSY values
- **WHEN** `MachineState` is inspected
- **THEN** `MachineState.FREE` and `MachineState.BUSY` are defined

### Requirement: materialize_task free function

The system SHALL provide a `materialize_task(task: Task) -> Task` free
function that returns a new `Task` with a `TaskCreated` event appended to
`events`. It constructs the event from the freshly-inserted `Task`'s
`task_id`, `webhook_url`, `webhook_custom_params`, and `engine` fields.

`materialize_task` is the sole `TaskCreated` emission site, called only by
`TaskRepository.insert` on the row-mapping output. It is a domain-layer
function; `TaskCreated` is consumed only inside the domain layer.

#### Scenario: materialize_task attaches TaskCreated
- **WHEN** `materialize_task(task)` is called on a freshly-inserted Task with `task_id=TaskId(42)`, `engine="fleur"`, `webhook_url="https://..."`, `webhook_custom_params={}`, `events=()`
- **THEN** a new Task is returned with `events` containing one `TaskCreated` whose `task_id == TaskId(42)`, `engine_name == "fleur"`, `webhook_url == "https://..."`, `webhook_custom_params == {}`

#### Scenario: materialize_task preserves all other fields
- **WHEN** `materialize_task(task)` is called on a Task
- **THEN** the returned Task has the same `task_id`, `label`, `engine`, `remote_folder`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`, `created_at`, `updated_at`, `status`, `allocated_node_id` as the input

### Requirement: NewNode pre-persistence record

The system SHALL provide a `NewNode` domain entity as an immutable
pre-persistence node record — the input shape to `NodeRepository.insert`. It
carries no identity attribute; the conversion to a `Node` happens in exactly
one place — `NodeRepository.insert`. The tmp-node row is reused as the real
node's identity: `clouds.allocate(provider, tmp_node_id)` returns a `Node`
carrying `node_id == tmp_node_id`.

`NewNode` mirrors the non-`node_id` fields of `Node` with identical defaults,
except that `hostname` and `ncpus` carry defaults (`""` and `None`) so the
tmp-reservation call site can construct a tmp node without naming them:
`NewNode(cloud=selected_name, enabled=False)`.

#### Scenario: NewNode defaults ncpus to None
- **WHEN** a NewNode is instantiated with only `cloud="aws"` and `enabled=False`
- **THEN** `ncpus` defaults to `None` (no operator-set limit; discovered at spawn)

### Requirement: NodeStatus enum

The system SHALL provide a `NodeStatus` enum as a `StrEnum` with the `OTHER`
value (a placeholder for future node lifecycle states). The enum value
matches the `TASK_STATUS` convention (enum label == name).

#### Scenario: NodeStatus has OTHER value
- **WHEN** `NodeStatus` is inspected
- **THEN** `NodeStatus.OTHER` is defined with value `"OTHER"`

#### Scenario: NodeStatus is a StrEnum
- **WHEN** `isinstance(NodeStatus.OTHER, str)` is checked
- **THEN** it returns `True` (StrEnum members are str instances)

#### Scenario: NodeStatus DB lookup by name
- **WHEN** `NodeStatus["OTHER"]` is called
- **THEN** it returns `NodeStatus.OTHER` (name-based lookup, matching the `TASK_STATUS` pattern)

### Requirement: EngineRepository domain collection

The system SHALL provide an `EngineRepository` value object as an immutable
collection of `Engine`s (re-exported from `yascheduler.domain.model` and
`yascheduler.domain`). `filter` and `filter_platforms` SHALL return a new
frozen `EngineRepository` instance; the original is not mutated.

#### Scenario: EngineRepository constructed with data
- **WHEN** `EngineRepository(data={"fleur": engine})` is constructed
- **THEN** `repo["fleur"] is engine`, `repo.get("fleur") is engine`, `"fleur" in repo` is True, `repo.get("missing") is None`, and `list(repo.values()) == [engine]`

#### Scenario: EngineRepository is unhashable
- **WHEN** `hash(repo)` is called on an `EngineRepository` instance
- **THEN** `TypeError` is raised (frozen dataclass with `Mapping` field is unhashable)