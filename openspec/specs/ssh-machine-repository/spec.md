# SSH Machine Repository

## Purpose

TBD - SSH machine repository and operations adapters implementing the MachineRepository and MachineOperations domain ports.

## Requirements

### Requirement: MachineRepository port

The system SHALL define a `@runtime_checkable` `MachineRepository` Protocol
in `yascheduler/domain/ports.py` representing the connected-machine
collection — lifecycle, queries, state transitions, accessor getters,
and the generic occupancy-monitor mechanism. The Protocol SHALL NOT
include operations on a single machine (exec, SFTP, deploy, download,
occupancy-check logic) — those are `MachineOperations`.

**Collection lifecycle:**
- `connect(ip: str, username: str, client_keys: Sequence[PurePath] | None, *, port: int = 22, connect_timeout: int | None = None, data_dir: PurePath | None = None, engines_dir: PurePath | None = None, tasks_dir: PurePath | None = None, jump_host: str | None = None, jump_username: str | None = None) -> ConnectedMachine` (async)
- `disconnect(ip: str) -> None` (async)
- `disconnect_all() -> None` (async)
- `register_machine(ip: str, state: _MachineState) -> None` (sync) — internal/test hook

**Queries:**
- `list_free(platforms: list[str] | None) -> list[ConnectedMachine]` (sync) — FREE machines filtered by platform, oldest-first by `free_since`
- `list_connected() -> list[ConnectedMachine]` (sync)
- `contains(ip: str) -> bool` (sync)
- `get_machine_state(ip: str) -> ConnectedMachine | None` (sync) — domain entity
- `__len__() -> int` (sync)
- `__contains__(ip: str) -> bool` (sync)

**State transitions:**
- `update_machine(machine: ConnectedMachine) -> None` (sync) — replace `ConnectedMachine` in the stored `_MachineState`
- `occupy(ip: str) -> None` (sync) — read-modify-write transitioning the stored machine to BUSY
- `release(ip: str) -> None` (sync) — read-modify-write transitioning the stored machine to FREE with `free_since = time.monotonic()`

**Accessor getters (read stored state):**
- `get_adapter(ip: str) -> RemoteMachineAdapter` (sync)
- `get_platforms(ip: str) -> Sequence[str]` (sync)
- `get_path(ip: str) -> type[PurePath]` (sync)
- `get_quote(ip: str) -> QuoteCallable` (sync)
- `get_data_dir(ip: str) -> PurePath` (sync)
- `get_engines_dir(ip: str) -> PurePath` (sync)
- `get_tasks_dir(ip: str) -> PurePath` (sync)
- `get_hostname(ip: str) -> str` (sync) — `conn_opts.host`

**Connection lifecycle:**
- `get_conn(ip: str) -> SSHClientConnection` (async) — returns current connection; reconnects if closed

**Occupancy-monitor mechanism (generic, Engine-agnostic):**
- `install_monitor(ip: str, *, interval: float, check_factory: Callable[[], Awaitable[bool]], on_free: Callable[[], None]) -> None` (sync) — creates an `asyncio.Task` keyed by IP that sleeps `interval`, calls `check_factory()`, and calls `on_free()` then breaks when the check returns `False`. Re-installing for an already-monitored IP cancels the prior monitor before installing the new one. A done-callback pops the IP only when the slot still points at the same task (re-registration identity check).
- `cancel_monitor(ip: str) -> None` (sync) — pops the monitor for `ip` (if any), cancels it; does NOT await

Note: `_get_machine_state(ip) -> _MachineState | None`, `register_machine(ip, _MachineState)`,
`keys() -> KeysView[str, _MachineState]`, and `items() -> ItemsView[str, _MachineState]`
are implementation-only methods on `SSHMachineRepository` (see the
"SSHMachineRepository implements MachineRepository" requirement) — they
reference `_MachineState` (an infra-internal dataclass) and are therefore
NOT part of the domain Protocol.

`MachineRepository` is `@runtime_checkable`. It SHALL NOT reference
`Engine`; the `install_monitor` mechanism is generic over
`Callable[[], Awaitable[bool]]` and `Callable[[], None]`.

