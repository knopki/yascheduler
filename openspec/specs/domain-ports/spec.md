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
`get(ip: str) -> Node | None`, `get_by_id(node_id: NodeId) -> Node | None`,
`list_enabled() -> list[Node]`, `list_disabled() -> list[Node]`,
`list_all() -> list[Node]`, `insert(new_node: NewNode) -> Node`,
`add_tmp(cloud: str) -> str`, `update(node: Node) -> None`,
`enable(ip: str) -> None`, `disable(ip: str) -> None`, `remove(ip: str) -> None`,
`get_by_ips(ips: list[str]) -> dict[str, Node]`, `count_by_status() -> Mapping[bool, int]`.

`insert(new_node: NewNode) -> Node` is the create method (renamed from `add`).
It takes a pre-persistence `NewNode` and returns the persisted `Node` carrying
the database-generated `node_id`. This mirrors `TaskRepository.insert(task) ->
Task`, which returns the enriched object. The implementation runs
`node/insert.sql ... RETURNING node_id`.

`get_by_id(node_id: NodeId) -> Node | None` is an additive lookup by primary
key. There is no batch `get_by_ids` (no consumer identified). A batch variant
mirroring `get_by_ips` is explicitly out of scope.

`add_tmp` takes only `cloud: str` — the `username` column on
`yascheduler_nodes` retains its `DEFAULT 'root'` and the tmp-row falls back to
that default. The tmp-row is a short-lived placeholder (`enabled=FALSE`)
removed before any reader touches it; no caller needs to supply a username.
`add_tmp`'s signature and return type (`-> str`, the generated placeholder ip)
are **unchanged** by this change; reworking it is a deferred follow-up.

All ip-keyed mutators (`get`, `enable`, `disable`, `remove`, `update`,
`get_by_ips`) keep their ip keying. `update(node)` keeps `WHERE ip = :ip`
internally (`ip UNIQUE` protects the write); switching these to
`WHERE node_id =` is an explicit non-goal, deferred until `ip UNIQUE` is
relaxed in a future change. This change **carries** `node_id`; it does not
**replace** ip-based identification.

#### Scenario: Full node lifecycle through port
- **WHEN** a consumer calls `insert`, `get`, `get_by_id`, `update`, `enable`, `disable`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `remove` through the port
- **THEN** the Protocol defines all these operations with async signatures

#### Scenario: Insert takes NewNode returns Node
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned whose `node_id` is the database-generated `NodeId` and whose other fields match the `NewNode`

#### Scenario: Get node by id
- **WHEN** `get_by_id(NodeId(5))` is called and a row with node_id=5 exists
- **THEN** a `Node` is returned with `node_id == NodeId(5)`; if no such row exists, `None` is returned

#### Scenario: Add temporary node takes only cloud
- **WHEN** `add_tmp("aws")` is called
- **THEN** a tmp-node row is inserted with `enabled=FALSE`, the given cloud, and `username` left to the DB default (`'root'`); the generated placeholder ip is returned (unchanged behavior)

### Requirement: MachineRepository, MachineSession, and MachineOperations ports

The system SHALL define three `@runtime_checkable` Protocols in
`yascheduler/domain/ports.py`:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_session`/`__contains__`/`__len__`).
  Returns `MachineSession` from `connect`/`list_free`/`list_connected`/
  `get_session`. SHALL NOT declare state transitions, accessor
  getters, or the monitor mechanism — those are on `MachineSession`.
- `MachineSession` — the connected-machine entity handle: identity
  (`ip`, `machine`), state transitions (`occupy`/`release`/`update`),
  connect-time config (`adapter`, `platforms`, `data_dir`,
  `engines_dir`, `tasks_dir`), adapter-derived accessors (`path`,
  `quote`, `hostname`), base primitives (`run`/`run_full`/`run_bg`/
  `upload`/`open_sftp`/`get_cpu_cores`/`setup_node`/`pgrep`/
  `list_processes`), monitor mechanism (`install_monitor`/
  `cancel_monitor`), and lifecycle (`is_closed`).
- `MachineOperations` — operations on a single machine, with method
  signatures taking `session: MachineSession`. Methods: `run`,
  `run_full`, `run_bg`, `get_cpu_cores`, `setup_node`,
  `start_task_on_machine`, `download_outputs`, `occupancy_check`,
  `start_occupancy_check`.

The full method-signature specification of these three Protocols lives
in the `ssh-infrastructure` capability spec (Requirement:
MachineRepository port, Requirement: MachineSession port, Requirement:
SSHMachineSession implements MachineSession, Requirement: MachineOperations port,
Requirement: SSHMachineOperations composition). The `domain-ports`
capability asserts only that all three Protocols are defined here, are
`@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades.

