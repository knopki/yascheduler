## MODIFIED Requirements

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol with async methods:
`get_by_id(node_id: NodeId) -> Node | None`,
`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]`,
`list_enabled() -> list[Node]`, `list_disabled() -> list[Node]`,
`list_all() -> list[Node]`, `insert(new_node: NewNode) -> Node`,
`update(node: Node) -> None`, `enable(node_id: NodeId) -> None`,
`disable(node_id: NodeId) -> None`, `remove(node_id: NodeId) -> None`,
`count_by_status() -> Mapping[bool, int]`.

The hostname-keyed lookup methods `get(ip: str)` and
`get_by_ips(ips: list[str])` are not part of the Protocol. All lookups key on
`NodeId`.

`insert(new_node: NewNode) -> Node` is the sole node-insertion path. It takes
a pre-persistence `NewNode` and returns the persisted `Node` carrying the
database-generated `node_id`. This mirrors `TaskRepository.insert(task) ->
Task`. The tmp-reservation flow SHALL use `insert` for tmp nodes too —
constructing `NewNode(cloud=selected_name, enabled=False)` (relying on
`NewNode`'s `hostname=""` and `ncpus=0` defaults) and persisting it to reserve
capacity; the returned `Node.node_id` is the tmp-node handle for cleanup AND
for reuse as the real node's identity.

`get_by_id(node_id: NodeId) -> Node | None` is the single-row lookup by
primary key.

`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]` is the batch
lookup by primary-key list, returning a dict keyed by `NodeId`.

The Protocol defines no `add_tmp` method. The tmp-reservation flow
calls `insert(NewNode(cloud=..., enabled=False)) -> Node` (returning the
`Node` whose `node_id` is the cleanup handle). There is exactly one
node-insertion method on the port.

The four mutators `enable(node_id: NodeId)`, `disable(node_id: NodeId)`,
`remove(node_id: NodeId)`, and `update(node: Node)` SHALL key on `node_id`.
`enable`/`disable`/`remove` take `NodeId` directly; `update` takes a `Node`
(which carries `node_id`).

The `list_*` methods remain unkeyed (return all/enabled/disabled; ordering
by `node_id` ascending is preserved on `list_all`).

#### Scenario: Insert takes NewNode returns Node

- **WHEN** `insert(NewNode(hostname="[IP]", ncpus=4))` is called
- **THEN** a `Node` is returned whose `node_id` is the database-generated `NodeId` and whose other fields match the `NewNode`

#### Scenario: Get node by id

- **WHEN** `get_by_id(NodeId(5))` is called and a row with node_id=5 exists
- **THEN** a `Node` is returned with `node_id == NodeId(5)`; if no such row exists, `None` is returned

#### Scenario: Remove takes NodeId

- **WHEN** `remove(NodeId(7))` is called
- **THEN** the node row with `node_id=7` is deleted; the key is `NodeId`, not `hostname`

### Requirement: MachineRepository, MachineSession, and MachineOperations ports

The system SHALL define `@runtime_checkable` Protocols for the SSH-side ports:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_session`/`__contains__`/`__len__`).
  Returns `MachineSession` from `connect`/`list_free`/`list_connected`/
  `get_session`.
- `MachineSession` — the connected-machine entity handle: identity
  (`hostname`, `machine`), state transitions (`occupy`/`release`/`update`),
  connect-time config, adapter-derived accessors, base primitives
  (`run`/`run_full`/`run_bg`/`upload`/`open_sftp`/`get_cpu_cores`/
  `setup_node`/`pgrep`/`list_processes`), monitor mechanism, and lifecycle.
  The former `ip` property is removed; it is replaced by `hostname`
  (merging with the existing adapter-derived `hostname` accessor — see the
  `ssh-infrastructure` spec for the full Protocol surface).

Full method-signature specification lives in the `ssh-infrastructure` spec.
`domain-ports` asserts only that these Protocols are defined, are
`@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades. Application-layer consumers SHALL type
their SSH-side collection parameter against `MachineRepository`.

The former `MachineOperations` Protocol is REMOVED. SSH-side operations
that previously hung off the facade are now invoked directly on the concrete
collaborator classes (`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`
from `yascheduler.infra.ssh.operations`). The facade pass-throughs
(`run`/`run_full`/`run_bg`/`get_cpu_cores`/`setup_node`) are now invoked
directly on the `MachineSession` instance every caller already holds.

#### Scenario: Two Protocols defined

- **WHEN** `yascheduler.domain.ports` is inspected
- **THEN** `MachineRepository` and `MachineSession` are defined as `@runtime_checkable` Protocols; no `MachineOperations` Protocol is present

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str, node: Node) -> Node` (async),
`deallocate(node: Node) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync).

`allocate` takes the tmp-node `Node` (post-insert identity — the row already
exists with the tmp `node_id`) and returns a `Node` reusing that same
`node_id`. The cloud adapter reuses the passed node's `node_id` as the real
node's identity. The returned `Node` carries the same `node_id`. This is one
row per cloud allocation lifecycle, not two.

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `str | None` (the selected provider name or
`None`), then calls `allocate(selection, node)`.

`allocate` SHALL set `external_id` alongside `hostname` in the returned
`Node` (both set to the cloud-provisioned address). `deallocate` takes the
`Node` and reads `node.cloud` (the provider name) and `node.hostname` (the
cloud SDK host identifier) internally — the caller no longer unpacks them.
When `node.cloud` is `None` the adapter SHALL log and return without deleting
a VM. `deallocate` stays hostname-keyed for the actual VM lookup —
`hostname` is the cloud SDK host identifier (migrating VM identification to a
`node_id`-derived tag is a future cloud-adapter change).

`select_provider` is sync — it does no I/O. It returns `None` when no
provider has capacity OR when the selected provider's op semaphore is
locked (throttle). The caller's `selection is None` branch handles
cleanup.

`capacity()` is not part of the port — capacity counting is a use case /
orchestrator responsibility, not a cloud adapter concern.

#### Scenario: allocate sets external_id alongside hostname
- **WHEN** `allocate(provider, node)` returns a `Node` with a cloud-provisioned address `ip_addr`
- **THEN** the returned `Node` has `hostname == ip_addr` AND `external_id == ip_addr`

#### Scenario: deallocate reads node.cloud and node.hostname
- **WHEN** `deallocate(node)` is called and `node.cloud` is not None
- **THEN** the adapter reads `node.cloud` (provider) and `node.hostname` (cloud host) to identify and delete the VM