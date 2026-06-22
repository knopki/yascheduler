## Purpose

Defines abstract port interfaces (typing.Protocol) for the domain layer: TaskRepository, NodeRepository, MachineGateway, and CloudProvisioner — contracts that infrastructure adapters must implement.

## Requirements

### Requirement: TaskRepository port

The system SHALL define a `TaskRepository` Protocol with async methods:
`get(task_id: int) -> Task | None`, `save(task: Task) -> None`,
`insert(task: Task) -> Task`,
`list_by_status(statuses: set[TaskStatus], limit: int | None) -> list[Task]`,
`list_by_jobs(job_ids: list[int]) -> list[Task]`,
`update_status(task_id: int, status: TaskStatus) -> None`,
`list_ids_by_ip_and_status(ip: str, status: TaskStatus) -> list[int]`.

The `TaskRepository` Protocol SHALL define an async `list_by_status` method
with an optional `limit` parameter for bounded queries.

#### Scenario: Repository method signatures are async
- **WHEN** a class implements `TaskRepository` with matching async method signatures
- **THEN** it satisfies the Protocol structurally

#### Scenario: List tasks by status without limit
- **WHEN** `list_by_status({TaskStatus.TO_DO})` is called
- **THEN** returns all tasks with TO_DO status

#### Scenario: List tasks by status with limit
- **WHEN** `list_by_status({TaskStatus.TO_DO}, limit=10)` is called
- **THEN** returns at most 10 tasks with TO_DO status

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol with async methods:
`get(ip: str) -> Node | None`, `list_enabled() -> list[Node]`,
`list_disabled() -> list[Node]`, `list_all() -> list[Node]`,
`add(node: Node) -> None`, `add_tmp(cloud: str, username: str) -> str`,
`update(node: Node) -> None`, `enable(ip: str) -> None`,
`disable(ip: str) -> None`, `remove(ip: str) -> None`,
`get_by_ips(ips: list[str]) -> dict[str, Node]`.

#### Scenario: Full node lifecycle through port
- **WHEN** a consumer calls `add`, `get`, `update`, `enable`, `disable`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `remove` through the port
- **THEN** the Protocol defines all these operations with async signatures

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

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str) -> Node` (async),
`deallocate(cloud: str, ip: str) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> ProviderSelection | None` (sync).

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `ProviderSelection` (or `None`), then
calls `allocate(selection.name)`.

`deallocate` takes `cloud` explicitly because the adapter no longer reads
the database to resolve the provider from `ip`. The caller (use case) has
the `Node` and passes `node.cloud`.

`select_provider` is sync — it does no I/O. It returns `None` when no
provider has capacity OR when the selected provider's op semaphore is
locked (throttle). The caller's `selection is None` branch handles
cleanup.

`capacity()` is removed — capacity counting is a use case / orchestrator
responsibility, not a cloud adapter concern.

The system SHALL define a `ProviderSelection` value object in
`yascheduler.domain.model` with fields `name: str` and `username: str`.
It is primitive-only — no adapter types (`CloudAdapter`, `ConfigCloud`)
cross the port boundary.

#### Scenario: Allocate cloud node
- **WHEN** `allocate("aws")` is called with a valid provider name
- **THEN** returns a Node with the provisioned IP (no DB write inside the adapter)

#### Scenario: Report capacity
- **WHEN** `capacity()` is called
- **THEN** returns a dict mapping provider names to available node counts

#### Scenario: Deallocate cloud node with explicit cloud
- **WHEN** `deallocate(cloud="aws", ip="10.0.0.1")` is called
- **THEN** the VM at the given IP is deleted via the named provider's SDK

#### Scenario: Select provider returns ProviderSelection
- **WHEN** `select_provider(["linux"], {"aws": 0})` is called and aws has capacity and supports linux
- **THEN** returns a `ProviderSelection(name="aws", username="root")` (or configured username)

#### Scenario: Select provider returns None on no capacity
- **WHEN** `select_provider(["linux"], {"aws": 10})` is called and aws max_nodes is 10
- **THEN** returns `None`

#### Scenario: Select provider returns None on throttle
- **WHEN** the selected provider's op semaphore is locked
- **THEN** `select_provider` returns `None` (does not raise)

### Requirement: Ports are importable from domain

The system SHALL expose all port Protocols from `yascheduler.domain.ports`.

#### Scenario: Import ports for adapter implementation
- **WHEN** an adapter module imports `from yascheduler.domain.ports import TaskRepository`
- **THEN** the Protocol class is available for structural subtyping
