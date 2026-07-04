## MODIFIED Requirements

### Requirement: MachineRepository port

The system SHALL define a `@runtime_checkable` `MachineRepository`
Protocol in `yascheduler/domain/ports.py` representing the
connected-machine collection. The Protocol SHALL NOT include operations
on a single machine (exec, SFTP, deploy, download, occupancy-check
logic, monitor mechanism) — those are `MachineSession` and
`MachineOperations`.

The collection is keyed by `NodeId`, not by ip. `ip` survives only as
the transport address read from `node.ip` inside `connect`; it is no
longer a positional parameter or a dict key.

**Collection lifecycle:**
- `connect(node: Node, username: str, client_keys: Sequence[PurePath] | None, *, port: int = 22, connect_timeout: int | None = None, data_dir: PurePath | None = None, engines_dir: PurePath | None = None, tasks_dir: PurePath | None = None, jump_host: str | None = None, jump_username: str | None = None) -> MachineSession` (async) — constructs and registers an `SSHMachineSession` keyed by `node.node_id`, returns it. The asyncssh transport uses `node.ip` as the host address.
- `disconnect(node_id: NodeId) -> None` (async) — pops the session keyed by `node_id` and delegates teardown to `session._close()`
- `disconnect_all() -> None` (async) — unchanged

**Queries:**
- `list_free(platforms: list[str] | None) -> list[MachineSession]` (sync) — FREE sessions filtered by `session.machine.platform`, oldest-first by `session.machine.free_since` (unchanged shape)
- `list_connected() -> list[MachineSession]` (sync) — unchanged
- `get_session(node_id: NodeId) -> MachineSession | None` (sync) — the live session for `node_id`, or `None` after disconnect
- `contains(node_id: NodeId) -> bool` (sync) — explicit form of `__contains__`; preserved for the three production callers (`deallocate_nodes.py`, `orchestrator.py` ×2)
- `__len__() -> int` (sync) — unchanged
- `__contains__(node_id: NodeId) -> bool` (sync) — supports `node_id in repository`

`MachineRepository` is `@runtime_checkable`. The Protocol SHALL NOT
reference `Engine`. The Protocol SHALL NOT expose accessor getters
(`get_path`/`get_quote`/`get_hostname`), state-transition wrappers
(`occupy`/`release`/`update_machine`), or the monitor mechanism
(`install_monitor`/`cancel_monitor`) — those are on `MachineSession`.
The Protocol SHALL NOT expose `get_machine_state` — callers use
`get_session(node_id).machine` instead.

#### Scenario: Repository satisfies Protocol structurally

- **WHEN** a class implements all `MachineRepository` methods with matching signatures (keyed by `NodeId`/`Node`)
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

#### Scenario: Register and list connected sessions

- **WHEN** `await repository.connect(node, ...)` returns a session `s`, then `list_connected()` is called
- **THEN** returns a list containing `s`

#### Scenario: Filter free sessions by platform

- **WHEN** `list_free(["linux", "debian-12"])` is called
- **THEN** returns only sessions whose `machine.state == FREE` and `machine.platform` is "linux" or "debian-12", sorted oldest-first by `session.machine.free_since`

#### Scenario: get_session returns None for unknown node_id

- **WHEN** `get_session(NodeId(99))` is called for a node_id that has never been connected (or has been disconnected)
- **THEN** returns `None`

#### Scenario: get_session returns the live session

- **WHEN** `await repository.connect(node, ...)` returns `s`, then `get_session(node.node_id)` is called
- **THEN** returns `s` (the same object)

#### Scenario: Repository supports contains

- **WHEN** `NodeId(1)` has a live session and `NodeId(2)` does not
- **THEN** `repository.contains(NodeId(1))` returns `True`, `NodeId(1) in repository` returns `True`, and `repository.contains(NodeId(2))` returns `False`

#### Scenario: Repository supports len

