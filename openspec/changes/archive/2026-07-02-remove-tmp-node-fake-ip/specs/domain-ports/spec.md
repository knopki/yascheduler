## MODIFIED Requirements

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol with async methods:
`get(ip: str) -> Node | None`, `get_by_id(node_id: NodeId) -> Node | None`,
`list_enabled() -> list[Node]`, `list_disabled() -> list[Node]`,
`list_all() -> list[Node]`, `insert(new_node: NewNode) -> Node`,
`update(node: Node) -> None`, `enable(node_id: NodeId) -> None`,
`disable(node_id: NodeId) -> None`, `remove(node_id: NodeId) -> None`,
`get_by_ips(ips: list[str]) -> dict[str, Node]`, `count_by_status() -> Mapping[bool, int]`.

`insert(new_node: NewNode) -> Node` is the sole node-insertion path. It takes
a pre-persistence `NewNode` and returns the persisted `Node` carrying the
database-generated `node_id`. This mirrors `TaskRepository.insert(task) ->
Task`. The implementation runs `node/insert.sql ... RETURNING node_id`. The
tmp-reservation flow (cloud provisioning critical section in `allocate_task`)
SHALL use `insert` for tmp nodes too — constructing
`NewNode(cloud=selected_name, enabled=False)` (relying on `NewNode`'s
`ip=""` and `ncpus=0` defaults) and persisting it to reserve capacity; the
returned `Node.node_id` is the tmp-node handle for cleanup.

`get_by_id(node_id: NodeId) -> Node | None` is the lookup by primary key.
There is no batch `get_by_ids` (no consumer identified). A batch variant
mirroring `get_by_ips` is explicitly out of scope.

The four mutators `enable(node_id: NodeId)`, `disable(node_id: NodeId)`,
`remove(node_id: NodeId)`, and `update(node: Node)` SHALL key on `node_id`.
`enable`/`disable`/`remove` take `NodeId` directly; `update` takes a `Node`
(which carries `node_id`) and the implementation SHALL bind `node.node_id.value`
as the SQL key. The implementation runs `node/{enable,disable,remove,update}.sql`
with `WHERE node_id = :node_id`.

The lookup methods `get(ip: str)`, `get_by_ips(ips: list[str])`, and the
`list_*` methods remain ip-keyed / unkeyed — switching them to `node_id` is an
explicit non-goal of this change (deferred until the ip-keyed orchestrator
queues that feed them are migrated).

`add_tmp` is **removed** by this change. The tmp-reservation flow that
previously called `add_tmp(cloud) -> str` (returning a fake placeholder IP)
now calls `insert(NewNode(cloud=..., enabled=False)) -> Node` (returning the
`Node` whose `node_id` is the cleanup handle). There is exactly one
node-insertion method on the port.

#### Scenario: Full node lifecycle through port
- **WHEN** a consumer calls `insert`, `get`, `get_by_id`, `update`, `enable`, `disable`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `remove` through the port
- **THEN** the Protocol defines all these operations with async signatures; `add_tmp` is NOT defined on the Protocol

#### Scenario: Insert takes NewNode returns Node
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned whose `node_id` is the database-generated `NodeId` and whose other fields match the `NewNode`

#### Scenario: Insert serves the tmp-reservation path
- **WHEN** `insert(NewNode(cloud="aws", enabled=False))` is called (relying on `NewNode.ip=""` and `NewNode.ncpus=0` defaults)
- **THEN** a tmp-node row is inserted with `ip=""`, `enabled=FALSE`, `cloud="aws"`, `username="root"` (default), `port=22` (default); a `Node` is returned carrying the generated `node_id` (the cleanup handle)

#### Scenario: Get node by id
- **WHEN** `get_by_id(NodeId(5))` is called and a row with node_id=5 exists
- **THEN** a `Node` is returned with `node_id == NodeId(5)`; if no such row exists, `None` is returned

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

#### Scenario: No add_tmp method on the port
- **WHEN** the `NodeRepository` Protocol is inspected for `add_tmp`
- **THEN** no `add_tmp` method is defined; tmp-node insertion goes through `insert`