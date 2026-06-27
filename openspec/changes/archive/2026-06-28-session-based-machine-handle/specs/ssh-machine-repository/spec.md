# SSH Machine Repository (delta — session-based-machine-handle)

## MODIFIED Requirements

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
(`occupy`/`release`/`update_machine`), or the monitor mechanism
(`install_monitor`/`cancel_monitor`) — those are on `MachineSession`. The
Protocol SHALL NOT expose `get_machine_state` — callers use
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
`disconnect(ip)` per session.

The connection-building bits (`MySSHClient`, `DEFAULT_CONN_OPTS`,
`_resolve_tunnel`) SHALL live in `infra/ssh/repository.py` and be used
by `_open_connection`.

The repository SHALL NOT expose `_get_machine_state`,
`register_machine`, `keys`, `items`, `get_machine_state`,
`install_monitor`, `cancel_monitor`, `occupy`, `release`,
`update_machine`, `get_path`, `get_quote`, `get_hostname`,
`get_adapter`, `get_platforms`, `get_data_dir`, `get_engines_dir`,
`get_tasks_dir`, or `get_conn` — all removed by this change or its
predecessor `cleanup-unused-repository-symbols`.

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

### Requirement: MachineOperations port

The system SHALL define a `@runtime_checkable` `MachineOperations`
Protocol in `yascheduler/domain/ports.py` representing operations on a
single machine. The Protocol's methods SHALL take `session: MachineSession`
where they today take `machine: ConnectedMachine` or `ip: str`. The
Protocol SHALL NOT itself declare base primitives (`run`, `run_full`,
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

## REMOVED Requirements

### Requirement: (none)

This change does not remove any top-level requirement from
`ssh-machine-repository`. The `MachineRepository port`,
`SSHMachineRepository implements MachineRepository`, `MachineOperations
port`, and `SSHMachineOperations composition` requirements are all
MODIFIED in place. Their previous content (including `_MachineState`,
`_get_machine_state`, `_monitors`, `occupy`/`release`/`update_machine`,
`install_monitor`/`cancel_monitor`, `get_path`/`get_quote`/
`get_hostname`, `get_machine_state`, and the operations base primitives)
is superseded by the MODIFIED text above and by the new
`ssh-machine-session` capability spec.
