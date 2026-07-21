## MODIFIED Requirements

### Requirement: Domain exception hierarchy

Tests SHALL verify all exception classes from `yascheduler.domain.exceptions`:
- `DomainError` catchable as `Exception`
- `ValidationError` hierarchy: `UnsupportedEngineError` (carries `engine_name`),
  `MissingInputFileError` (carries `engine_name`, `filename`)
- `TaskError` hierarchy: `TaskNotTodoError`, `TaskNotRunningError` (each carries `task_id`)
- `MachineBusyError` (carries `node_id`)
- `MachineConnectionError` (carries `node_id`, `hostname`, `reason`)
- `SchedulingError` hierarchy: `NoCompatibleNodeError` (carries `task_id`, `platforms`),
  `CloudCapacityExhaustedError` (carries `task_id`)
- All classes importable from `yascheduler.domain.exceptions`

#### Scenario: Exception hierarchy and field carrying
- **WHEN** `UnsupportedEngineError("gaussian")`, `TaskNotTodoError(TaskId(42))`, `NoCompatibleNodeError(TaskId(1), ["linux"])`, `MachineBusyError(NodeId(1))`, `MachineConnectionError(NodeId(1), "10.0.0.1", "refused")` are raised and caught
- **THEN** each stores its documented attribute (`engine_name`, `task_id`, `platforms`, `node_id`, `hostname`, `reason`) and is catchable via its parent class; `MachineBusyError` stores `node_id` only (no `hostname` attribute)

### Requirement: Remote machine management

Tests SHALL verify `ConnectedMachine` state transitions (`occupy`/`release`
toggling `state`/`free_since` via `MachineSession.occupy()`/`MachineSession.release()`),
`MachineBusyError` construction (single-argument `node_id`, no `hostname` attribute),
and `SSHMachineRepository.list_free(platforms)` filtering (busy exclusion,
platforms filter, oldest-first ordering by `free_since`, original registry
unchanged).

`ConnectedMachine` tests SHALL construct the entity with `node_id` and
`platform` keyword arguments only (NOT `hostname` or `ncpus`). `occupy()`
SHALL raise `MachineBusyError(node_id)` — assertions SHALL verify `e.node_id`
and SHALL NOT access `e.hostname`.

#### Scenario: ConnectedMachine occupy sets state to BUSY

- **WHEN** `session.occupy()` is called on a session whose `machine.state` is FREE
- **THEN** `session.machine.state` becomes BUSY and `session.machine.free_since` remains its prior value (only `release` resets `free_since`)

#### Scenario: ConnectedMachine release resets free_since

- **WHEN** `session.release()` is called on a session whose `machine.state` is BUSY
- **THEN** `session.machine.state` becomes FREE and `session.machine.free_since` is set to `time.monotonic()`

#### Scenario: ConnectedMachine occupy on BUSY raises MachineBusyError with node_id only

- **WHEN** `machine.occupy()` is called on a `ConnectedMachine` with `state=BUSY` and `node_id=NodeId(7)`
- **THEN** `MachineBusyError` is raised, `e.node_id == NodeId(7)`, and `e` does NOT have a `hostname` attribute (asserting `not hasattr(e, "hostname")` or `getattr(e, "hostname", None) is None`)

#### Scenario: list_free filters by platform and state

- **WHEN** `repository.list_free(["linux", "debian-12"])` is called on a repository holding FREE linux, BUSY linux, and FREE windows sessions
- **THEN** the returned list contains only the FREE linux session (BUSY excluded, windows excluded by platform filter), sorted oldest-first by `session.machine.free_since`, and the repository's `_sessions` dict is unchanged