#### Scenario: Repository satisfies Protocol structurally

- **WHEN** a class implements all `MachineRepository` methods with matching signatures
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

#### Scenario: Register and list connected machines

- **WHEN** `register_machine("10.0.0.1", state)` is called, then `list_connected()` is called
- **THEN** returns a list containing the `ConnectedMachine` of the registered state

#### Scenario: Filter free machines by platform

- **WHEN** `list_free(["linux", "debian-12"])` is called
- **THEN** returns only FREE machines whose `platform` is "linux" or "debian-12", sorted oldest-first by `free_since`

#### Scenario: occupy transitions machine to BUSY

- **WHEN** `occupy("10.0.0.1")` is called on a registered FREE machine
- **THEN** the stored `ConnectedMachine.state` becomes `BUSY`

#### Scenario: release transitions machine to FREE

- **WHEN** `release("10.0.0.1")` is called on a registered BUSY machine
- **THEN** the stored `ConnectedMachine.state` becomes `FREE` and `free_since` is set to `time.monotonic()`

#### Scenario: install_monitor replaces prior monitor

- **WHEN** `install_monitor(ip, ...)` is called for an IP that already has a live monitor
- **THEN** the prior monitor's `asyncio.Task` is cancelled before the new monitor is installed under the same IP key, without affecting monitors registered for other IPs

#### Scenario: install_monitor done-callback is identity-checked

- **WHEN** a monitor completes and the slot for its IP has been reassigned to a newer monitor
- **THEN** the done-callback SHALL NOT evict the newer monitor; the slot still points at the newer task

#### Scenario: cancel_monitor does not affect other IPs

- **WHEN** `cancel_monitor("10.0.0.1")` is called and IP "10.0.0.2" also has a monitor
- **THEN** only the monitor for "10.0.0.1" is cancelled; the monitor for "10.0.0.2" remains alive and registered

### Requirement: SSHMachineRepository implements MachineRepository

The system SHALL provide an `SSHMachineRepository` class in
`yascheduler/infra/ssh/repository.py` that satisfies the
`MachineRepository` Protocol. The repository SHALL own two dicts keyed by
IP: `_machines: dict[str, _MachineState]` (the connected-machine
registry) and `_monitors: dict[str, asyncio.Task[None]]` (the occupancy
monitors). Both dicts share the IP key so `disconnect(ip)` cleans both
atomically.

The `_MachineState` dataclass SHALL be defined in
`yascheduler/infra/ssh/repository.py` as a `@dataclass(frozen=True)`
holding `conn`, `conn_opts`, `machine`, `adapter`, `platforms`,
`data_dir`, `engines_dir`, `tasks_dir`.

`connect(ip, ...)` SHALL use a two-method pattern: inner `_connect_impl`
decorated with `@my_backoff_exc()` retries on `SSHRetryExc`; outer
`connect` translates exhausted `(asyncssh.misc.Error, OSError)` to
`MachineConnectionError`. `connect` SHALL open the SSH connection via
`_open_connection`, detect platform via `_detect_platform(conn,
ADAPTERS)` from `infra/ssh/platform/`, initialize paths via `_init_paths`
from `infra/ssh/platform/`, read `ncpus` via
`adapter.get_cpu_cores(make_run_fn(conn, adapter))`, construct a
`ConnectedMachine`, and store the resulting `_MachineState` in
`_machines[ip]`.

`disconnect(ip)` SHALL pop `_machines[ip]` (early return if absent),
then pop and cancel the monitor for `ip` (if any) and await its
cancellation, then close the SSH connection. The pop-before-await
ordering SHALL be preserved (prevents re-entry race re-inserting the
cancelled task).

`disconnect_all()` SHALL iterate `list(self._machines)` and call
`disconnect(ip)` per machine.

`get_conn(ip)` SHALL return the current SSH connection; if it is closing,
SHALL reconnect via `asyncssh.connection.connect(options=state.conn_opts,
...)`, replace `state` in `_machines[ip]` with the new connection, and
return it.

