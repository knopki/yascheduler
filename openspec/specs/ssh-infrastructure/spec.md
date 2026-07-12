# SSH Infrastructure

## Purpose

Provide SSH machine infrastructure split across SSHMachineRepository
(connected-machine collection lifecycle, queries, state transitions,
occupancy-monitor mechanism) and SSHMachineSession (per-machine command
execution, SFTP transfer, process inspection, node setup, task deployment,
output download, and occupancy check logic). Both implement the
MachineRepository and MachineSession domain ports respectively using
asyncssh for SSH connections and SFTP, with retry logic on idempotent
operations.

## Requirements

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

### Requirement: MachineSession port

The system SHALL define a `@runtime_checkable` `MachineSession`
Protocol representing the connected-machine entity handle. The session
is what operations methods operate on; the repository hands sessions out
and tracks them by IP. The Protocol SHALL NOT include collection
lifecycle, queries, or repository keying — those are `MachineRepository`.

**Domain face:**
- `hostname: str` (read-only property) — the machine hostname (the asyncssh transport host). This property replaces the former `ip` property; the `ip` property is removed.
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

### Requirement: download_outputs per-file SFTP isolation and retry

The system SHALL provide `OutputDownloader.download_outputs(session,
remote_dir, local_dir, files, task_id)` returning
`(local_folder: str, remote_folder: str, transient_errors, permanent_errors)`.
The method SHALL catch all per-file exceptions and classify each into
`transient_errors` (instances of `SFTPRetryExc`) or `permanent_errors`
(all other caught exceptions). Session-level failures SHALL be caught and
returned in `transient_errors`. The method SHALL NOT raise.

The method SHALL open a FRESH SFTP client per file in the per-file loop,
so a dropped SFTP connection on one file invalidates only that file's
retries. The per-file retry (fibonacci, max_time=60, `SFTPRetryExc`) SHALL
wrap each `sftp.get` call individually.

The method SHALL remove the remote directory tree only ONCE, after the
per-file loop completes, and only when BOTH error lists are empty. When
either list is non-empty, the remote directory SHALL NOT be removed.

The `local_folder`/`remote_folder` return values are `str(local_dir)` and
`remote_dir` verbatim.

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `operations.download_outputs(session, remote_dir, local_dir, files, task_id)` is called
- **THEN** a FRESH SFTP client is opened per file in the loop, each file is downloaded with per-file retry, per-file exceptions are classified into `transient_errors` and `permanent_errors`, and `(local_folder=str(local_dir), remote_folder=remote_dir, transient_errors, permanent_errors)` is returned

### Requirement: start_task_on_machine rolls back BUSY on failure

The `TaskDeployer.start_task_on_machine` method SHALL roll back the
session-level BUSY marking on any deploy or spawn failure. The method
SHALL mark the session BUSY at `session.occupy()` before performing the
deploy and spawn steps. If any exception (including `CancelledError`)
escapes, the method SHALL roll back by calling `session.release()`, then
re-raise the original exception. The rollback SHALL run under
`except BaseException`.

The rollback SHALL be defensive against concurrent state changes:
- If the session is closed (`session.is_closed` is `True`), log a warning and re-raise without rollback.
- If the session is open but not `BUSY`, log a warning, still call `session.release()`, and re-raise.
- Otherwise log an info line and re-raise.

This requirement governs the session-level occupancy marker only; the
DB task status and orchestrator's in-memory `mark_running()` are owned
by the caller and unaffected by this rollback.

#### Scenario: Upload failure rolls back BUSY

- **WHEN** `TaskDeployer.start_task_on_machine` calls `session.occupy()` marking the session BUSY, then the deploy step raises
- **THEN** the `except BaseException` handler calls `session.release()`, logs an info line, and re-raises the original exception
- **AND** the session's `machine.state` is `FREE` after the call returns

### Requirement: `_write_remote_file` re-raises non-SFTP exceptions

The `_write_remote_file` helper SHALL re-raise any exception that occurs
during the SFTP file write. It SHALL NOT swallow non-SFTP exceptions
(e.g. `binascii.Error`, `TypeError`, `UnicodeEncodeError`, `KeyError`).
The helper MAY catch `asyncssh.misc.Error` specifically to log the
structured SFTP `code` and `reason` fields and SHALL re-raise immediately
after logging. The propagation is the abort signal for `start_task_on_machine`.

#### Scenario: Non-SFTP exception re-raised by _write_remote_file
- **WHEN** `_write_remote_file` encounters a `TypeError` during SFTP write
- **THEN** the exception is re-raised immediately (not swallowed)

### Requirement: Retry and backoff policy

The system SHALL apply `@my_backoff_exc()` (fibonacci, max_time=60,
`SSHRetryExc`) ONLY to idempotent operations: `get_cpu_cores` (pure read)
and connection establishment. The system SHALL NOT apply
`@my_backoff_exc()` to `run_bg` and SHALL NOT apply `@my_backoff_sftp()`
to `upload` or `download` — these are non-idempotent (a successful remote
side-effect followed by a lost client confirmation would produce a duplicate
on retry). `download_outputs` SHALL continue to use `my_backoff_sftp()` as
the per-file retry wrapper inside the per-file loop.

SSH connections SHALL be retried on transient failures using the `backoff`
library with fibonacci backoff and `max_time=60`. The repository SHALL use
a two-method pattern for `connect()`: inner method with
`@my_backoff_exc()` (retries on `SSHRetryExc`), outer `connect` translates
exhausted `(asyncssh.misc.Error, OSError)` to `MachineConnectionError`.

#### Scenario: get_cpu_cores retries on SSH failure

- **WHEN** `session.get_cpu_cores()` fails with a retryable SSH exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds (idempotent read — retry is safe)

### Requirement: Occupancy monitoring

The system SHALL periodically check if an engine process is still
running on a machine and update the machine state to FREE when the
process exits. The check logic lives on the `OccupancyChecker` class;
the monitor mechanism (`install_monitor`/`cancel_monitor`) lives on
`SSHMachineSession`.

The `OccupancyChecker.start_occupancy_check(session, config)` SHALL
additionally call `session.occupy()` before installing the monitor
(so that the system sees BUSY while the task runs). The monitor's
`on_free` SHALL call `session.release()`.

#### Scenario: Process exits, machine becomes free

- **WHEN** occupancy check detects the engine process has exited
- **THEN** the `ConnectedMachine` state is updated to FREE with `free_since` set (via `session.release()` invoked as the monitor's `on_free`)

### Requirement: Module layout

Platform-specific modules SHALL live in the SSH platform package.
`ProcessInfo` (frozen dataclass with fields `pid: int`, `name: str`,
`command: str`) SHALL be defined in the platform protocol module.
`ADAPTERS`, platform detection, path init, and `MAX_SESSIONS` SHALL
live in the platform package. Platform modules SHALL import `Engine`,
`EngineRepository`, and `Deploy*` types from `yascheduler.domain`.

#### Scenario: ProcessInfo defined in platform protocol module
- **WHEN** the platform protocol module is inspected
- **THEN** `ProcessInfo` is a frozen dataclass with fields `pid: int`, `name: str`, `command: str`
