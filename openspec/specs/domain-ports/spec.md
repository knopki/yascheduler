## Purpose

Defines abstract port interfaces (typing.Protocol) for the domain layer: TaskRepository, NodeRepository, MachineRepository, MachineOperations, and CloudProvisioner — contracts that infrastructure adapters must implement.

## Requirements

### Requirement: TaskRepository port

The system SHALL define a `TaskRepository` Protocol with async methods:
`get(task_id: TaskId) -> Task | None`, `save(task: Task) -> None`,
`insert(new_task: NewTask) -> Task`,
`list_by_status(statuses: set[TaskStatus], *, limit: int | None = None) -> list[Task]`,
`list_by_jobs(job_ids: list[TaskId]) -> list[Task]`,
`update_status(task_id: TaskId, status: TaskStatus) -> None`,
 `list_ids_by_node_id_and_status(node_id: NodeId, status: TaskStatus) -> list[TaskId]`,
 `count_by_status() -> Mapping[TaskStatus, int]`.

The method `list_ids_by_ip_and_status(ip: str, status: TaskStatus) -> list[TaskId]`
is REMOVED and replaced by
`list_ids_by_node_id_and_status(node_id: NodeId, status: TaskStatus) -> list[TaskId]`.
The filter key changes from `ip` (the transport address, which is no longer
stored on `yascheduler_tasks` after migration 009 drops the `ip` column) to
`node_id` (the canonical allocation identity, already carried by `Task` as
`allocated_node_id`). Both callers (`entrypoints/cli/manage_node._remove_node_hard`
and `_remove_node_soft`) already hold a fully-resolved `Node` with
`node.node_id`, so the signature change is source-compatible at the call sites
(they pass `node.node_id` instead of `node.ip`).

`insert` takes `NewTask` (pre-persistence) and returns `Task` (post-persistence,
carrying the generated `TaskId`); it is the sole `NewTask → Task` conversion
site. `get`, `update_status`, `list_ids_by_node_id_and_status` (return), and
`list_by_jobs` (input) use `TaskId` — the domain is type-safe end-to-end. The
public `Yascheduler` facade (see `package-facades`) is the sole `int`/`TaskId`
boundary: it wraps `TaskId(int)` on input and extracts `.value` on output.

The `TaskRepository` Protocol SHALL define an async `list_by_status` method
with an optional `limit` parameter for bounded queries. `save`,
`list_by_status`, and `count_by_status` are unchanged in signature (they
take/return `Task` / mappings, which carry `TaskId` internally).

#### Scenario: Repository method signatures are async
- **WHEN** a class implements `TaskRepository` with matching async method signatures
- **THEN** it satisfies the Protocol structurally

#### Scenario: List tasks by status without limit
- **WHEN** `list_by_status({TaskStatus.TO_DO})` is called
- **THEN** returns all tasks with TO_DO status (each `Task` carries a `TaskId`)

#### Scenario: List tasks by status with limit
- **WHEN** `list_by_status({TaskStatus.TO_DO}, limit=10)` is called
- **THEN** returns at most 10 tasks with TO_DO status

#### Scenario: insert converts NewTask to Task
- **WHEN** `insert(new_task)` is called with a `NewTask` (no `task_id`)
- **THEN** a `Task` carrying the DB-generated `TaskId` is returned (the sole `NewTask → Task` conversion)

#### Scenario: get takes TaskId
- **WHEN** `get(TaskId(42))` is called
- **THEN** returns a `Task` (with `task_id: TaskId`) or `None`

#### Scenario: update_status takes TaskId
- **WHEN** `update_status(TaskId(42), TaskStatus.RUNNING)` is called
- **THEN** the status of the task with `task_id=42` is updated (the `TaskId` is the key)

#### Scenario: list_ids_by_node_id_and_status returns TaskIds
- **WHEN** `list_ids_by_node_id_and_status(NodeId("n1"), TaskStatus.RUNNING)` is called
- **THEN** returns a `list[TaskId]` (not `list[int]`); the caller feeds them directly to `update_status(TaskId, ...)`

#### Scenario: list_by_jobs takes TaskIds
- **WHEN** `list_by_jobs([TaskId(1), TaskId(2), TaskId(3)])` is called
- **THEN** returns tasks whose `task_id` is in the given list of `TaskId`s

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol with async methods:
`get_by_id(node_id: NodeId) -> Node | None`,
`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]`,
`list_enabled() -> list[Node]`, `list_disabled() -> list[Node]`,
`list_all() -> list[Node]`, `insert(new_node: NewNode) -> Node`,
`update(node: Node) -> None`, `enable(node_id: NodeId) -> None`,
`disable(node_id: NodeId) -> None`, `remove(node_id: NodeId) -> None`,
`count_by_status() -> Mapping[bool, int]`.

