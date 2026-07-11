## MODIFIED Requirements

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
`node.username` as the login user, and `node.port` as the port. On
connection failure, `MachineConnectionError(node.node_id, node.hostname,
str(err))` SHALL be raised (carrying both identity and address).

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

### Requirement: MachineSession port

The system SHALL define a `@runtime_checkable` `MachineSession`
Protocol representing the connected-machine entity handle. The session
is what operations methods operate on; the repository hands sessions out
and tracks them by `NodeId`. The Protocol SHALL NOT include collection
lifecycle, queries, or repository keying — those are `MachineRepository`.

**Domain face:**
- `hostname: str` (read-only property) — the machine hostname (the asyncssh transport host). This property replaces the former `ip` property; the `ip` property is removed. The Domain-face `hostname` and the former adapter-derived `hostname` accessor (which returned `conn_opts.host`) merge into a single `hostname` property — they always carried the same value (the asyncssh host passed at connect time).
- `machine: ConnectedMachine` (read-only property) — the current snapshot; mutate via `occupy`/`release`/`update`
- `is_closed: bool` (read-only property) — `True` after `_close()` has been invoked (rollback paths check this to detect mid-deploy disconnect)
- `occupy() -> None` (sync) — read-modify-write transitioning the snapshot to BUSY
- `release() -> None` (sync) — read-modify-write transitioning the snapshot to FREE with `free_since = time.monotonic()`
- `update(machine: ConnectedMachine) -> None` (sync) — replace the internal snapshot (used by rollback paths)

**Connect-time config (read-only properties, set at `connect`):**
- `adapter: RemoteMachineAdapter`
- `platforms: Sequence[str]`
- `data_dir: PurePath`
- `engines_dir: PurePath`
- `tasks_dir: PurePath`

**Adapter-derived accessors (read-only properties):**
- `path: type[PurePath]` — `adapter.path`
- `quote: QuoteCallable` — `adapter.quote`

**Base primitives (async, on the session directly):**
- `run(cmd: str) -> ProcessResult` (async)
- `run_full(cmd: str) -> SSHCompletedProcess` (async)
- `run_bg(cmd: str, *, cwd: str | None = None) -> None` (async)
- `upload(local: Path, remote: str) -> None` (async)
- `open_sftp() -> AsyncContextManager[SFTPClient]` (async) — async context manager yielding an SFTP client
- `get_cpu_cores() -> int` (async) — retries on `SSHRetryExc` (idempotent read)
- `setup_node(engines: EngineRepository) -> None` (async)
- `pgrep(pattern: str | Pattern[str], full: bool = True) -> AsyncGenerator[ProcessInfo, None]` (async)
- `list_processes() -> AsyncGenerator[ProcessInfo, None]` (async)

**Monitor mechanism (Engine-agnostic; on the session, NOT on the repository):**
- `install_monitor(*, interval: float, check_factory: Callable[[], Awaitable[bool]], on_free: Callable[[], None]) -> None` (sync) — installs an `asyncio.Task` on the session that sleeps `interval`, calls `check_factory()`, and calls `on_free()` then breaks when the check returns `False`. Re-installing cancels the prior monitor before installing the new one. Idempotent on a closed session: returns immediately without installing if `is_closed` is `True`.
- `cancel_monitor() -> None` (sync) — cancels the session's monitor (if any); does NOT await

`MachineSession` is `@runtime_checkable`. The Protocol SHALL NOT
reference `Engine`; `install_monitor` is generic over
`Callable[[], Awaitable[bool]]` and `Callable[[], None]`.

#### Scenario: occupy transitions snapshot to BUSY

- **WHEN** `session.occupy()` is called on a session whose `machine.state` is FREE
- **THEN** `session.machine.state` becomes BUSY

#### Scenario: install_monitor replaces prior monitor

- **WHEN** `session.install_monitor(...)` is called on a session that already has a live monitor
- **THEN** the prior monitor's `asyncio.Task` is cancelled before the new monitor is installed on the same session, without affecting any other session's monitor

### Requirement: SSHMachineSession implements MachineSession

The system SHALL provide an `SSHMachineSession` class that satisfies the
`MachineSession` Protocol. The session SHALL be constructed by
`SSHMachineRepository.connect` with: `hostname`, an open `SSHClientConnection`,
`SSHClientConnectionOptions`, a `ConnectedMachine` (initial snapshot with
`state=FREE`, `free_since=time.monotonic()`), `adapter`, `platforms`,
`data_dir`, `engines_dir`, `tasks_dir`.

The session SHALL own its own teardown via a `_close()` coroutine,
invoked only by `SSHMachineRepository.disconnect`. `_close()` SHALL be
idempotent: if `is_closed` is already `True`, it returns immediately.
Otherwise it SHALL:
1. Set the closed flag synchronously (BEFORE any await).
2. Pop and cancel the monitor task (if any).
3. Await the cancelled monitor's task (suppressing `asyncio.CancelledError`).
4. Close the SSH connection and await `wait_closed()`.

`SSHMachineSession`'s base primitives SHALL use the session's own `conn`
and `adapter` directly — NO hostname-keyed lookup, NO call into the repository.
`run_full` SHALL retry on `SSHRetryExc` via the `@my_backoff_exc()` decorator.
`setup_node` SHALL accept `engines: EngineRepository` and use the session's
own `adapter.setup_node(...)`.

#### Scenario: Session owns its monitor task

- **WHEN** `session.install_monitor(...)` is called
- **THEN** the resulting `asyncio.Task` is stored on the session and is NOT registered in any repository-level dict

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

- **WHEN** `await repository.connect(node, ...)` returns
- **THEN** the return value is a `MachineSession` whose `hostname == node.hostname`, `machine.node_id == node.node_id`, `machine.state == FREE`, `machine.platform`, and `machine.ncpus` match the connection