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

#### Scenario: insert converts NewTask to Task
- **WHEN** `insert(new_task)` is called with a `NewTask` (no `task_id`)
- **THEN** a `Task` carrying the DB-generated `TaskId` is returned (the sole `NewTask → Task` conversion)

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

#### Scenario: Insert takes NewNode returns Node

- **WHEN** `insert(NewNode(ip="[IP]", ncpus=4))` is called
- **THEN** a `Node` is returned whose `node_id` is the database-generated `NodeId` and whose other fields match the `NewNode`

#### Scenario: Get node by id

- **WHEN** `get_by_id(NodeId(5))` is called and a row with node_id=5 exists
- **THEN** a `Node` is returned with `node_id == NodeId(5)`; if no such row exists, `None` is returned

#### Scenario: Remove takes NodeId

- **WHEN** `remove(NodeId(7))` is called
- **THEN** the node row with `node_id=7` is deleted; the key is `NodeId`, not `ip`

### Requirement: MachineRepository, MachineSession, and MachineOperations ports

The system SHALL define `@runtime_checkable` Protocols in
`yascheduler/domain/ports.py` for the SSH-side ports:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_session`/`__contains__`/`__len__`).
  Returns `MachineSession` from `connect`/`list_free`/`list_connected`/
  `get_session`.
- `MachineSession` — the connected-machine entity handle: identity
  (`ip`, `machine`), state transitions (`occupy`/`release`/`update`),
  connect-time config, adapter-derived accessors, base primitives
  (`run`/`run_full`/`run_bg`/`upload`/`open_sftp`/`get_cpu_cores`/
  `setup_node`/`pgrep`/`list_processes`), monitor mechanism, and lifecycle.

Full method-signature specification lives in the `ssh-infrastructure` spec.
`domain-ports` asserts only that these Protocols are defined here, are
`@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades. Application-layer consumers SHALL type
their SSH-side collection parameter against `MachineRepository`.

The former `MachineOperations` Protocol is REMOVED. SSH-side operations
that previously hung off the facade (`start_task_on_machine`,
`download_outputs`, `occupancy_check`, `start_occupancy_check`) are now
invoked directly on the concrete collaborator classes (`TaskDeployer`,
`OutputDownloader`, `OccupancyChecker` from
`yascheduler.infra.ssh.operations`). The facade pass-throughs
(`run`/`run_full`/`run_bg`/`get_cpu_cores`/`setup_node`) are now invoked
directly on the `MachineSession` instance every caller already holds.

#### Scenario: Two Protocols defined in domain/ports.py

- **WHEN** `yascheduler.domain.ports` is inspected
- **THEN** `MachineRepository` and `MachineSession` are defined as `@runtime_checkable` Protocols; no `MachineOperations` Protocol is present

### Requirement: CloudConfig structural Protocol

The system SHALL define a `@runtime_checkable` `CloudConfig` Protocol in
`yascheduler/domain/ports.py`. The authoritative field list, DTO inheritance
contract, and importability scenarios live in the `cloud` spec.

#### Scenario: CloudConfig Protocol defined in domain/ports.py
- **WHEN** `yascheduler.domain.ports` is inspected
- **THEN** `CloudConfig` is defined as a `@runtime_checkable` Protocol

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

#### Scenario: Select provider returns provider name string or None

- **WHEN** `select_provider(["linux"], {"aws": 0})` is called and aws has capacity and supports linux
- **THEN** returns the string `"aws"`; returns `None` when no capacity or op semaphore is locked


