# Delta: ssh-infrastructure

## MODIFIED Requirements

### Requirement: MachineRepository port

The system SHALL define a `@runtime_checkable` `MachineRepository` Protocol
representing the connected-machine collection, keyed by `NodeId`. The
collection lifecycle methods (`connect`, `disconnect`, `disconnect_all`), the
query methods (`list_free`, `list_connected`, `get_session`, `contains`,
`__contains__`, `__len__`), and the FREE-session filter semantics live on this
Protocol.

`connect(node: Node, client_keys: Sequence[PurePath] | None, *, connect_timeout,
data_dir, engines_dir, tasks_dir) -> MachineSession` (async) SHALL register an
`SSHMachineSession` keyed by `node.node_id` and return it. The asyncssh
transport identity (host, login user, port, jump leg) SHALL be read from the
`node` parameter.

`list_free(platforms: list[str] | None) -> list[MachineSession]` (sync) SHALL
return sessions whose `machine.state == FREE`, optionally filtered by
`machine.platform`, sorted oldest-first by `session.machine.free_since`.

`MachineRepository` SHALL be importable via the `yascheduler.domain` facade.

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

The system SHALL provide an `SSHMachineRepository` class that satisfies the
`MachineRepository` Protocol. The repository SHALL own a single dict of
sessions keyed by `NodeId`.

`connect(node: Node, ...)` SHALL establish an SSH session, detect the
platform, read `ncpus` via `adapter.get_cpu_cores(...)`, log the discovered
CPU count at the discovery site, seed the session cache with the discovered
value, construct an `SSHMachineSession`, store it keyed by `node.node_id`, and
return it. On connection failure,
`MachineConnectionError(node.node_id, node.hostname, str(err))` SHALL be
raised.

`disconnect(node_id)` SHALL remove the session for `node_id` (early return if
absent) and close it. `disconnect_all()` SHALL iterate a snapshot of keys and
call `disconnect(node_id)` per session; it SHALL be idempotent.

#### Scenario: Repository owns only the sessions dict keyed by NodeId

- **WHEN** `SSHMachineRepository.__init__` is inspected
- **THEN** the instance has a dict of sessions keyed by `NodeId` as its only collection attribute

#### Scenario: connect logs CPU count at discovery site, not in setup_node

- **WHEN** `await repository.connect(node, client_keys, ...)` succeeds and `adapter.get_cpu_cores(...)` returns `8`
- **THEN** an info log line with the CPU count is emitted from the repository's connect path (the discovery site), and no separate CPU-count log is emitted from `SSHMachineSession.setup_node`

### Requirement: MachineSession port

The system SHALL define a `@runtime_checkable` `MachineSession` Protocol
representing the connected-machine entity handle.

**Domain face** — read-only properties: `hostname: str`, `machine:
ConnectedMachine`, `is_closed: bool`. Mutators: `occupy() -> None` (sync),
`release() -> None` (sync), `update(machine: ConnectedMachine) -> None`
(sync).

**Connect-time config** — read-only properties: `adapter`, `platforms`,
`data_dir`, `engines_dir`, `tasks_dir`.

**Adapter-derived accessors** — read-only properties: `path`, `quote`.

**Base primitives** (async): `run`, `run_full`, `run_bg`, `upload`,
`open_sftp`, `get_cpu_cores`, `setup_node`, `pgrep`, `list_processes`.

**Monitor mechanism** (sync, on the session): `install_monitor(*, interval,
check_factory, on_free) -> None` and `cancel_monitor() -> None`.
`install_monitor` periodically awaits `check_factory()` and calls `on_free()`
when the check returns `False`.

`MachineSession` SHALL be importable via the `yascheduler.domain` facade.

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

The session SHALL own its own teardown, invoked only by
`SSHMachineRepository.disconnect`. Close SHALL be idempotent and SHALL release
the SSH connection and cancel the monitor task.

`run_full` SHALL retry on retryable SSH errors with fibonacci backoff up to
`max_time=60`. `setup_node(engines: EngineRepository) -> None` (async) SHALL
delegate to `adapter.setup_node(...)`.