The ip-keyed lookup methods `get(ip: str)` and `get_by_ips(ips:
list[str])` are REMOVED. After this change, no caller resolves a node
by ip. `manage_node`'s host_spec path resolves the node via `get_by_id`
through `NodeTarget` (`target.node_id` is set by the parser when the
operator passes a node_id; the host_spec path resolves the node through
a validation UoW and passes the `Node` forward). `check_status` flips
to `get_by_ids`. Removing the ip-keyed methods prevents future
ip-keyed regressions.

`insert(new_node: NewNode) -> Node` is the sole node-insertion path. It takes
a pre-persistence `NewNode` and returns the persisted `Node` carrying the
database-generated `node_id`. This mirrors `TaskRepository.insert(task) ->
Task`. The implementation runs `node/insert.sql ... RETURNING node_id`. The
tmp-reservation flow (cloud provisioning critical section in `allocate_task`)
SHALL use `insert` for tmp nodes too — constructing
`NewNode(cloud=selected_name, enabled=False)` (relying on `NewNode`'s
`ip=""` and `ncpus=0` defaults) and persisting it to reserve capacity; the
returned `Node.node_id` is the tmp-node handle for cleanup AND for reuse as
the real node's identity (see the `cloud` capability's `allocate` contract).

`get_by_id(node_id: NodeId) -> Node | None` is the single-row lookup by
primary key (unchanged).

`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]` is the batch
lookup by primary-key list, returning a dict keyed by `NodeId`. It is
the node_id-keyed analog of the removed `get_by_ips`. The
implementation runs `node/get_by_ids.sql` with
`WHERE node_id = ANY(:node_ids)`. `check_status` is the primary
consumer (batch-resolves nodes for all running tasks in one
round-trip).

The Protocol defines no `add_tmp` method. The tmp-reservation flow
calls `insert(NewNode(cloud=..., enabled=False)) -> Node` (returning the
`Node` whose `node_id` is the cleanup handle). There is exactly one
node-insertion method on the port.

The four mutators `enable(node_id: NodeId)`, `disable(node_id: NodeId)`,
`remove(node_id: NodeId)`, and `update(node: Node)` SHALL key on `node_id`.
`enable`/`disable`/`remove` take `NodeId` directly; `update` takes a `Node`
(which carries `node_id`) and the implementation SHALL bind `node.node_id.value`
as the SQL key. The implementation runs `node/{enable,disable,remove,update}.sql`
with `WHERE node_id = :node_id`.

The `list_*` methods remain unkeyed (return all/enabled/disabled; ordering
by `node_id` ascending is preserved on `list_all`).

#### Scenario: Full node lifecycle through port

- **WHEN** a consumer calls `insert`, `get_by_id`, `get_by_ids`, `update`, `enable`, `disable`, `list_enabled`, `list_disabled`, `list_all`, `remove` through the port
- **THEN** the Protocol defines all these operations with async signatures; `get(ip)` and `get_by_ips(ips)` are NOT defined; `add_tmp` is NOT defined

#### Scenario: Insert takes NewNode returns Node

- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned whose `node_id` is the database-generated `NodeId` and whose other fields match the `NewNode`

#### Scenario: Insert serves the tmp-reservation path

- **WHEN** `insert(NewNode(cloud="aws", enabled=False))` is called (relying on `NewNode.ip=""` and `NewNode.ncpus=0` defaults)
- **THEN** a tmp-node row is inserted with `ip=""`, `enabled=FALSE`, `cloud="aws"`, `username="root"` (default), `port=22` (default); a `Node` is returned carrying the generated `node_id` (the cleanup handle AND the real-node identity reused by `clouds.allocate`)

#### Scenario: Get node by id

- **WHEN** `get_by_id(NodeId(5))` is called and a row with node_id=5 exists
- **THEN** a `Node` is returned with `node_id == NodeId(5)`; if no such row exists, `None` is returned

#### Scenario: Get nodes by ids returns dict keyed by NodeId

- **WHEN** `get_by_ids([NodeId(5), NodeId(7)])` is called and rows with node_id=5 and node_id=7 exist
- **THEN** a `dict[NodeId, Node]` is returned with keys `NodeId(5)` and `NodeId(7)` mapping to the respective `Node` objects; missing node_ids are absent from the dict (not mapped to `None`)

#### Scenario: No get(ip) method on the port