In addition to the `MachineRepository` Protocol methods, `SSHMachineRepository`
SHALL expose implementation-only methods (NOT part of the domain
Protocol; used by adapter-internal consumers and tests):
- `_get_machine_state(ip: str) -> _MachineState | None` (sync) — returns the internal `_MachineState` (or `None`)
- `register_machine(ip: str, state: _MachineState) -> None` (sync) — test/CLI hook to install a prebuilt state
- `keys() -> KeysView[str]` (sync) — the IP keys of `_machines`
- `items() -> ItemsView[str, _MachineState]` (sync) — the `(ip, _MachineState)` pairs of `_machines`

The connection-building bits (`MySSHClient`, `DEFAULT_CONN_OPTS`,
`_resolve_tunnel`) SHALL live in `infra/ssh/repository.py` and be used by
`_open_connection`. They SHALL NOT be imported from `helpers.py` (which
is deleted).

#### Scenario: Repository imported from correct module

- **WHEN** `SSHMachineRepository` is imported
- **THEN** it is imported from `yascheduler.infra.ssh.repository`

#### Scenario: _MachineState is private to repository

- **WHEN** `_MachineState` is needed by a test or adapter-internal consumer
- **THEN** it is imported from `yascheduler.infra.ssh.repository` (not re-exported from the package root)

#### Scenario: Repository owns both dicts

- **WHEN** `disconnect(ip)` runs
- **THEN** `_machines[ip]` and `_monitors[ip]` are both popped (when present), the monitor is cancelled and awaited, and the SSH connection is closed

### Requirement: MachineOperations port

The system SHALL define a `@runtime_checkable` `MachineOperations`
Protocol in `yascheduler/domain/ports.py` representing operations on a
single machine — command exec, SFTP transfer, process inspection, node
setup, task deployment, output download, and occupancy check logic. The
Protocol SHALL NOT include collection lifecycle, queries, state
transitions, accessor getters, or the monitor mechanism — those are
`MachineRepository`.

**Command execution:**
- `run(machine: ConnectedMachine, cmd: str) -> ProcessResult` (async)
- `run_full(machine: ConnectedMachine, cmd: str) -> SSHCompletedProcess` (async)
- `run_bg(machine: ConnectedMachine, cmd: str, *, cwd: str | None = None) -> None` (async)

**File transfer:**
- `upload(machine: ConnectedMachine, local: Path, remote: str) -> None` (async)
- `download(machine: ConnectedMachine, remote: str, local: Path) -> None` (async)
- `get_sftp(ip: str) -> AsyncContextManager[SFTPClient]` (async) — async context manager yielding an SFTP client

**Process inspection:**
- `pgrep(ip: str, pattern: str | Pattern[str], full: bool = True) -> AsyncGenerator[ProcessInfo, None]` (async)
- `list_processes(ip: str) -> AsyncGenerator[ProcessInfo, None]` (async)

**Node info / setup:**
- `get_cpu_cores(ip: str) -> int` (async) — retries on `SSHRetryExc` (idempotent read)
- `setup_node(ip: str, engines: EngineRepository) -> None` (async)

**Task deployment:**
- `start_task_on_machine(machine: ConnectedMachine, engine: Engine, task: Task, ncpus: int, engines_dir: PurePath) -> bool` (async)

**Output download:**
- `download_outputs(ip: str, remote_dir: str, local_dir: Path, files: list[str], task_id: int | None = None) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]` (async) — returns `(meta_add, transient_errors, permanent_errors)`

**Occupancy check:**
- `occupancy_check(ip: str, config: Engine) -> bool` (async) — True if busy or SSH failed (safe default), False only when confirmed free
- `start_occupancy_check(ip: str, config: Engine) -> None` (sync) — engine-aware installer that calls `repository.occupy(ip)` then `repository.install_monitor(ip, interval=config.sleep_interval, check_factory=partial(self.occupancy_check, ip, config), on_free=partial(repository.release, ip))`

