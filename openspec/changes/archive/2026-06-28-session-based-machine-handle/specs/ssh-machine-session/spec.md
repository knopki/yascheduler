# SSH Machine Session

## ADDED Requirements

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

**Base primitives (async, moved from the dissolved `SSHMachineOperations` base):**
- `run(cmd: str) -> ProcessResult` (async)
- `run_full(cmd: str) -> SSHCompletedProcess` (async)
- `run_bg(cmd: str, *, cwd: str | None = None) -> None` (async)
- `upload(local: Path, remote: str) -> None` (async)
- `open_sftp() -> AsyncContextManager[SFTPClient]` (async) — async context manager yielding an SFTP client
- `get_cpu_cores() -> int` (async) — retries on `SSHRetryExc` (idempotent read)
- `setup_node(engines: EngineRepository) -> None` (async)
- `pgrep(pattern: str | Pattern[str], full: bool = True) -> AsyncGenerator[ProcessInfo, None]` (async)
- `list_processes() -> AsyncGenerator[ProcessInfo, None]` (async)

**Monitor mechanism (Engine-agnostic; moved off `MachineRepository`):**
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
at each consumer tick where it needs to operate on a machine — same
pattern as today's `get_machine_state(ip)`. The orchestrator SHALL NOT
cache session references across await boundaries: a cached reference
survives `disconnect` and silently mutates an orphaned session.

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
