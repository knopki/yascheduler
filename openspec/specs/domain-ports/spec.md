## Purpose

Defines abstract port interfaces (typing.Protocol) for the domain layer: TaskRepository, NodeRepository, MachineRepository, MachineOperations, and CloudProvisioner — contracts that infrastructure adapters must implement.

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

### Requirement: MachineRepository and MachineOperations ports replace MachineGateway

The system SHALL define two `@runtime_checkable` Protocols in
`yascheduler/domain/ports.py` replacing the removed `MachineGateway`:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_machine_state`/`contains`),
  state transitions (`update_machine`/`occupy`/`release`), accessor
  getters (`get_path`/`get_quote`/`get_hostname`), and the generic
  monitor mechanism (`install_monitor`/`cancel_monitor`).
- `MachineOperations` — operations on a single machine:
  `run`/`run_full`/`run_bg`, `upload`/`download`/`get_sftp`,
  `pgrep`/`list_processes`, `get_cpu_cores`/`setup_node`,
  `start_task_on_machine`, `download_outputs`, `occupancy_check`,
  `start_occupancy_check`.

The full method-signature specification of these two Protocols lives
in the `ssh-machine-repository` capability spec (Requirement:
MachineRepository port, Requirement: MachineOperations port, Requirement:
SSHMachineOperations composition). The `domain-ports` capability
asserts only that both Protocols are defined here, are
`@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades.

Application-layer consumers (`allocate_task.py`, `consume_task.py`,
`deallocate_nodes.py`, `abandon_node.py`, `orchestrator.py`) SHALL type
their SSH-side parameters against `MachineRepository` and
`MachineOperations` (one or both, depending on which methods they call)
— never against `MachineGateway` (removed).

#### Scenario: Import MachineRepository from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineRepository`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: Import MachineOperations from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineOperations`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: Both Protocols are runtime_checkable

- **WHEN** `isinstance(repository_obj, MachineRepository)` and
  `isinstance(operations_obj, MachineOperations)` are evaluated
- **THEN** both Protocols are `@runtime_checkable` and structural-subtype
  their implementations

#### Scenario: Application consumers type against the two new Protocols

- **WHEN** `application/orchestrator.py`, `application/allocate_task.py`,
  `application/consume_task.py`, `application/deallocate_nodes.py`, and
  `application/abandon_node.py` are inspected for SSH-side parameter
  annotations
- **THEN** the annotations are `MachineRepository` and/or
  `MachineOperations` (per the methods each consumer calls); the
  annotation `MachineGateway` does not appear in any of these files

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
including `CloudConfig`, `MachineRepository`, and `MachineOperations`.

The module SHALL NOT export `MachineGateway` — the Protocol is removed
and replaced by `MachineRepository` + `MachineOperations`.

#### Scenario: Import ports for adapter implementation

- **WHEN** an adapter module imports `from yascheduler.domain.ports import TaskRepository`
- **THEN** the Protocol class is available for structural subtyping

#### Scenario: Import MachineRepository and MachineOperations from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineRepository, MachineOperations`
- **THEN** the Protocol classes resolve without ImportError

#### Scenario: Import CloudConfig from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: MachineGateway not exported

- **WHEN** `yascheduler.domain.ports` is inspected for `MachineGateway`
- **THEN** the name is absent; the Protocol has been removed and replaced by `MachineRepository` + `MachineOperations`