The `config` parameter of `start_occupancy_check` and `occupancy_check`,
and the `engine` parameter of `start_task_on_machine`, SHALL be the
concrete `Engine` frozen dataclass from `yascheduler.domain.engine` (per
the `engine-to-domain-frozen` precedent — no separate
`OccupancyConfig`/`TaskExecutionEngine` Protocols).

Note (per design.md Q3): the domain `MachineOperations` Protocol exposes
the deployment use-case as `start_task_on_machine(...)` (matching the
implementation's method name and the existing orchestrator call sites),
rather than the flattened `deploy_task(...)` name design.md D8 floated
as an alternative. The concrete `SSHMachineOperations` class forwards
`start_task_on_machine` to `self.deploy.start_task_on_machine`; the
Protocol uses the existing name so existing call sites do not need a
method-name rename alongside the parameter-name change.

`MachineOperations` is `@runtime_checkable`.

#### Scenario: Operations satisfies Protocol structurally

- **WHEN** a class implements all `MachineOperations` methods with matching signatures
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

#### Scenario: start_occupancy_check composes repository monitor

- **WHEN** `start_occupancy_check(ip, engine)` is called
- **THEN** the operations object calls `repository.occupy(ip)` and `repository.install_monitor(ip, interval=engine.sleep_interval, check_factory=..., on_free=...)` — the operations object does NOT touch `_monitors` directly

#### Scenario: occupancy_check defaults to busy on SSH failure

- **WHEN** `occupancy_check(ip, config)` runs and the underlying SSH check raises a `SSHRetryExc`
- **THEN** the method returns `True` (safe-default busy) rather than propagating the exception

### Requirement: SSHMachineOperations composition

The system SHALL provide an `SSHMachineOperations` class in
`yascheduler/infra/ssh/operations/` satisfying the `MachineOperations`
Protocol. The class SHALL receive a `MachineRepository` reference and a
logger at construction and SHALL compose three sibling collaborators:
`TaskDeployer`, `OutputDownloader`, `OccupancyChecker` — exposed as the
`deploy`, `download`, `occupancy` attributes respectively. Base
primitives (`run`, `run_full`, `run_bg`, `upload`, `download`,
`get_sftp`, `pgrep`, `list_processes`, `get_cpu_cores`, `setup_node`)
SHALL live on `SSHMachineOperations` itself; the three collaborators
SHALL receive a reference to a primitive-provider (typed against narrow
local Protocols defined in `operations/base.py`) plus the repository.

`SSHMachineOperations.start_task_on_machine(...)` SHALL forward to
`self.deploy.start_task_on_machine(...)`; similarly
`download_outputs(...)` to `self.download.download_outputs(...)` and
`start_occupancy_check(...)`/`occupancy_check(...)` to
`self.occupancy.*`.

Composition (not inheritance) SHALL be used. The collaborators SHALL
NOT subclass `SSHMachineOperations`.

#### Scenario: Operations imports from operations package

- **WHEN** `SSHMachineOperations` is imported
- **THEN** it is imported from `yascheduler.infra.ssh.operations`

#### Scenario: Deploy attribute is TaskDeployer

- **WHEN** `SSHMachineOperations(repository, log).deploy` is accessed
- **THEN** it is an instance of `TaskDeployer` holding the same repository and primitive-provider references

#### Scenario: start_task_on_machine forwards to deploy

- **WHEN** `operations.start_task_on_machine(machine, engine, task, ncpus, engines_dir)` is called
- **THEN** the call forwards to `operations.deploy.start_task_on_machine(...)` with identical arguments

#### Scenario: download_outputs forwards to download

- **WHEN** `operations.download_outputs(ip, remote_dir, local_dir, files, task_id)` is called
- **THEN** the call forwards to `operations.download.download_outputs(...)` with identical arguments

#### Scenario: start_occupancy_check forwards to occupancy

- **WHEN** `operations.start_occupancy_check(ip, engine)` is called
- **THEN** the call forwards to `operations.occupancy.start_occupancy_check(...)` with identical arguments
