## MODIFIED Requirements

### Requirement: MachineRepository port

The system SHALL define a `@runtime_checkable` `MachineRepository`
Protocol representing the connected-machine collection. The Protocol
SHALL NOT include operations on a single machine (exec, SFTP, deploy,
download, occupancy-check logic, monitor mechanism) — those are
`MachineSession`.

The collection is keyed by `NodeId`, not by ip. The transport address,
login user, port, and jump-leg parameters survive ONLY as fields on
`node` read inside `connect`; they are NOT separate parameters.

**Collection lifecycle:**
- `connect(node: Node, client_keys: Sequence[PurePath] | None, *, connect_timeout: int | None = None, data_dir: PurePath | None = None, engines_dir: PurePath | None = None, tasks_dir: PurePath | None = None) -> MachineSession` (async) — constructs and registers an `SSHMachineSession` keyed by `node.node_id`, returns it. The asyncssh transport uses `node.hostname` as the host address, `node.username` as the login user, `node.port` as the port, and `node.jump_host` / `node.jump_port` / `node.jump_username` to build the tunnel leg. `connect` SHALL NOT take `username`, `port`, `jump_host`, or `jump_username` parameters — they are read from `node`.
- `disconnect(node_id: NodeId) -> None` (async) — pops the session keyed by `node_id` and delegates teardown to `session._close()`
- `disconnect_all() -> None` (async) — unchanged

**Queries:**
- `list_free(platforms: list[str] | None) -> list[MachineSession]` (sync) — FREE sessions filtered by `session.machine.platform`, oldest-first by `session.machine.free_since`
- `list_connected() -> list[MachineSession]` (sync) — unchanged
- `get_session(node_id: NodeId) -> MachineSession | None` (sync) — the live session for `node_id`, or `None` after disconnect
- `contains(node_id: NodeId) -> bool` (sync) — explicit form of `__contains__`
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

- **WHEN** a class implements all `MachineRepository` methods with matching signatures (keyed by `NodeId`/`Node`, no `jump_host` / `jump_username` / `username` / `port` parameters on `connect`)
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

#### Scenario: Filter free sessions by platform

- **WHEN** `list_free(["linux", "debian-12"])` is called
- **THEN** returns only sessions whose `machine.state == FREE` and `machine.platform` is "linux" or "debian-12", sorted oldest-first by `session.machine.free_since`

#### Scenario: connect reads jump identity from Node

- **WHEN** `await repository.connect(node, client_keys)` is called on a node with `jump_host="bastion.example.com"`, `jump_port=2222`, `jump_username="jumper"`
- **THEN** the asyncssh tunnel leg is built from `node.jump_host` / `node.jump_port` / `node.jump_username` (no separate `jump_host` / `jump_username` arguments are passed to `connect`)

#### Scenario: connect omits tunnel when Node.jump_host is None

- **WHEN** `await repository.connect(node, client_keys)` is called on a node with `jump_host=None`
- **THEN** asyncssh is invoked with `tunnel=None` (direct connection, no bastion leg)

### Requirement: SSHMachineRepository implements MachineRepository

The system SHALL provide an `SSHMachineRepository` class that satisfies
the `MachineRepository` Protocol. The repository SHALL own a single dict
of sessions keyed by `NodeId`.

`connect(node: Node, ...)` SHALL use a two-method pattern: inner method
decorated with `@my_backoff_exc()` retries on `SSHRetryExc`; outer
`connect` translates exhausted `(asyncssh.misc.Error, OSError)` to
`MachineConnectionError`. `connect` SHALL open the SSH connection, detect
platform via the platform package, initialize paths via the platform
package, read `ncpus` via `adapter.get_cpu_cores(...)`, construct a
`ConnectedMachine`, construct an `SSHMachineSession`, store it keyed by
`node.node_id`, and return it.

`connect` SHALL read `node.hostname` as the asyncssh host address,
`node.username` as the login user, and `node.port` as the port. The
tunnel leg SHALL be built from `node.jump_host` / `node.jump_port` /
`node.jump_username` via an `SSHClientConnectionOptions` object that
inherits `client_keys` / `known_hosts` / `connect_timeout` from the
destination leg. When `node.jump_host` is `None`, no tunnel is built
(`tunnel=None`). On connection failure, `MachineConnectionError(node.node_id,
node.hostname, str(err))` SHALL be raised (carrying both identity and
address).

`disconnect(node_id)` SHALL pop the session for `node_id` (early return if
absent), then `await session._close()`. The pop-before-await ordering
SHALL be preserved. `disconnect_all()` SHALL iterate a snapshot of keys
and call `disconnect(node_id)` per session; it SHALL be idempotent.

`disconnect(node_id)` SHALL be scoped to the targeted node — it SHALL
cancel only the monitor registered for `node_id` and SHALL NOT cancel
monitors for any other machine.

#### Scenario: Repository owns only the sessions dict keyed by NodeId

- **WHEN** `SSHMachineRepository.__init__` is inspected
- **THEN** the instance has a dict of sessions keyed by `NodeId` and does NOT have `_machines` or `_monitors`

#### Scenario: Tunnel leg reuses destination-leg options

- **WHEN** `connect` is called with `client_keys=[Path("/etc/yascheduler/keys/id_rsa")]` and `connect_timeout=10` on a node with `jump_host="bastion.example.com"`
- **THEN** the `SSHClientConnectionOptions` passed as asyncssh `tunnel=` carries the same `client_keys`, `known_hosts=None`, and `connect_timeout=10` as the destination leg