Application-layer consumers (`allocate_task.py`, `consume_task.py`,
`deallocate_nodes.py`, `abandon_node.py`, `orchestrator.py`) SHALL type
their SSH-side parameters against `MachineRepository`,
`MachineSession`, and/or `MachineOperations` (one or more, depending on
which methods they call).

#### Scenario: Import MachineRepository from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineRepository`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: Import MachineOperations from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineOperations`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: Import MachineSession from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineSession`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: All three Protocols are runtime_checkable

- **WHEN** `isinstance(repo_obj, MachineRepository)`,
  `isinstance(session_obj, MachineSession)`, and
  `isinstance(ops_obj, MachineOperations)` are evaluated
- **THEN** all three Protocols are `@runtime_checkable` and
  structural-subtype their implementations

#### Scenario: Application consumers type against the three Protocols

- **WHEN** `application/orchestrator.py`, `application/allocate_task.py`,
  `application/consume_task.py`, `application/deallocate_nodes.py`, and
  `application/abandon_node.py` are inspected for SSH-side parameter
  annotations
- **THEN** the annotations are `MachineRepository`, `MachineSession`,
  and/or `MachineOperations` (per the methods each consumer calls)

### Requirement: CloudConfig structural Protocol

The system SHALL define a `@runtime_checkable` `CloudConfig` Protocol in
`yascheduler/domain/ports.py` capturing the cloud-config surface that
application-layer consumers (`deallocate_nodes`, `orchestrator`) read.

The authoritative field list, the explicit-inheritance contract with the
`ConfigCloud*` DTOs, and the importability scenarios live in the `cloud-config`
capability. `domain-ports` asserts only that the Protocol is defined here, is
`@runtime_checkable`, and is exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades.

#### Scenario: CloudConfig importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str) -> NewNode` (async),
`deallocate(cloud: str, ip: str) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync).

`allocate` returns a `NewNode` (pre-persistence) — a freshly-built VM that has
NOT been written to `yascheduler_nodes`. The caller (`allocate_task`) persists
it via `NodeRepository.insert(new_node) -> Node`. Returning `NewNode` (rather
than `Node`) is honest about persistence state: a `Node` always carries a
`node_id`, which does not exist until `insert` runs.

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

`capacity()` is not part of the port — capacity counting is a use case /
orchestrator responsibility, not a cloud adapter concern.

`select_provider` returns the selected provider's name as a bare `str`,
matching the identity-string convention used across `NodeRepository`
(`get(ip: str)`, `remove(ip: str)`, `enable(ip: str)`, `disable(ip: str)`).
No `ProviderSelection` value object is defined; the application layer
treats the returned string as an opaque provider identity and passes it
back to `allocate`/`deallocate` unchanged.

#### Scenario: Allocate cloud node returns NewNode
- **WHEN** `allocate("aws")` is called with a valid provider name
- **THEN** returns a `NewNode` with the provisioned IP (no DB write inside the adapter; the caller persists via `NodeRepository.insert`)

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
including `CloudConfig`, `MachineRepository`, `MachineSession`, and
`MachineOperations`.

#### Scenario: Import ports for adapter implementation

- **WHEN** an adapter module imports `from yascheduler.domain.ports import TaskRepository`
- **THEN** the Protocol class is available for structural subtyping

#### Scenario: Import MachineRepository, MachineSession, and MachineOperations from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineRepository, MachineSession, MachineOperations`
- **THEN** all three Protocol classes resolve without ImportError
