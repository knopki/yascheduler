## MODIFIED Requirements

### Requirement: MachineGateway port

The system SHALL define a `MachineGateway` Protocol with methods:

**Connection lifecycle:**
- `connect(ip: str, username: str, client_keys: Sequence[PurePath] | None, *, port: int = 22, connect_timeout: int | None = None, data_dir: PurePath | None = None, engines_dir: PurePath | None = None, tasks_dir: PurePath | None = None, jump_host: str | None = None, jump_username: str | None = None) -> ConnectedMachine` (async)
- `disconnect(ip: str) -> None` (async)
- `disconnect_all() -> None` (async)

**Machine queries:**
- `list_free(platforms: list[str] | None) -> list[ConnectedMachine]` (sync)
- `list_connected() -> list[ConnectedMachine]` (sync)
- `contains(ip: str) -> bool` (sync)
- `get_machine_state(ip: str) -> ConnectedMachine | None` (sync)
- `update_machine(machine: ConnectedMachine) -> None` (sync)
- `__len__() -> int` (sync)

**Command execution:**
- `run(machine: ConnectedMachine, cmd: str) -> ProcessResult` (async)
- `run_bg(machine: ConnectedMachine, cmd: str, *, cwd: str | None = None) -> None` (async)

**File transfer:**
- `upload(machine: ConnectedMachine, local: Path, remote: str) -> None` (async)
- `download(machine: ConnectedMachine, remote: str, local: Path) -> None` (async)
- `download_outputs(ip: str, remote_dir: str, local_dir: Path, files: list[str], task_id: int | None = None) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]` (async) — returns `(meta_add, transient_errors, permanent_errors)` where `meta_add` contains `[("remote_folder", remote_dir), ("local_folder", str(local_dir))]`, `transient_errors` lists per-file `(file_path, exception)` tuples classified as retryable (instances of `SFTPRetryExc`), and `permanent_errors` lists per-file `(file_path, exception)` tuples classified as non-retryable (all other caught exceptions). The remote directory is removed only when `transient_errors` is empty; otherwise it is preserved for retry.

**Occupancy monitoring:**
- `start_occupancy_check(ip: str, config: Engine) -> None` (sync)

**Task deployment:**
- `start_task_on_machine(machine: ConnectedMachine, engine: Engine, task: Task, ncpus: int, engines_dir: PurePath) -> bool` (async)

**Remote info:**
- `get_cpu_cores(ip: str) -> int` (async)

The `config` parameter of `start_occupancy_check` and the `engine` parameter of
`start_task_on_machine` SHALL be typed as the concrete `Engine` frozen
dataclass from `yascheduler.domain.engine`. The system SHALL NOT define
separate `OccupancyConfig` or `TaskExecutionEngine` Protocols for these
parameters — `Engine` carries every field the SSH gateway reads for occupancy
checks (`name`, `check_pname`, `check_cmd`, `check_cmd_code`, `sleep_interval`)
and for task deployment (`spawn`, `input_files`), and a single-implementer
Protocol mirroring a concrete class is duplication whose cost exceeds the
Interface-Segregation benefit (per the `engine-to-domain-frozen` D4 precedent).

#### Scenario: List free machines filtered by platform
- **WHEN** `list_free(["linux", "debian-12"])` is called
- **THEN** returns only FREE ConnectedMachines with matching platforms

#### Scenario: Run command on machine
- **WHEN** `run(machine, "echo hello")` is called
- **THEN** returns a ProcessResult with exit_code and captured output

#### Scenario: List all connected machines
- **WHEN** `list_connected()` is called
- **THEN** returns a list of all ConnectedMachine objects currently registered

#### Scenario: Check if machine is connected
- **WHEN** `contains("10.0.0.1")` is called
- **THEN** returns True if the machine is registered, False otherwise

#### Scenario: Get machine state
- **WHEN** `get_machine_state("10.0.0.1")` is called
- **THEN** returns the ConnectedMachine if registered, None otherwise

#### Scenario: Update machine state
- **WHEN** `update_machine(machine)` is called with a ConnectedMachine
- **THEN** the machine's state is replaced in the registry

#### Scenario: Download task outputs with classified errors
- **WHEN** `download_outputs(ip, remote_dir, local_dir, files, task_id)` is called
- **THEN** opens SFTP session, downloads each file with retry, classifies per-file exceptions into `transient_errors` and `permanent_errors`, removes the remote directory only when `transient_errors` is empty, and returns `(meta_add, transient_errors, permanent_errors)` where `meta_add` contains `[("remote_folder", remote_dir), ("local_folder", str(local_dir))]`

#### Scenario: Download outputs preserves remote dir on transient errors
- **WHEN** `download_outputs(...)` encounters transient per-file errors (instances of `SFTPRetryExc`)
- **THEN** the remote directory is NOT removed and `transient_errors` is non-empty in the returned tuple

#### Scenario: Download outputs removes remote dir on permanent-only or success
- **WHEN** `download_outputs(...)` completes with `transient_errors` empty (full success or only permanent errors)
- **THEN** the remote directory is removed and `transient_errors` is empty in the returned tuple

#### Scenario: Start occupancy check
- **WHEN** `start_occupancy_check(ip, config)` is called with an `Engine` instance
- **THEN** background monitoring starts, checking if engine process is still running

#### Scenario: Get CPU cores
- **WHEN** `get_cpu_cores("10.0.0.1")` is called
- **THEN** returns the CPU core count for the machine

#### Scenario: Connect with retry
- **WHEN** `connect(...)` is called and connection fails with retryable error
- **THEN** the connection is retried with backoff; after exhaustion, raises `MachineConnectionError`

#### Scenario: Connect with non-retryable error
- **WHEN** `connect(...)` is called and connection fails with non-retryable error (e.g., auth failure)
- **THEN** raises `MachineConnectionError` immediately without retry