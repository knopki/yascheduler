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

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str, tmp_node_id: NodeId) -> Node` (async),
`deallocate(cloud: str, ip: str) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync).

`allocate` returns a `Node` (post-persistence identity — the row already
exists with `node_id == tmp_node_id`). The caller (`allocate_task`) inserted
the tmp-node row via `uow.nodes.insert(NewNode(cloud=..., enabled=False)) ->
Node` and passes the returned `tmp_node_id` to `allocate`. The cloud adapter
reuses this `tmp_node_id` as the real node's identity: the setup SSH session
registers under `tmp_node_id`, and the returned `Node` carries
`node_id == tmp_node_id`. The caller then flips the row to `enabled=TRUE` and
sets `ip`/`ncpus` via a single `uow.nodes.update(node)`. This replaces the
prior `insert(NewNode) + remove(tmp_node_id)` pair — one row per cloud
allocation lifecycle, not two.

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `str | None` (the selected provider name or
`None`), then calls `allocate(selection, tmp_node_id)`.

`deallocate` takes `cloud` explicitly because the adapter no longer reads
the database to resolve the provider from `ip`. The caller (use case) has
the `Node` and passes `node.cloud`. `deallocate` stays ip-keyed — `ip` is
the cloud SDK host identifier (enriching it to carry `external_id`/`Node`
is a future cloud-adapter change).

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

#### Scenario: Allocate cloud node returns Node reusing tmp_node_id

- **WHEN** `allocate("aws", tmp_node_id=NodeId(7))` is called with a valid provider name
- **THEN** returns a `Node` with `node_id == NodeId(7)` (the tmp_node_id), a real `ip` (the provisioned VM's address), `enabled=True`, and `ncpus` populated from the VM; no DB write inside the adapter; the caller persists via `NodeRepository.update(node)`

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