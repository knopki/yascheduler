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
- `download_outputs(ip: str, remote_dir: str, local_dir: Path, files: list[str], task_id: int | None = None) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]` (async)

**Occupancy monitoring:**
- `start_occupancy_check(ip: str, config: OccupancyConfig) -> None` (sync)

**Task deployment:**
- `start_task_on_machine(machine: ConnectedMachine, engine: TaskExecutionEngine, task: Task, ncpus: int, engines_dir: PurePath) -> bool` (async)

**Remote info:**
- `get_cpu_cores(ip: str) -> int` (async)

The system SHALL define an `OccupancyConfig` Protocol with attributes:
- `name: str`
- `check_pname: str | None`
- `check_cmd: str | None`
- `check_cmd_code: int`
- `sleep_interval: int`

The system SHALL define a `TaskExecutionEngine` Protocol extending `OccupancyConfig`
with the engine fields required for task deployment:
- `spawn: str` (format template for the spawn command)
- `input_files: tuple[str, ...]` (engine input file names)

`config.Engine` SHALL structurally satisfy `TaskExecutionEngine`.

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

#### Scenario: Download task outputs
- **WHEN** `download_outputs(ip, remote_dir, local_dir, files, task_id)` is called
- **THEN** opens SFTP session, downloads each file with retry, removes remote directory, returns `(meta_add, sftp_errors)` tuple where `meta_add` contains `[("remote_folder", remote_dir), ("local_folder", str(local_dir))]` and `sftp_errors` contains `(file_path, exception)` tuples

#### Scenario: Start occupancy check
- **WHEN** `start_occupancy_check(ip, config)` is called with an OccupancyConfig
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
