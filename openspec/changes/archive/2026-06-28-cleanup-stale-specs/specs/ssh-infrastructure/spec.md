## ADDED Requirements

### Requirement: MachineRepository port

The system SHALL define a `@runtime_checkable` `MachineRepository`
Protocol in `yascheduler/domain/ports.py` representing the
connected-machine collection. The Protocol SHALL NOT include operations
on a single machine (exec, SFTP, deploy, download, occupancy-check
logic, monitor mechanism) — those are `MachineSession` and
`MachineOperations`.

**Collection lifecycle:**
- `connect(ip: str, username: str, client_keys: Sequence[PurePath] | None, *, port: int = 22, connect_timeout: int | None = None, data_dir: PurePath | None = None, engines_dir: PurePath | None = None, tasks_dir: PurePath | None = None, jump_host: str | None = None, jump_username: str | None = None) -> MachineSession` (async) — constructs and registers an `SSHMachineSession`, returns it
- `disconnect(ip: str) -> None` (async) — pops the session and delegates teardown to `session._close()`
- `disconnect_all() -> None` (async)

**Queries:**
- `list_free(platforms: list[str] | None) -> list[MachineSession]` (sync) — FREE sessions filtered by `session.machine.platform`, oldest-first by `session.machine.free_since`
- `list_connected() -> list[MachineSession]` (sync)
- `get_session(ip: str) -> MachineSession | None` (sync) — the live session for `ip`, or `None` after disconnect
- `contains(ip: str) -> bool` (sync) — explicit form of `__contains__`; preserved for the three production callers (`deallocate_nodes.py`, `orchestrator.py` ×2)
- `__len__() -> int` (sync)
- `__contains__(ip: str) -> bool` (sync) — supports `ip in repository`

