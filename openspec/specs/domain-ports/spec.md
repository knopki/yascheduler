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
`add(node: Node) -> None`, `add_tmp(cloud: str) -> str`,
`update(node: Node) -> None`, `enable(ip: str) -> None`,
`disable(ip: str) -> None`, `remove(ip: str) -> None`,
`get_by_ips(ips: list[str]) -> dict[str, Node]`.

`add_tmp` takes only `cloud: str` — the `username` column on
`yascheduler_nodes` retains its `DEFAULT 'root'` and the tmp-row falls back to
that default. The tmp-row is a short-lived placeholder (`enabled=FALSE`)
removed before any reader touches it; no caller needs to supply a username.

#### Scenario: Full node lifecycle through port
- **WHEN** a consumer calls `add`, `get`, `update`, `enable`, `disable`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `remove` through the port
- **THEN** the Protocol defines all these operations with async signatures

#### Scenario: Add temporary node takes only cloud
- **WHEN** `add_tmp("aws")` is called
- **THEN** a tmp-node row is inserted with `enabled=FALSE`, the given cloud, and `username` left to the DB default (`'root'`); the generated IP is returned

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

### Requirement: CloudConfig structural Protocol

The system SHALL define a `@runtime_checkable` `CloudConfig` Protocol in
`yascheduler/domain/ports.py` with attributes:
- `prefix: str`
- `max_nodes: int`
- `idle_tolerance: int`
- `username: str`
- `jump_username: str | None`
- `jump_host: str | None`

`CloudConfig` captures the 6-field surface that application-layer consumers
(`deallocate_nodes`, `orchestrator`) read from cloud provider configs. The
concrete `ConfigCloud*` DTOs in `infra/cloud/cloud_configs.py` SHALL
**explicitly inherit** `CloudConfig` as a typing aid — the inheritance removes
the writable-vs-frozen mismatch that previously forced `cast` bridges in the
composition root and parser. The Protocol remains structural: a DTO outside
the inheritance tree still satisfies `CloudConfig` structurally per PEP 544;
the explicit inheritance by the 4 `ConfigCloud*` DTOs does not relax the
structural contract.

Application-layer consumers SHALL type `config_clouds` / `active_clouds`
parameters as `Sequence[CloudConfig]`, not `Sequence[ConfigCloud]`, keeping
`application → infra` TYPE_CHECKING-only. `CloudConfig` is a structural
Protocol for the minimal surface a consumer needs; it stands as its own
requirement (previously sub-prose under the `MachineGateway port`
requirement) because it has its own implementers (the 4 `ConfigCloud*` DTOs)
and its own consumption surface (`deallocate_nodes`, `orchestrator`), unlike
the single-implementer `Engine` case where the `OccupancyConfig` and
`TaskExecutionEngine` Protocols were removed.

The `CloudConfig` Protocol's docstring SHALL reflect the explicit-inheritance
choice — the prior "(no explicit inheritance)" wording (sub-prose under the
`MachineGateway port` requirement) becomes stale after the 4 `ConfigCloud*`
DTOs gain explicit inheritance; the docstring SHALL state that the DTOs inherit
the Protocol explicitly as a typing aid while structural matching continues to
apply to any DTO declaring the 6 fields. The stale "satisfied ... without
inheritance" prose under the `MachineGateway port` requirement SHALL be removed
from that location — the CloudConfig contract now stands as its own
requirement (this one), and the `MachineGateway port` requirement SHALL no
longer carry CloudConfig sub-prose.

#### Scenario: CloudConfig is runtime_checkable and satisfied by ConfigCloud DTOs
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
- **THEN** it returns `True` (the DTO inherits the Protocol explicitly; the
  Protocol is `@runtime_checkable`)

#### Scenario: CloudConfig docstring reflects explicit inheritance
- **WHEN** the `CloudConfig` Protocol's docstring in
  `yascheduler/domain/ports.py` is inspected
- **THEN** it does NOT contain the phrase "(no explicit inheritance)" (the 4
  `ConfigCloud*` DTOs now inherit the Protocol explicitly); it SHALL state
  that the DTOs inherit the Protocol as a typing aid and that structural
  matching continues to apply to any DTO declaring the 6 fields

#### Scenario: No stale "without inheritance" prose under MachineGateway port
- **WHEN** the `### Requirement: MachineGateway port` block in
  `yascheduler/domain/ports.py` (or in the rendered spec) is inspected
- **THEN** it does NOT carry the CloudConfig sub-prose previously at lines
  100-117 of `openspec/specs/domain-ports/spec.md` (the CloudConfig contract
  now stands as its own requirement; the `MachineGateway port` requirement
  no longer carries CloudConfig sub-prose or the "CloudConfig is
  runtime_checkable and satisfied by ConfigCloud DTOs" Scenario previously
  at lines 162-164)

#### Scenario: CloudConfig importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str) -> Node` (async),
`deallocate(cloud: str, ip: str) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync).

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `str | None` (the selected provider name or
`None`), then calls `allocate(selection)`.

`deallocate` takes `cloud` explicitly because the adapter no longer reads
the database to resolve the provider from `ip`. The caller (use case) has
the `Node` and passes `node.cloud`.

`select_provider` is sync — it does no I/O. It returns `None` when no
provider has capacity OR when the selected provider's op semaphore is
locked (throttle). The caller's `selection is None` branch handles
cleanup.

`capacity()` is removed — capacity counting is a use case / orchestrator
responsibility, not a cloud adapter concern.

`select_provider` returns the selected provider's name as a bare `str`,
matching the identity-string convention used across `NodeRepository`
(`get(ip: str)`, `remove(ip: str)`, `enable(ip: str)`, `disable(ip: str)`).
No `ProviderSelection` value object is defined; the application layer
treats the returned string as an opaque provider identity and passes it
back to `allocate`/`deallocate` unchanged.

#### Scenario: Allocate cloud node
- **WHEN** `allocate("aws")` is called with a valid provider name
- **THEN** returns a Node with the provisioned IP (no DB write inside the adapter)

#### Scenario: Report capacity
- **WHEN** `capacity()` is called
- **THEN** returns a dict mapping provider names to available node counts

#### Scenario: Deallocate cloud node with explicit cloud
- **WHEN** `deallocate(cloud="aws", ip="10.0.0.1")` is called
- **THEN** the VM at the given IP is deleted via the named provider's SDK

#### Scenario: Select provider returns provider name string
- **WHEN** `select_provider(["linux"], {"aws": 0})` is called and aws has capacity and supports linux
- **THEN** returns the string `"aws"` (the selected provider's name)

#### Scenario: Select provider returns None on no capacity
- **WHEN** `select_provider(["linux"], {"aws": 10})` is called and aws max_nodes is 10
- **THEN** returns `None`

#### Scenario: Select provider returns None on throttle
- **WHEN** the selected provider's op semaphore is locked
- **THEN** `select_provider` returns `None` (does not raise)

### Requirement: Ports are importable from domain

The system SHALL expose all port Protocols from `yascheduler.domain.ports`,
including `CloudConfig`.

#### Scenario: Import ports for adapter implementation
- **WHEN** an adapter module imports `from yascheduler.domain.ports import TaskRepository`
- **THEN** the Protocol class is available for structural subtyping

#### Scenario: Import CloudConfig from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError
