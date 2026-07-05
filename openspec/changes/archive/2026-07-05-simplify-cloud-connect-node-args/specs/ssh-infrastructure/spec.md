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
longer a positional parameter or a dict key. The transport login user
and port likewise survive only as `node.username` and `node.port` read
inside `connect`; they are NOT separate parameters.

**Collection lifecycle:**
- `connect(node: Node, client_keys: Sequence[PurePath] | None, *, connect_timeout: int | None = None, data_dir: PurePath | None = None, engines_dir: PurePath | None = None, tasks_dir: PurePath | None = None, jump_host: str | None = None, jump_username: str | None = None) -> MachineSession` (async) — constructs and registers an `SSHMachineSession` keyed by `node.node_id`, returns it. The asyncssh transport uses `node.ip` as the host address, `node.username` as the login user, and `node.port` as the port. `connect` SHALL NOT take `username` or `port` parameters — they are read from `node`. `client_keys` remains a parameter (it is not a `Node` attribute); `jump_host`/`jump_username`/`connect_timeout`/`data_dir`/`engines_dir`/`tasks_dir` remain per-connection parameters.
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

#### Scenario: connect takes no username or port parameters

- **WHEN** the `MachineRepository.connect` signature is inspected
- **THEN** it has no `username` and no `port` parameter; the login user is `node.username` and the port is `node.port`, both read from the `node` argument

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