`MachineRepository` is `@runtime_checkable`. The Protocol SHALL NOT
reference `Engine`. The Protocol SHALL NOT expose accessor getters
(`get_path`/`get_quote`/`get_hostname`), state-transition wrappers
(`occupy`/`release`/update_machine`), or the monitor mechanism
(`install_monitor`/`cancel_monitor`) — those are on `MachineSession`.
The Protocol SHALL NOT expose `get_machine_state` — callers use
`get_session(ip).machine` instead.

#### Scenario: Repository satisfies Protocol structurally

- **WHEN** a class implements all `MachineRepository` methods with matching signatures
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

#### Scenario: Register and list connected sessions

- **WHEN** `await repository.connect("10.0.0.1", ...)` returns a session `s`, then `list_connected()` is called
- **THEN** returns a list containing `s`

#### Scenario: Filter free sessions by platform

- **WHEN** `list_free(["linux", "debian-12"])` is called
- **THEN** returns only sessions whose `machine.state == FREE` and `machine.platform` is "linux" or "debian-12", sorted oldest-first by `session.machine.free_since`

#### Scenario: get_session returns None for unknown IP

- **WHEN** `get_session("10.0.0.99")` is called for an IP that has never been connected (or has been disconnected)
- **THEN** returns `None`

#### Scenario: get_session returns the live session

- **WHEN** `await repository.connect("10.0.0.1", ...)` returns `s`, then `get_session("10.0.0.1")` is called
- **THEN** returns `s` (the same object)

#### Scenario: Repository supports contains

- **WHEN** `"10.0.0.1"` has a live session and `"10.0.0.2"` does not
- **THEN** `repository.contains("10.0.0.1")` returns `True`, `"10.0.0.1" in repository` returns `True`, and `repository.contains("10.0.0.2")` returns `False`

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
`_sessions: dict[str, SSHMachineSession]` keyed by IP. The repository
SHALL NOT own a `_monitors` dict — monitors live on sessions. The
repository SHALL NOT define `_machines`, `_MachineState`, or
`_get_machine_state`.

`connect(ip, ...)` SHALL use a two-method pattern: inner `_connect_impl`
decorated with `@my_backoff_exc()` retries on `SSHRetryExc`; outer
`connect` translates exhausted `(asyncssh.misc.Error, OSError)` to
`MachineConnectionError`. `connect` SHALL open the SSH connection via
`_open_connection`, detect platform via `_detect_platform(conn,
ADAPTERS)` from `infra/ssh/platform/`, initialize paths via `_init_paths`
from `infra/ssh/platform/`, read `ncpus` via
`adapter.get_cpu_cores(make_run_fn(conn, adapter))`, construct a
`ConnectedMachine`, construct an `SSHMachineSession` from the connection
+ snapshot + adapter + paths, store it in `_sessions[ip]`, and return
it.

`disconnect(ip)` SHALL pop `_sessions[ip]` (early return if absent),
then `await session._close()`. The pop-before-await ordering SHALL be
preserved — `_sessions.pop(ip)` happens BEFORE any await yields control,
and `session._close()` sets `is_closed = True` synchronously before its
own first await.

`disconnect_all()` SHALL iterate `list(self._sessions)` and call
`disconnect(ip)` per session. `disconnect_all()` SHALL be idempotent
(it iterates a snapshot, so concurrent disconnects are safe).

`disconnect(ip)` SHALL be scoped to the targeted IP. It SHALL cancel
only the background monitor task registered for `ip` (if present, via
the session's `cancel_monitor`) and SHALL NOT cancel monitors
registered for any other machine. After `disconnect(ip)` returns, the
monitors for every other still connected machine SHALL remain alive and
uncancelased.

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

#### Scenario: Repository owns only the sessions dict

- **WHEN** `SSHMachineRepository.__init__` is inspected
- **THEN** the instance has `_sessions: dict[str, SSHMachineSession]` and does NOT have `_machines` or `_monitors`

#### Scenario: disconnect delegates teardown to session

- **WHEN** `await repository.disconnect("10.0.0.1")` runs
- **THEN** `_sessions["10.0.0.1"]` is popped, then `await session._close()` is called; the repository does NOT directly cancel any monitor task or close any connection

#### Scenario: Repository has no _MachineState

- **WHEN** `yascheduler.infra.ssh.repository` is inspected
- **THEN** no `_MachineState` class is defined — sessions live in `infra/ssh/session.py` as `SSHMachineSession`

#### Scenario: Repository has no _get_machine_state

- **WHEN** `SSHMachineRepository` is inspected for `_get_machine_state`
- **THEN** the method is absent — operations receive sessions directly and never reach into repository internals

#### Scenario: Disconnect single machine

- **WHEN** `repository.disconnect("10.0.0.1")` is called on a connected machine
- **THEN** the SSH connection for `10.0.0.1` is closed, the machine is removed from the registry, and any monitor registered for `10.0.0.1` is cancelled and awaited

#### Scenario: Disconnect does not touch other machines' monitors

- **WHEN** machines A, B, and C are connected, each has an occupancy monitor installed via `operations.occupancy.start_occupancy_check`, and `repository.disconnect("B")` is called
- **THEN** only the monitor registered for B is cancelled, the monitors for A and C remain alive (not cancelled) and remain registered for their respective IPs, and machines A and C stay connected

#### Scenario: Disconnect unknown IP

- **WHEN** `repository.disconnect("10.0.0.99")` is called for an IP with no registered machine
- **THEN** no exception is raised, no monitor for any other IP is cancelled, and the registry of connected machines is unchanged

#### Scenario: Disconnect all

- **WHEN** `repository.disconnect_all()` is called
- **THEN** every connected machine's SSH connection is closed, every connected machine is removed from the registry, and every registered monitor is cancelled

### Requirement: MachineSession port

The system SHALL define a `@runtime_checkable` `MachineSession` Protocol
in `yascheduler/domain/ports.py` representing the connected-machine
entity handle — the public counterpart to the dissolved private
`_MachineState`. The session is what `MachineOperations` methods operate
on; the repository hands sessions out and tracks them by IP. The
Protocol SHALL NOT include collection lifecycle, queries, or repository
keying — those are `MachineRepository`.

**Domain face:**
- `ip: str` (read-only property) — the machine IP, set at connect time
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
- `hostname: str` — `conn_opts.host`

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
- `install_monitor(*, interval: float, check_factory: Callable[[], Awaitable[bool]], on_free: Callable[[], None]) -> None` (sync) — installs an `asyncio.Task` on the session that sleeps `interval`, calls `check_factory()`, and calls `on_free()` then breaks when the check returns `False`. Re-installing cancels the prior monitor before installing the new one. A done-callback clears `self._monitor_task` only when the slot still points at the same task (re-registration identity check). Idempotent on a closed session: returns immediately without installing if `is_closed` is `True`.
- `cancel_monitor() -> None` (sync) — cancels the session's monitor (if any); does NOT await

`MachineSession` is `@runtime_checkable`. The Protocol SHALL NOT
reference `Engine`; `install_monitor` is generic over
`Callable[[], Awaitable[bool]]` and `Callable[[], None]`.

#### Scenario: Session satisfies Protocol structurally

- **WHEN** a class implements all `MachineSession` methods with matching signatures
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

#### Scenario: occupy transitions snapshot to BUSY

- **WHEN** `session.occupy()` is called on a session whose `machine.state` is FREE
- **THEN** `session.machine.state` becomes BUSY

#### Scenario: release transitions snapshot to FREE

- **WHEN** `session.release()` is called on a session whose `machine.state` is BUSY
- **THEN** `session.machine.state` becomes FREE and `session.machine.free_since` is set to `time.monotonic()`

#### Scenario: install_monitor replaces prior monitor

- **WHEN** `session.install_monitor(...)` is called on a session that already has a live monitor
- **THEN** the prior monitor's `asyncio.Task` is cancelled before the new monitor is installed on the same session, without affecting any other session's monitor

#### Scenario: install_monitor done-callback is identity-checked

- **WHEN** a session's monitor completes and the session has since had a newer monitor installed
- **THEN** the done-callback SHALL NOT clear the newer monitor's slot; the session's `_monitor_task` still points at the newer task

#### Scenario: install_monitor no-ops on closed session

- **WHEN** `session.install_monitor(...)` is called on a session whose `is_closed` is `True`
- **THEN** no monitor is installed; the method returns without side effect

#### Scenario: cancel_monitor does not affect other sessions

- **WHEN** `session_a.cancel_monitor()` is called and `session_b` (a different session) also has a monitor
- **THEN** only `session_a`'s monitor is cancelled; `session_b`'s monitor remains alive

#### Scenario: is_closed is False on a freshly connected session

- **WHEN** a session is returned from `repository.connect(...)`
- **THEN** `session.is_closed` is `False`

### Requirement: SSHMachineSession implements MachineSession

The system SHALL provide an `SSHMachineSession` class in
`yascheduler/infra/ssh/session.py` that satisfies the `MachineSession`
Protocol. The session SHALL be constructed by `SSHMachineRepository.connect`
with: `ip`, an open `SSHClientConnection`, `SSHClientConnectionOptions`,
a `ConnectedMachine` (initial snapshot with `state=FREE`,
`free_since=time.monotonic()`), `adapter`, `platforms`, `data_dir`,
`engines_dir`, `tasks_dir`.

The session SHALL own its own teardown via a `_close()` coroutine,
invoked only by `SSHMachineRepository.disconnect`. `_close()` SHALL be
idempotent: if `is_closed` is already `True`, it returns immediately.
Otherwise it SHALL:

1. Set `self._closed = True` synchronously (BEFORE any await — preserves
   the disconnect-scope isolation invariant: a re-entry race cannot
   re-insert a cancelled task because the session reports closed before
   yielding control).
2. Pop and cancel `self._monitor_task` (if any).
3. Await the cancelled monitor's task (suppressing `asyncio.CancelledError`).
4. Close the SSH connection (if its transport is open) and await
   `wait_closed()`.

The session's `_monitor_task` attribute SHALL hold the monitor's
`asyncio.Task[None]` or `None`. The `install_monitor`/`cancel_monitor`
methods manipulate this attribute; the repository does not see it.

`SSHMachineSession`'s base primitives (`run`, `run_full`, `run_bg`,
`upload`, `open_sftp`, `get_cpu_cores`, `setup_node`, `pgrep`,
`list_processes`) SHALL use the session's own `conn` and `adapter`
directly — NO IP-keyed lookup, NO call into the repository, NO private
state reach-through. `run_full` SHALL retry on `SSHRetryExc` via the
`@my_backoff_exc()` decorator (the canonical copy of the decorator,
moved from `operations/base.py`).

`setup_node` SHALL accept `engines: EngineRepository` and use the
session's own `adapter.setup_node(...)` with `make_run_fn(conn, adapter)`
from `infra/ssh/platform/run_fn.py`.

The session SHALL NOT own connection-building logic — `MySSHClient`,
`DEFAULT_CONN_OPTS`, `_resolve_tunnel` stay in `repository.py` and are
used by `SSHMachineRepository._open_connection` to construct the
connection that the session receives.

#### Scenario: Session imported from correct module

- **WHEN** `SSHMachineSession` is imported
- **THEN** it is imported from `yascheduler.infra.ssh.session`

#### Scenario: Session owns its monitor task

- **WHEN** `session.install_monitor(...)` is called
- **THEN** the resulting `asyncio.Task` is stored on `session._monitor_task` and is NOT registered in any repository-level dict

#### Scenario: _close sets is_closed before first await

- **WHEN** `await session._close()` runs and reaches its first `await` (the monitor task cancellation)
- **THEN** `session.is_closed` is already `True` (set synchronously at the top of `_close`)

#### Scenario: _close is idempotent

- **WHEN** `await session._close()` is called twice in succession
- **THEN** the second call returns immediately without re-cancelling tasks or re-closing the connection

#### Scenario: Base primitives do not call the repository

- **WHEN** `session.run_full(cmd)` is called
- **THEN** the implementation reads `self._conn` and `self._adapter` directly; it does NOT call `SSHMachineRepository._get_machine_state` or any repository method

### Requirement: Session is returned by repository and resolved per-tick by the orchestrator

`SSHMachineRepository.connect(...) -> MachineSession` SHALL return the
newly-constructed session. `list_free`/`list_connected` SHALL return
`list[MachineSession]`. `get_session(ip) -> MachineSession | None` SHALL
return the live session for `ip` or `None` (after disconnect).

The orchestrator SHALL resolve a session via `repository.get_session(ip)`
at each consumer tick where it needs to operate on a machine. The
orchestrator SHALL NOT cache session references across await boundaries:
a cached reference survives `disconnect` and silently mutates an
orphaned session.

Use cases (`allocate_task`, `consume_task`) SHALL receive sessions as
parameters (resolved by the orchestrator) or resolve them via
`repository.get_session` when they need to call an operations method;
they SHALL NOT cache sessions.

#### Scenario: connect returns a session

- **WHEN** `await repository.connect(ip=..., username=..., client_keys=..., ...)` returns
- **THEN** the return value is a `MachineSession` whose `ip`, `machine.state == FREE`, `machine.platform`, and `machine.ncpus` match the connection

#### Scenario: get_session returns None after disconnect

- **WHEN** `repository.disconnect(ip)` has completed and `repository.get_session(ip)` is then called
- **THEN** the return value is `None`

#### Scenario: Orchestrator resolves session per tick

- **WHEN** the orchestrator's `_task_consumer_consumer` runs for a given `ip`
- **THEN** it calls `self._repository.get_session(ip)` once at the top and threads the result (or `None` for `MACHINE_GONE` handling) through the consumer body; it does NOT read a cached session attribute across ticks

#### Scenario: list_free returns sessions

- **WHEN** `repository.list_free(["linux"])` is called and the repository holds two FREE linux sessions
- **THEN** the return value is `list[MachineSession]` of length 2, sorted oldest-first by `session.machine.free_since`

### Requirement: MachineOperations port

The system SHALL define a `@runtime_checkable` `MachineOperations`
Protocol in `yascheduler/domain/ports.py` representing operations on a
single machine. The Protocol's methods SHALL take `session: MachineSession`.
The Protocol SHALL NOT itself declare base primitives (`run`, `run_full`,
`run_bg`, `upload`, `open_sftp`, `pgrep`, `list_processes`,
`get_cpu_cores`, `setup_node`) — those are on `MachineSession` and the
facade delegates to them. The Protocol SHALL declare the three use-case
methods that the orchestrator and use cases call:

**Use-case methods:**
- `start_task_on_machine(session: MachineSession, engine: Engine, task: Task, ncpus: int, engines_dir: PurePath) -> bool` (async)
- `download_outputs(session: MachineSession, remote_dir: str, local_dir: Path, files: list[str], task_id: int | None = None) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]` (async) — returns `(meta_add, transient_errors, permanent_errors)`
- `occupancy_check(session: MachineSession, config: Engine) -> bool` (async) — True if busy or SSH failed (safe default), False only when confirmed free
- `start_occupancy_check(session: MachineSession, config: Engine) -> None` (sync)

**Facade-pass-through methods (delegating to `session.*`):**
- `run(session: MachineSession, cmd: str) -> ProcessResult` (async)
- `run_full(session: MachineSession, cmd: str) -> SSHCompletedProcess` (async)
- `run_bg(session: MachineSession, cmd: str, *, cwd: str | None = None) -> None` (async)
- `get_cpu_cores(session: MachineSession) -> int` (async)
- `setup_node(session: MachineSession, engines: EngineRepository) -> None` (async)

The `config` parameter of `start_occupancy_check` and `occupancy_check`,
and the `engine` parameter of `start_task_on_machine`, SHALL be the
concrete `Engine` frozen dataclass from `yascheduler.domain.engine`.

`MachineOperations` is `@runtime_checkable`. The Protocol SHALL NOT
expose `download`, `get_sftp`, `pgrep`, `list_processes`, or `upload`
— the first is replaced by `download_outputs`; the rest are accessed
via the `session` parameter when collaborators need them internally.

#### Scenario: Operations satisfies Protocol structurally

- **WHEN** a class implements all `MachineOperations` methods with matching signatures
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

#### Scenario: Operations methods take MachineSession

- **WHEN** the `MachineOperations` Protocol's method signatures are inspected
- **THEN** each machine-reference parameter is typed `session: MachineSession` (not `ConnectedMachine`, not `ip: str`)

#### Scenario: start_occupancy_check composes session monitor

- **WHEN** `operations.start_occupancy_check(session, engine)` is called
- **THEN** the operations object calls `session.occupy()` (if `session.machine.state == FREE`) and `session.install_monitor(interval=engine.sleep_interval, check_factory=..., on_free=session.release)` — the operations object does NOT touch any repository attribute or `_monitors` dict

#### Scenario: occupancy_check defaults to busy on SSH failure

- **WHEN** `operations.occupancy_check(session, config)` runs and the underlying SSH check raises a `SSHRetryExc`
- **THEN** the method returns `True` (safe-default busy) rather than propagating the exception

### Requirement: SSHMachineOperations composition

The system SHALL provide an `SSHMachineOperations` class in
`yascheduler/infra/ssh/operations/` satisfying the `MachineOperations`
Protocol. The class SHALL receive a `MachineRepository` reference and a
logger at construction. The class SHALL compose three sibling
collaborators — `TaskDeployer`, `OutputDownloader`, `OccupancyChecker` —
exposed as the `deploy`, `download`, `occupancy` attributes
respectively.

The three collaborators SHALL be **stateless**: each SHALL take `(log)`
at construction and `(session, ...)` per method call. None of the three
SHALL hold a repository reference or an operations reference — they
operate exclusively via the `session` parameter.

`SSHMachineOperations` SHALL NOT declare base primitives itself. Its
methods (`run`, `run_full`, `run_bg`, `get_cpu_cores`, `setup_node`)
SHALL delegate to the corresponding session methods
(`session.run(cmd)`, etc.). Its use-case methods
(`start_task_on_machine`, `download_outputs`, `occupancy_check`,
`start_occupancy_check`) SHALL forward to the corresponding
collaborator method, passing the session through.

`SSHMachineOperations.start_task_on_machine(session, engine, task,
ncpus, engines_dir)` SHALL forward to
`self.deploy.start_task_on_machine(session, engine, task, ncpus,
engines_dir)`; similarly `download_outputs` to `self.download.*` and
`start_occupancy_check`/`occupancy_check` to `self.occupancy.*`.

Composition (not inheritance) SHALL be used. The collaborators SHALL
NOT subclass `SSHMachineOperations`. The narrow local Protocols
(`CommandExecutor`, `SftpProvider`, `StateAccessors`) defined by the
prior `decompose-ssh-gateway` change in `operations/base.py` SHALL be
**removed** — collaborators take sessions directly.

#### Scenario: Operations imports from operations package

- **WHEN** `SSHMachineOperations` is imported
- **THEN** it is imported from `yascheduler.infra.ssh.operations`

#### Scenario: Collaborators are stateless

- **WHEN** `TaskDeployer`, `OutputDownloader`, `OccupancyChecker` are constructed
- **THEN** each accepts only `(log)`; none holds a repository reference or an operations reference

#### Scenario: Deploy attribute is TaskDeployer

- **WHEN** `SSHMachineOperations(repository, log).deploy` is accessed
- **THEN** it is an instance of `TaskDeployer`

#### Scenario: start_task_on_machine forwards to deploy with session

- **WHEN** `operations.start_task_on_machine(session, engine, task, ncpus, engines_dir)` is called
- **THEN** the call forwards to `operations.deploy.start_task_on_machine(session, engine, task, ncpus, engines_dir)` with identical arguments

#### Scenario: download_outputs forwards to download with session

- **WHEN** `operations.download_outputs(session, remote_dir, local_dir, files, task_id)` is called
- **THEN** the call forwards to `operations.download.download_outputs(session, remote_dir, local_dir, files, task_id)` with identical arguments

#### Scenario: start_occupancy_check forwards to occupancy with session

- **WHEN** `operations.start_occupancy_check(session, engine)` is called
- **THEN** the call forwards to `operations.occupancy.start_occupancy_check(session, engine)` with identical arguments

#### Scenario: run delegates to session

- **WHEN** `operations.run(session, cmd)` is called
- **THEN** the implementation calls `session.run(cmd)` and returns its result; the operations object does NOT look up the session via the repository

### Requirement: download_outputs per-file SFTP isolation and retry

The system SHALL provide `SSHMachineOperations.download_outputs(session,
remote_dir, local_dir, files, task_id)` returning
`tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]],
list[tuple[str | None, Exception]]]` containing `(meta_add,
transient_errors, permanent_errors)`. The method SHALL catch all
per-file exceptions (including non-retry) and classify each into
`transient_errors` (instances of `SFTPRetryExc`) or `permanent_errors`
(all other caught exceptions, including `SFTPNoSuchFile`,
`SFTPPermissionDenied`, and bare `OSError` from local filesystem
writes). The method SHALL catch all session-level exceptions and return
them in `transient_errors` (a session-level failure is transient — the
remote directory is preserved for retry). The method SHALL NOT raise.

The method SHALL open a FRESH SFTP client (`session.open_sftp()` context)
per file in the per-file loop, so that a dropped SFTP connection on one
file invalidates only that file's retries and does not fail-fast the
remaining files on a dead shared client. The per-file retry
(`file_get_retry`, fibonacci, max_time=60, `SFTPRetryExc`) SHALL wrap
each `sftp.get` call individually.

The method SHALL remove the remote directory tree only ONCE, after the
per-file loop completes, and only when BOTH `transient_errors` AND
`permanent_errors` are empty — i.e. on full success only. When either
list is non-empty, the method SHALL NOT remove the remote directory tree
(any undownloaded file, whether transient or permanent, must remain
available for the next retry cycle or for operator debugging). The
rmtree SHALL use its own separate `session.open_sftp()` context (not a
per-file client).

`download_outputs` SHALL continue to use `my_backoff_sftp()` (defined
in `infra/ssh/operations/download.py`) as the per-file retry wrapper
inside the per-file loop.

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `operations.download_outputs(session, remote_dir, local_dir, files, task_id)` is called
- **THEN** a FRESH SFTP client is opened per file in the loop, each file is downloaded with per-file retry (`file_get_retry`, fibonacci, max_time=60, `SFTPRetryExc`), per-file exceptions are classified into `transient_errors` (instances of `SFTPRetryExc`) and `permanent_errors` (all other caught exceptions), and `(meta_add, transient_errors, permanent_errors)` is returned

#### Scenario: Remote directory removed only on full success

- **WHEN** `download_outputs` completes the per-file loop with both `transient_errors` and `permanent_errors` empty (full success)
- **THEN** the remote directory tree is removed ONCE via `sftp.rmtree` using a separate `session.open_sftp()` context after the loop

#### Scenario: Remote directory preserved on any errors

- **WHEN** `download_outputs` completes the per-file loop with `transient_errors` non-empty OR `permanent_errors` non-empty
- **THEN** the remote directory tree is NOT removed (undownloaded files — whether transient or permanent — remain available for retry or operator debugging)

#### Scenario: Per-file SFTP isolation bounds dead-connection blast radius

- **WHEN** `download_outputs` is downloading files [f1, f2, f3] and the SFTP connection drops during f2's transfer
- **THEN** f2's per-file retry exhausts on the dead f2 client and classifies f2 as transient, but f3 is downloaded via a FRESH `session.open_sftp()` client and retries normally (not fail-fast on a dead shared client)

#### Scenario: Download outputs catches all exceptions

- **WHEN** `download_outputs` encounters a non-retryable per-file exception
- **THEN** the exception is caught and classified into `permanent_errors`, not raised

#### Scenario: Session-level failure is transient and preserves remote dir

- **WHEN** `download_outputs` encounters a session-level failure (e.g. `session.open_sftp()` itself raises before the per-file loop body executes)
- **THEN** the exception is caught by the single outer `try/except Exception`, recorded in `transient_errors`, the remote directory is NOT removed, and the method returns without raising

### Requirement: start_task_on_machine rolls back BUSY on failure

The `start_task_on_machine` method SHALL roll back the session-level
BUSY marking on any deploy or spawn failure. The operations'
`start_task_on_machine(session, engine, task, ncpus,
engines_dir) -> bool` method (implemented in `TaskDeployer`, forwarded
from `SSHMachineOperations`) SHALL mark the session BUSY at
`session.occupy()` before performing the deploy (upload) and spawn
(`_exec_spawn_command` → `run_bg`) steps. If any exception (including
`CancelledError` during daemon shutdown) escapes the deploy or spawn
steps, the method SHALL roll back the session-level BUSY marking by
calling `session.update(session.machine.release())` (or
`session.release()` directly), then re-raise the original exception.
The rollback SHALL run under `except BaseException` so that
`CancelledError` is covered.

The rollback SHALL be defensive against concurrent state changes:

- If the session is closed (`session.is_closed` is `True`, e.g.
  `disconnect(ip)` ran concurrently), the method SHALL log a warning
  and re-raise without attempting the rollback.
- If the session is open but its state is not `BUSY` (a logic error
  somewhere), the method SHALL log a warning AND still call
  `session.release()` to enforce the invariant (FREE on failure), then
  re-raise.
- Otherwise the method SHALL log an info line (rollback succeeded) and
  re-raise.

This requirement governs the session-level occupancy marker only; the
DB task status and the orchestrator's in-memory `mark_running()` are
owned by the caller (`_try_start_on_machine` in
`allocate_task.py:114-144`) and are not affected by this rollback.

#### Scenario: Upload failure rolls back BUSY

- **WHEN** `start_task_on_machine` calls `session.occupy()` marking the session BUSY, then `_upload_task_data` raises (e.g. an `asyncssh.misc.Error` from `sftp.makedirs` or a propagated non-SFTP exception from `_write_remote_file`)
- **THEN** the method's `except BaseException` handler calls `session.release()` (or `session.update(session.machine.release())`), logging an info line, and re-raises the original exception
- **AND** the session's `machine.state` is `FREE` after the call returns (via the raised exception), so the next allocator tick can pick it up

#### Scenario: Spawn failure rolls back BUSY

- **WHEN** `start_task_on_machine` marks the session BUSY, the upload succeeds, then `_exec_spawn_command` → `run_bg` raises (e.g. `ChannelOpenError`, no longer retried per the amended Backoff requirement)
- **THEN** the method's `except BaseException` handler calls `session.release()`, logs an info line, and re-raises
- **AND** the session's `machine.state` is `FREE` after the call, and no occupancy monitor was installed (it installs only after successful spawn)

#### Scenario: CancelledError during deploy rolls back BUSY

- **WHEN** `start_task_on_machine` marks the session BUSY and the daemon is shut down mid-deploy (raising `CancelledError`) before spawn completes
- **THEN** the `except BaseException` handler catches the `CancelledError`, calls `session.release()`, logs an info line, and re-raises the `CancelledError`
- **AND** the session's `machine.state` is `FREE` (not stuck BUSY with no owner)

#### Scenario: Concurrent disconnect skips rollback with warning

- **WHEN** `start_task_on_machine` marks the session BUSY, then `repository.disconnect(session.ip)` runs concurrently and closes the session, and then the deploy or spawn raises
- **THEN** the rollback handler sees `session.is_closed` is `True`, logs a warning ("session already closed"), and re-raises the original exception without attempting `release()`

#### Scenario: Unexpected non-BUSY state still releases and warns

- **WHEN** `start_task_on_machine`'s rollback handler runs and the session's `machine.state` is other than `BUSY` (a logic error somewhere upstream)
- **THEN** the handler logs a warning ("unexpected state <state>, expected BUSY"), still calls `session.release()` to enforce the FREE-on-failure invariant, and re-raises
- **AND** the session's `machine.state` is `FREE` after the call

### Requirement: `_write_remote_file` re-raises non-SFTP exceptions

The `_write_remote_file` helper SHALL re-raise non-SFTP exceptions.
The deploy module's `_write_remote_file(sftp, path, data, log, mode)`
helper (in `infra/ssh/operations/deployment.py`) SHALL re-raise any
exception that occurs during the SFTP file write. It SHALL NOT swallow
non-SFTP exceptions (e.g. `binascii.Error` from a malformed base64
`fort.9` payload, `TypeError` from a non-string `data`,
`UnicodeEncodeError` on a text-mode write, `KeyError` from a missing
`task.context.extra` key, transient non-SFTP asyncssh errors, or
`OSError`).

The helper MAY catch `asyncssh.misc.Error` specifically to log the
structured SFTP `code` and `reason` fields (which are absent from
`str(err)` at upstream catch sites) and SHALL re-raise it immediately
after logging.

The propagation is the abort signal for `start_task_on_machine`: the
exception surfaces in `_upload_task_data` (which has no `try/except`
around the per-file loop) and then in `start_task_on_machine`'s DEPLOY
block `try/except Exception`, which logs `"Can't upload task_id=N
files: <err>"` (with `task_id`) and re-raises. The engine spawn command
SHALL NOT execute when an input file write has failed.