- **WHEN** the repository holds three live sessions
- **THEN** `len(repository)` returns `3`

#### Scenario: Repository exposes no state-transition wrappers

- **WHEN** the `MachineRepository` Protocol is inspected for `occupy`/`release`/`update_machine` methods
- **THEN** none are present — state transitions are on `MachineSession`

#### Scenario: Repository exposes no monitor mechanism

- **WHEN** the `MachineRepository` Protocol is inspected for `install_monitor`/`cancel_monitor` methods
- **THEN** none are present — the monitor mechanism is on `MachineSession`

### Requirement: SSHMachineRepository implements MachineRepository

The system SHALL provide an `SSHMachineRepository` class in
`yascheduler/infra/ssh/repository.py` that satisfies the
`MachineRepository` Protocol. The repository SHALL own a single dict
`_sessions: dict[NodeId, SSHMachineSession]` keyed by `NodeId`. The
repository SHALL NOT own a `_monitors` dict — monitors live on
sessions. The repository SHALL NOT define `_machines`, `_MachineState`,
or `_get_machine_state`.

`connect(node: Node, ...)` SHALL use a two-method pattern: inner
`_connect_impl` decorated with `@my_backoff_exc()` retries on
`SSHRetryExc`; outer `connect` translates exhausted
`(asyncssh.misc.Error, OSError)` to `MachineConnectionError`. `connect`
SHALL open the SSH connection via `_open_connection` (using `node.ip`
as the asyncssh host), detect platform via `_detect_platform(conn,
ADAPTERS)` from `infra/ssh/platform/`, initialize paths via `_init_paths`
from `infra/ssh/platform/`, read `ncpus` via
`adapter.get_cpu_cores(make_run_fn(conn, adapter))`, construct a
`ConnectedMachine` carrying `node_id=node.node_id`, construct an
`SSHMachineSession` from the connection + snapshot + adapter + paths,
store it in `_sessions[node.node_id]`, and return it.

`disconnect(node_id)` SHALL pop `_sessions[node_id]` (early return if
absent), then `await session._close()`. The pop-before-await ordering
SHALL be preserved — `_sessions.pop(node_id)` happens BEFORE any await
yields control, and `session._close()` sets `is_closed = True`
synchronously before its own first await.

`disconnect_all()` SHALL iterate `list(self._sessions)` and call
`disconnect(node_id)` per session. `disconnect_all()` SHALL be
idempotent (it iterates a snapshot, so concurrent disconnects are
safe).