- **WHEN** the `NodeRepository` Protocol is inspected for `get`
- **THEN** no `get(ip: str)` method is defined; node lookups are `get_by_id` / `get_by_ids` only

#### Scenario: No get_by_ips method on the port

- **WHEN** the `NodeRepository` Protocol is inspected for `get_by_ips`
- **THEN** no `get_by_ips(ips: list[str])` method is defined; batch lookups are `get_by_ids` only

#### Scenario: No add_tmp method on the port

- **WHEN** the `NodeRepository` Protocol is inspected for `add_tmp`
- **THEN** no `add_tmp` method is defined; tmp-node insertion goes through `insert`

#### Scenario: Enable takes NodeId

- **WHEN** `enable(NodeId(7))` is called
- **THEN** the node with `node_id=7` is enabled; the key is `NodeId`, not `ip`

#### Scenario: Disable takes NodeId

- **WHEN** `disable(NodeId(7))` is called
- **THEN** the node with `node_id=7` is disabled; the key is `NodeId`, not `ip`

#### Scenario: Remove takes NodeId

- **WHEN** `remove(NodeId(7))` is called
- **THEN** the node row with `node_id=7` is deleted; the key is `NodeId`, not `ip`

#### Scenario: Update takes Node and keys on node_id

- **WHEN** `update(node)` is called with a `Node` carrying `node_id=NodeId(7)`
- **THEN** the row with `node_id=7` is updated; the SQL `WHERE` clause keys on `node_id`, not `ip`
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
`ConfigCloud*` DTOs, and the importability scenarios live in the `cloud`
capability. `domain-ports` asserts only that the Protocol is defined here, is
`@runtime_checkable`, and is exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades.

#### Scenario: CloudConfig importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str, node: Node) -> Node` (async),
`deallocate(node: Node) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync).

`allocate` takes the tmp-node `Node` (post-insert identity — the row already
exists with the tmp `node_id`) and returns a `Node` reusing that same
`node_id`. The caller (`allocate_task`) inserted the tmp-node row via
`uow.nodes.insert(NewNode(cloud=..., enabled=False)) -> Node` and passes that
`Node` to `allocate`. The cloud adapter reuses the passed node's `node_id` as
the real node's identity: the setup SSH session registers under it, and the
returned `Node` carries the same `node_id`. The caller then flips the row to
`enabled=TRUE` and sets `ip`/`ncpus` via a single `uow.nodes.update(node)`.
This is one row per cloud allocation lifecycle, not two.

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `str | None` (the selected provider name or
`None`), then calls `allocate(selection, node)`.

`deallocate` takes the `Node` and reads `node.cloud` (the provider name) and
`node.ip` (the cloud SDK host identifier) internally — the caller no longer
unpacks them. When `node.cloud` is `None` the adapter SHALL log and return
without deleting a VM. `deallocate` stays ip-keyed for the actual VM lookup —
`ip` is the cloud SDK host identifier (migrating VM identification to a
`node_id`-derived tag is a future cloud-adapter change).

`select_provider` is sync — it does no I/O. It returns `None` when no
provider has capacity OR when the selected provider's op semaphore is
locked (throttle). The caller's `selection is None` branch handles
cleanup.

`capacity()` is not part of the port — capacity counting is a use case /
orchestrator responsibility, not a cloud adapter concern.

`select_provider` returns the selected provider's name as a bare `str`,
matching the identity-string convention used across `NodeRepository`
(`get_by_id(node_id)`, `remove(node_id)`, `enable(node_id)`,
`disable(node_id)`). No `ProviderSelection` value object is defined; the
application layer treats the returned string as an opaque provider identity
and passes it back to `allocate`/`deallocate` unchanged.

#### Scenario: Allocate cloud node returns Node reusing the passed node's identity

- **WHEN** `allocate("aws", node)` is called with a valid provider name and a tmp-node `Node` carrying `node_id == NodeId(7)`
- **THEN** returns a `Node` with `node_id == NodeId(7)`, a real `ip` (the provisioned VM's address), `enabled=True`, and `ncpus` populated from the VM; no DB write inside the adapter; the caller persists via `NodeRepository.update(node)`

#### Scenario: Deallocate cloud node reads provider and host from the node

- **WHEN** `deallocate(node)` is called with a `Node` carrying `cloud="aws"` and `ip="10.0.0.1"`
- **THEN** the VM at `10.0.0.1` is deleted via the `aws` provider's SDK

#### Scenario: Deallocate no-ops when node has no cloud

- **WHEN** `deallocate(node)` is called with a `Node` whose `cloud` is `None`
- **THEN** no provider SDK is invoked; the adapter logs and returns

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
