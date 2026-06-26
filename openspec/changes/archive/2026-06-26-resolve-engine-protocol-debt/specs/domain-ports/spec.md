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

The system SHALL define a `CloudConfig` structural Protocol with attributes:
- `prefix: str`
- `max_nodes: int`
- `idle_tolerance: int`
- `username: str`
- `jump_username: str | None`
- `jump_host: str | None`

`CloudConfig` captures the 6-field surface that application-layer consumers
(`deallocate_nodes`, `orchestrator`) read from cloud provider configs. Every
`ConfigCloud*` DTO in `infra/cloud/cloud_configs.py` SHALL structurally satisfy
`CloudConfig`. Application-layer consumers SHALL type `config_clouds` /
`active_clouds` parameters as `Sequence[CloudConfig]`, not `Sequence[ConfigCloud]`,
keeping `application → infra` TYPE_CHECKING-only. `CloudConfig` is a structural
Protocol for the minimal surface a consumer needs, satisfied by the concrete
`ConfigCloud*` DTOs without inheritance; it stays in place because there are
multiple DTO implementers (unlike the single-implementer `Engine` case).

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
- **WHEN** `start_occupancy_check(ip, config)` is called with an `Engine` instance
- **THEN** background monitoring starts, checking if the engine process is still running

#### Scenario: Get CPU cores
- **WHEN** `get_cpu_cores("10.0.0.1")` is called
- **THEN** returns the CPU core count for the machine

#### Scenario: Connect with retry
- **WHEN** `connect(...)` is called and connection fails with retryable error
- **THEN** the connection is retried with backoff; after exhaustion, raises `MachineConnectionError`

#### Scenario: Connect with non-retryable error
- **WHEN** `connect(...)` is called and connection fails with non-retryable error (e.g., auth failure)
- **THEN** raises `MachineConnectionError` immediately without retry

#### Scenario: CloudConfig is runtime_checkable and satisfied by ConfigCloud DTOs
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
- **THEN** it returns `True` (the DTO declares all 6 Protocol fields; structural satisfaction)

## REMOVED Requirements

### Requirement: OccupancyConfig Protocol
**Reason**: The `OccupancyConfig` Protocol was introduced by `gateway-port-cleanup`
(D7) because the pre-`engine-to-domain-frozen` `domain.Engine` lacked
`check_cmd_code` / `sleep_interval` and `config.Engine` was unreachable from
`domain`. After `engine-to-domain-frozen` (P2/D4), `Engine` moved to
`yascheduler.domain` with all those fields and `infra → domain` /
`application → domain` became R3-legal. D4 deleted the parallel
`PEngine` / `PEngineRepository` Protocols on the rationale that a
single-implementer Protocol mirroring a concrete class is duplication whose
cost exceeds the Interface-Segregation benefit; `OccupancyConfig` is the same
case and is removed for the same reason. `MachineGateway.start_occupancy_check`
now types its `config` parameter as the concrete `Engine`.
**Migration**: Type the `config` parameter of `start_occupancy_check` and the
`config` parameter of any stub/mock implementation as `Engine` (imported from
`yascheduler.domain`). No runtime behavior changes; the runtime value was
always an `Engine` instance.

### Requirement: TaskExecutionEngine Protocol
**Reason**: Same as `OccupancyConfig` — `TaskExecutionEngine` was the
deployment-superset Protocol created by `gateway-port-cleanup` (D7) for the
same pre-D4 layer constraint. Post-D4, `Engine` carries `spawn` and
`input_files` and lives in `yascheduler.domain`; the Protocol is
single-implementer duplication, removed per the D4 rationale.
`MachineGateway.start_task_on_machine` now types its `engine` parameter as the
concrete `Engine`.
**Migration**: Type the `engine` parameter of `start_task_on_machine`,
`_exec_spawn_command`, and any stub/mock implementation as `Engine` (imported
from `yascheduler.domain`). Remove the `cast("TaskExecutionEngine", engine)`
and `cast("OccupancyConfig", engine)` calls in
`application/allocate_task.py` and `application/orchestrator.py` — they are
identity after the retype. No runtime behavior changes.