`disconnect(node_id)` SHALL be scoped to the targeted node. It SHALL
cancel only the background monitor task registered for `node_id` (if
present, via the session's `cancel_monitor`) and SHALL NOT cancel
monitors registered for any other machine. After `disconnect(node_id)`
returns, the monitors for every other still connected machine SHALL
remain alive and uncanceled.

The connection-building bits (`MySSHClient`, `DEFAULT_CONN_OPTS`,
`_resolve_tunnel`) SHALL live in `infra/ssh/repository.py` and be used
by `_open_connection`.

The repository SHALL NOT expose `_get_machine_state`,
`register_machine`, `keys`, `items`, `get_machine_state`,
`install_monitor`, `cancel_monitor`, `occupy`, `release`,
`update_machine`, `get_path`, `get_quote`, `get_hostname`,
`get_adapter`, `get_platforms`, `get_data_dir`, `get_engines_dir`,
`get_tasks_dir`, or `get_conn`.

#### Scenario: Repository imported from correct module

- **WHEN** `SSHMachineRepository` is imported
- **THEN** it is imported from `yascheduler.infra.ssh.repository`

#### Scenario: Repository owns only the sessions dict keyed by NodeId

- **WHEN** `SSHMachineRepository.__init__` is inspected
- **THEN** the instance has `_sessions: dict[NodeId, SSHMachineSession]` and does NOT have `_machines` or `_monitors`

#### Scenario: disconnect delegates teardown to session

- **WHEN** `await repository.disconnect(NodeId(1))` runs
- **THEN** `_sessions[NodeId(1)]` is popped, then `await session._close()` is called; the repository does NOT directly cancel any monitor task or close any connection

#### Scenario: Repository has no _MachineState

- **WHEN** `yascheduler.infra.ssh.repository` is inspected
- **THEN** no `_MachineState` class is defined — sessions live in `infra/ssh/session.py` as `SSHMachineSession`

#### Scenario: Repository has no _get_machine_state

- **WHEN** `SSHMachineRepository` is inspected for `_get_machine_state`
- **THEN** the method is absent — operations receive sessions directly and never reach into repository internals

#### Scenario: Disconnect single machine

- **WHEN** `repository.disconnect(NodeId(1))` is called on a connected machine
- **THEN** the SSH connection for that node is closed, the machine is removed from the registry, and any monitor registered for that node is cancelled and awaited

#### Scenario: Disconnect does not touch other machines' monitors

- **WHEN** machines A, B, and C are connected (keyed by their respective NodeIds), each has an occupancy monitor installed via `operations.occupancy.start_occupancy_check`, and `repository.disconnect(B.node_id)` is called
- **THEN** only the monitor registered for B is cancelled, the monitors for A and C remain alive (not cancelled) and remain registered for their respective NodeIds, and machines A and C stay connected

#### Scenario: Disconnect unknown node_id

- **WHEN** `repository.disconnect(NodeId(99))` is called for a node_id with no registered machine
- **THEN** no exception is raised, no monitor for any other node is cancelled, and the registry of connected machines is unchanged

#### Scenario: Disconnect all

- **WHEN** `repository.disconnect_all()` is called
- **THEN** every connected machine's SSH connection is closed, every connected machine is removed from the registry, and every registered monitor is cancelled

### Requirement: Session is returned by repository and resolved per-tick by the orchestrator

`SSHMachineRepository.connect(node: Node, ...) -> MachineSession` SHALL
return the newly-constructed session. `list_free`/`list_connected`
SHALL return `list[MachineSession]`. `get_session(node_id: NodeId) ->
MachineSession | None` SHALL return the live session for `node_id` or
`None` (after disconnect).

The orchestrator SHALL resolve a session via
`repository.get_session(task.allocated_node_id)` at each consumer tick
where it needs to operate on a machine. The orchestrator SHALL NOT
cache session references across await boundaries: a cached reference
survives `disconnect` and silently mutates an orphaned session.

Use cases (`allocate_task`, `consume_task`) SHALL receive sessions as
parameters (resolved by the orchestrator) or resolve them via
`repository.get_session(node_id)` when they need to call an operations
method; they SHALL NOT cache sessions.

#### Scenario: connect returns a session

- **WHEN** `await repository.connect(node, username=..., client_keys=..., ...)` returns
- **THEN** the return value is a `MachineSession` whose `ip == node.ip`, `machine.node_id == node.node_id`, `machine.state == FREE`, `machine.platform`, and `machine.ncpus` match the connection

#### Scenario: get_session returns None after disconnect

- **WHEN** `repository.disconnect(node_id)` has completed and `repository.get_session(node_id)` is then called
- **THEN** the return value is `None`

#### Scenario: Orchestrator resolves session per tick

- **WHEN** the orchestrator's `_task_consumer_consumer` runs for a given task
- **THEN** it calls `self._repository.get_session(task.allocated_node_id)` once at the top and threads the result (or `None` for `MACHINE_GONE` handling) through the consumer body; it does NOT read a cached session attribute across ticks

#### Scenario: list_free returns sessions

- **WHEN** `repository.list_free(["linux"])` is called and the repository holds two FREE linux sessions
- **THEN** the return value is `list[MachineSession]` of length 2, sorted oldest-first by `session.machine.free_since`