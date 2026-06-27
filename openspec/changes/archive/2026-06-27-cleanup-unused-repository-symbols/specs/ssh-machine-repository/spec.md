## MODIFIED Requirements

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
- `get_path(ip: str) -> type[PurePath]` (sync)
- `get_quote(ip: str) -> QuoteCallable` (sync)
- `get_hostname(ip: str) -> str` (sync) — `conn_opts.host`

**Occupancy-monitor mechanism (generic, Engine-agnostic):**
- `install_monitor(ip: str, *, interval: float, check_factory: Callable[[], Awaitable[bool]], on_free: Callable[[], None]) -> None` (sync) — creates an `asyncio.Task` keyed by IP that sleeps `interval`, calls `check_factory()`, and calls `on_free()` then breaks when the check returns `False`. Re-installing for an already-monitored IP cancels the prior monitor before installing the new one. A done-callback pops the IP only when the slot still points at the same task (re-registration identity check).
- `cancel_monitor(ip: str) -> None` (sync) — pops the monitor for `ip` (if any), cancels it; does NOT await

Note: `_get_machine_state(ip) -> _MachineState | None`
is the sole implementation-only method on `SSHMachineRepository` (see the
"SSHMachineRepository implements MachineRepository" requirement) — it
references `_MachineState` (an infra-internal dataclass) and is therefore
NOT part of the domain Protocol.

`MachineRepository` is `@runtime_checkable`. It SHALL NOT reference
`Engine`; the `install_monitor` mechanism is generic over
`Callable[[], Awaitable[bool]]` and `Callable[[], None]`.

#### Scenario: Repository satisfies Protocol structurally

- **WHEN** a class implements all `MachineRepository` methods with matching signatures
- **THEN** it satisfies the `@runtime_checkable` Protocol structurally

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

In addition to the `MachineRepository` Protocol methods, `SSHMachineRepository`
SHALL expose a single implementation-only method (NOT part of the domain
Protocol; used by adapter-internal consumers and tests):
- `_get_machine_state(ip: str) -> _MachineState | None` (sync) — returns the internal `_MachineState` (or `None`)

The connection-building bits (`MySSHClient`, `DEFAULT_CONN_OPTS`,
`_resolve_tunnel`) SHALL live in `infra/ssh/repository.py` and be used by
`_open_connection`.

#### Scenario: Repository imported from correct module

- **WHEN** `SSHMachineRepository` is imported
- **THEN** it is imported from `yascheduler.infra.ssh.repository`

#### Scenario: _MachineState is private to repository

- **WHEN** `_MachineState` is needed by a test or adapter-internal consumer
- **THEN** it is imported from `yascheduler.infra.ssh.repository` (not re-exported from the package root)

#### Scenario: Repository owns both dicts

- **WHEN** `disconnect(ip)` runs
- **THEN** `_machines[ip]` and `_monitors[ip]` are both popped (when present), the monitor is cancelled and awaited, and the SSH connection is closed
