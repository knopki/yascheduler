## Purpose

Define abstract port contracts so domain use cases stay decoupled from persistence, SSH, and cloud provider implementations.
## Requirements
### Requirement: TaskRepository port

The system SHALL define a `TaskRepository` Protocol (`@runtime_checkable`, async methods):
`get(task_id: TaskId) -> Task | None`,
`save(task: Task) -> None`,
`insert(new_task: NewTask) -> Task`,
`list_by_status(statuses: set[TaskStatus], *, limit: int | None = None) -> list[Task]`,
`list_by_jobs(job_ids: list[TaskId]) -> list[Task]`,
`update_status(task_id: TaskId, status: TaskStatus) -> None`,
`list_ids_by_node_id_and_status(node_id: NodeId, status: TaskStatus) -> list[TaskId]`,
`count_by_status() -> Mapping[TaskStatus, int]`.

#### Scenario: Repository method signatures are async

- **WHEN** a class implements `TaskRepository` with matching async method signatures
- **THEN** it satisfies the Protocol structurally

#### Scenario: insert converts NewTask to Task

- **WHEN** `insert(new_task)` is called with a `NewTask` (no `task_id`)
- **THEN** a `Task` carrying the DB-generated `TaskId` is returned

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol (`@runtime_checkable`, async methods):
`get_by_id(node_id: NodeId) -> Node | None`,
`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]`,
`list_enabled() -> list[Node]`,
`list_disabled() -> list[Node]`,
`list_all() -> list[Node]`,
`insert(new_node: NewNode) -> Node`,
`update(node: Node) -> None`,
`enable(node_id: NodeId) -> None`,
`disable(node_id: NodeId) -> None`,
`remove(node_id: NodeId) -> None`,
`count_by_status() -> Mapping[bool, int]`.

All lookups and mutators SHALL key on `NodeId`. `list_all` SHALL return nodes ordered by `node_id` ascending.

#### Scenario: Insert takes NewNode returns Node

- **WHEN** `insert(NewNode(hostname="[IP]", ncpus=4))` is called
- **THEN** a `Node` is returned whose `node_id` is the database-generated `NodeId` and whose other fields match the `NewNode`

#### Scenario: Get node by id

- **WHEN** `get_by_id(NodeId(5))` is called and a row with `node_id=5` exists
- **THEN** a `Node` is returned with `node_id == NodeId(5)`; if no such row exists, `None` is returned

#### Scenario: Remove takes NodeId

- **WHEN** `remove(NodeId(7))` is called
- **THEN** the node row with `node_id=7` is deleted

### Requirement: MachineRepository and MachineSession ports

The system SHALL define `@runtime_checkable` Protocols for the SSH-side ports:

- `MachineRepository` — connected-machine collection lifecycle and queries, returning `MachineSession` from `connect`/`list_free`/`list_connected`/`get_session`.
- `MachineSession` — the connected-machine entity handle.

Full method-signature specification lives in the `ssh-infrastructure` spec. `domain-ports` asserts only that these Protocols are defined, are `@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and `yascheduler.domain` facades.

#### Scenario: Two Protocols defined

- **WHEN** `yascheduler.domain.ports` is inspected
- **THEN** `MachineRepository` and `MachineSession` are defined as `@runtime_checkable` Protocols

### Requirement: CloudConfig structural Protocol

The system SHALL define a `@runtime_checkable` `CloudConfig` Protocol. The authoritative field list, DTO inheritance contract, and importability scenarios live in the `cloud` spec.

#### Scenario: CloudConfig Protocol defined

- **WHEN** `yascheduler.domain.ports` is inspected
- **THEN** `CloudConfig` is defined as a `@runtime_checkable` Protocol

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol:
`allocate(provider: str, node: Node) -> Node` (async),
`deallocate(node: Node) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync),
`stop() -> None` (async).

`allocate` SHALL return a `Node` that reuses the passed node's `node_id` and SHALL set both `hostname` and `external_id` to the cloud-provisioned address. When `node.cloud` is `None`, `deallocate` SHALL log and return without deleting a VM. `select_provider` SHALL perform no I/O and SHALL return `None` when no provider has capacity or the selected provider's op semaphore is locked.

#### Scenario: Allocate returns Node reusing the passed node's identity

- **WHEN** `allocate("aws", node)` is called with a valid provider name and a tmp-node `Node` carrying `node_id == NodeId(7)`
- **THEN** returns a `Node` with `node_id == NodeId(7)`, a real `hostname`, `external_id == hostname`, `enabled=True`, and `ncpus` populated from the VM; no DB write inside the adapter

#### Scenario: deallocate reads node.cloud and node.hostname

- **WHEN** `deallocate(node)` is called and `node.cloud` is not None
- **THEN** the adapter reads `node.cloud` (provider) and `node.hostname` (cloud host) to identify and delete the VM

#### Scenario: deallocate on cloud=None is a no-op

- **WHEN** `deallocate(node)` is called and `node.cloud` is None
- **THEN** the adapter logs and returns without attempting deletion

#### Scenario: Select provider returns provider name string or None

- **WHEN** `select_provider(["linux"], {"aws": 0})` is called and aws has capacity and supports linux
- **THEN** returns the string `"aws"`; returns `None` when no capacity or the op semaphore is locked