#### Scenario: Session owns its monitor task

- **WHEN** `session.install_monitor(...)` is called
- **THEN** the resulting `asyncio.Task` is stored on the session and is NOT registered in any repository-level dict

#### Scenario: Session.hostname stays sourced from node.hostname

- **WHEN** `SSHMachineSession` is constructed by `SSHMachineRepository.connect`
- **THEN** `session.hostname == node.hostname` (the session's transport-echo field is sourced from the Node parameter)

### Requirement: Session is returned by repository and resolved per-tick by the orchestrator

`SSHMachineRepository.connect(node: Node, ...) -> MachineSession` SHALL return
the newly-constructed session. `list_free` / `list_connected` SHALL return
`list[MachineSession]`. `get_session(node_id: NodeId) -> MachineSession | None`
SHALL return the live session for `node_id` or `None` (after disconnect).

#### Scenario: connect returns a session

- **WHEN** `await repository.connect(node, ...)` returns
- **THEN** the return value is a `MachineSession` whose `hostname == node.hostname`, `machine.node_id == node.node_id`, `machine.state == FREE`, `machine.platform`, and `machine.ncpus` match the connection

### Requirement: download_outputs per-file SFTP isolation and retry

The system SHALL provide `OutputDownloader.download_outputs(session,
remote_dir, local_dir, files, task_id)` returning
`(local_folder: str, remote_folder: str, transient_errors, permanent_errors)`.
Each per-file exception SHALL be classified into `transient_errors` (retryable
SFTP errors and session-level failures) or `permanent_errors` (all other
caught exceptions).

A FRESH SFTP client SHALL be opened per file in the per-file loop. Each file's
`sftp.get` SHALL be wrapped individually with per-file retry (fibonacci,
`max_time=60`).

The remote directory tree SHALL be removed ONCE, after the per-file loop
completes, and only when BOTH error lists are empty.

The `local_folder` / `remote_folder` return values SHALL be `str(local_dir)`
and `remote_dir` verbatim.

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `operations.download_outputs(session, remote_dir, local_dir, files, task_id)` is called
- **THEN** a FRESH SFTP client is opened per file in the loop, each file is downloaded with per-file retry, per-file exceptions are classified into `transient_errors` and `permanent_errors`, and `(local_folder=str(local_dir), remote_folder=remote_dir, transient_errors, permanent_errors)` is returned

### Requirement: start_task_on_machine rolls back BUSY on failure

The `TaskDeployer.start_task_on_machine` method SHALL mark the session BUSY at
`session.occupy()` before performing the deploy and spawn steps. If any
exception (including `CancelledError`) escapes, the method SHALL roll back by
calling `session.release()` (or its equivalent via `session.update(...)`),
then re-raise the original exception. The rollback SHALL run under
`except BaseException`.

The rollback SHALL govern the session-level occupancy marker only; the DB
task status and orchestrator's in-memory `mark_running()` are owned by the
caller.

#### Scenario: Upload failure rolls back BUSY

- **WHEN** `TaskDeployer.start_task_on_machine` calls `session.occupy()` marking the session BUSY, then the deploy step raises
- **THEN** the `except BaseException` handler calls `session.release()`, logs an info line, and re-raises the original exception
- **AND** the session's `machine.state` is `FREE` after the call returns

### Requirement: File-upload non-SFTP errors propagate

Non-SFTP exceptions SHALL propagate immediately during remote file upload.
SFTP errors (`asyncssh.misc.Error`) MAY be logged with structured `code` and
`reason` fields and SHALL also re-raise immediately after logging. The
propagated exception SHALL be the abort signal for `start_task_on_machine`.

#### Scenario: Non-SFTP exception re-raised during file upload
- **WHEN** a `TypeError` occurs during SFTP file write
- **THEN** the exception is re-raised immediately (not swallowed)

### Requirement: Retry and backoff policy

The system SHALL apply retry with fibonacci backoff, `max_time=60`, to
idempotent operations: `get_cpu_cores` (pure read, cache miss path) and
connection establishment. `download_outputs` SHALL continue to use per-file
SFTP retry (fibonacci, `max_time=60`) inside the per-file loop.

SSH connections SHALL be retried on transient failures using fibonacci backoff
with `max_time=60`. Exhausted failures SHALL surface as
`MachineConnectionError`.

The retry on `get_cpu_cores` applies only on a cache miss (the first call in a
session lifetime, or the priming call from `SSHMachineRepository.connect`).

#### Scenario: get_cpu_cores retries on SSH failure (cache miss)

- **WHEN** `session.get_cpu_cores()` is called on a session whose cache is empty (miss) and the underlying adapter call fails with a retryable SSH exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds (idempotent read — retry is safe); the successful result is stored in the session cache

#### Scenario: get_cpu_cores returns cached value without retry

- **WHEN** `session.get_cpu_cores()` is called on a session that has already cached a CPU count (cache hit) and the underlying adapter would fail
- **THEN** the cached value is returned immediately; the adapter is NOT invoked and no retry is attempted

### Requirement: SSHMachineSession memoizes CPU core discovery

`SSHMachineSession` SHALL memoize the result of CPU-core discovery per session
instance. The first `get_cpu_cores()` call in a session lifetime SHALL invoke
the adapter exactly once and store the result; subsequent calls within the
same session SHALL return the cached value without invoking the adapter.

The cache SHALL be primed by `SSHMachineRepository.connect` after constructing
the session, seeding it with the CPU count already read via
`adapter.get_cpu_cores(...)`. The first `get_cpu_cores()` call on a primed
session returns the cached value without invoking the adapter.

The cache lives for the session's lifetime only — a reconnected session starts
with an empty cache and re-discovers once.

#### Scenario: First get_cpu_cores call in a session invokes the adapter

- **WHEN** `session.get_cpu_cores()` is called on a session whose cache is empty (miss)
- **THEN** the underlying `adapter.get_cpu_cores(...)` is invoked exactly once and the result is stored in the session cache

#### Scenario: Second get_cpu_cores call in a session returns the cache

- **WHEN** `session.get_cpu_cores()` is called twice on the same session instance
- **THEN** the underlying `adapter.get_cpu_cores(...)` is invoked exactly once (on the first call); the second call returns the cached value without invoking the adapter

#### Scenario: connect primes the session cache

- **WHEN** `SSHMachineRepository.connect(node, ...)` constructs an `SSHMachineSession` and reads `ncpus` via `adapter.get_cpu_cores(...)`
- **THEN** the session cache is seeded with that value, and the first `session.get_cpu_cores()` call returns the primed value without a further adapter invocation

#### Scenario: Reconnected session re-discovers

- **WHEN** a session is closed and a new `SSHMachineSession` is constructed for the same `node_id` (reconnect)
- **THEN** the new session's cache is empty and the first `get_cpu_cores()` call re-invokes the adapter

### Requirement: Occupancy monitoring

The system SHALL periodically check if an engine process is still running on
a machine and update the machine state to FREE when the process exits. The
check logic lives on the `OccupancyChecker` class; the monitor mechanism
(`install_monitor` / `cancel_monitor`) lives on `SSHMachineSession`.

The `OccupancyChecker.start_occupancy_check(session, config)` SHALL call
`session.occupy()` before installing the monitor (so the system sees BUSY
while the task runs). The monitor's `on_free` SHALL call `session.release()`.

#### Scenario: Process exits, machine becomes free

- **WHEN** occupancy check detects the engine process has exited
- **THEN** the `ConnectedMachine` state is updated to FREE with `free_since` set (via `session.release()` invoked as the monitor's `on_free`)

### Requirement: Module layout

The system SHALL define `ProcessInfo` (frozen dataclass with fields
`pid: int`, `name: str`, `command: str`) in the platform protocol module.
`ADAPTERS`, platform detection, path init, and `MAX_SESSIONS` SHALL be
exposed from the SSH platform package.

#### Scenario: ProcessInfo defined in platform protocol module
- **WHEN** the platform protocol module is inspected
- **THEN** `ProcessInfo` is a frozen dataclass with fields `pid: int`, `name: str`, `command: str`