This requirement governs the module-private helper only; no public
surface (`MachineOperations`/`MachineRepository` Protocol, CLI, INI,
DB schema, AiiDA plugin) changes.

#### Scenario: Non-SFTP exception during write propagates and aborts spawn

- **WHEN** `_write_remote_file` is called and the write raises a non-SFTP exception (e.g. `binascii.Error` decoding a malformed `fort.9` base64 payload, or `TypeError` from `str(non_str)` `data`)
- **THEN** the exception propagates out of `_write_remote_file` without being swallowed, propagates through `_upload_task_data` (no `try/except` around the per-file loop), and is caught by `start_task_on_machine`'s DEPLOY block handler which logs `"Can't upload task_id=N files: <err>"` with the `task_id` and re-raises
- **AND** `_exec_spawn_command` is NOT called (the engine spawn command does not run, so no calculation proceeds with missing or garbage inputs)

#### Scenario: `asyncssh.misc.Error` is logged with structured code/reason and re-raised

- **WHEN** `_write_remote_file` is called and `sftp.open` or `f.write` raises an `asyncssh.misc.Error`
- **THEN** the helper logs `"Write <path> - SFTPError: <reason> (<code>)"` with the structured SFTP `code` and `reason` fields
- **AND** re-raises the same exception immediately
- **AND** the exception propagates through `_upload_task_data` and `start_task_on_machine` identically to the non-SFTP scenario above (abort, no spawn)

#### Scenario: Successful write returns normally

- **WHEN** `_write_remote_file` is called and the write completes without raising
- **THEN** the helper returns normally (no exception, no log line)
- **AND** `_upload_task_data` continues to the next input file in the loop

### Requirement: Backoff on session methods

The system SHALL apply `@my_backoff_exc()` (fibonacci, max_time=60,
`SSHRetryExc`) ONLY to idempotent session methods — namely
`get_cpu_cores` (a pure read of CPU core count) and the repository's
`_connect_impl` (retried connection establishment). The system SHALL
NOT apply `@my_backoff_exc()` to `run_bg` and SHALL NOT apply
`@my_backoff_sftp()` to `upload` or `download`: these three operations
are non-idempotent (a successful remote side-effect followed by a lost
client confirmation would produce a duplicate side-effect on retry), so
a single attempt with failure-propagation is the correct contract. The
`MachineOperations` Protocol declaration of `run_bg`, `upload`, and
`download` is preserved; only the SSH implementation's retry decorators
are removed.

`download_outputs` SHALL continue to use `my_backoff_sftp()` (defined
in `infra/ssh/operations/download.py`) as the per-file retry wrapper
inside the per-file loop.

#### Scenario: run_bg does not retry on SSH failure

- **WHEN** `session.run_bg(cmd)` fails with a retryable SSH exception (e.g. `ChannelOpenError`, `ConnectionLost` — both in `SSHRetryExc`)
- **THEN** the operation is NOT retried; the exception propagates immediately to the caller (`_exec_spawn_command`, then `start_task_on_machine`'s rollback handler, then the orchestrator)
- **AND** no second `asyncssh.create_process` call is made, so no duplicate engine process is started for the same task on the same machine

#### Scenario: upload does not retry on SFTP failure

- **WHEN** `session.upload(local, remote)` fails with a retryable SFTP exception (e.g. `SFTPConnectionLost` — in `SFTPRetryExc`)
- **THEN** the operation is NOT retried; the exception propagates immediately to the caller
- **AND** no second `sftp.put` call is made, so no half-written file is left on the remote from a partial retry

#### Scenario: get_cpu_cores retries on SSH failure

- **WHEN** `session.get_cpu_cores()` fails with a retryable SSH exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds (idempotent read — retry is safe)

### Requirement: SSH connection retry

The system SHALL retry SSH connections on transient failures using
the `backoff` library with fibonacci backoff and `max_time=60`. The
repository SHALL use a two-method pattern for `connect()`: inner
`_connect_impl` with `@my_backoff_exc()` decorator (retries on
`SSHRetryExc`), outer `connect` translates exhausted
`(asyncssh.misc.Error, OSError)` exceptions to
`MachineConnectionError`.

#### Scenario: Retry on connection refused

- **WHEN** SSH connection fails with a retryable exception (in `SSHRetryExc`)
- **THEN** the connection is retried with fibonacci backoff up to 60 seconds

#### Scenario: Non-retryable error skips retry

- **WHEN** SSH connection fails with a non-retryable exception (e.g., `PermissionDenied`)
- **THEN** the error is NOT retried and immediately translated to `MachineConnectionError`

#### Scenario: Exhausted retry raises MachineConnectionError

- **WHEN** all retry attempts are exhausted
- **THEN** the outer `connect` method catches `(asyncssh.misc.Error, OSError)` and raises `MachineConnectionError` wrapping the last exception

### Requirement: Occupancy monitoring

The system SHALL periodically check if an engine process is still
running on a machine and update the machine state to FREE when the
process exits. The check logic (`occupancy_check`,
`_occupancy_by_pgrep`, `_occupancy_by_cmd`) lives in
`infra/ssh/operations/occupancy.py`; the monitor mechanism
(`install_monitor`/`cancel_monitor`) lives on `SSHMachineSession`
(in `infra/ssh/session.py`).

The `OccupancyChecker.start_occupancy_check(session, config)` SHALL
additionally call `session.occupy()` before installing the monitor
(so that `_meta_sync` sees BUSY while the task runs). The monitor's
`on_free` SHALL call `session.release()`.

#### Scenario: Process exits, machine becomes free

- **WHEN** occupancy check detects the engine process has exited
- **THEN** the `ConnectedMachine` state is updated to FREE with `free_since` set (via `session.release()` invoked as the monitor's `on_free`)