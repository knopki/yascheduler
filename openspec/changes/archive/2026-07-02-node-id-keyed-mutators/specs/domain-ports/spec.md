## MODIFIED Requirements

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol with async methods:
`get(ip: str) -> Node | None`, `get_by_id(node_id: NodeId) -> Node | None`,
`list_enabled() -> list[Node]`, `list_disabled() -> list[Node]`,
`list_all() -> list[Node]`, `insert(new_node: NewNode) -> Node`,
`add_tmp(cloud: str) -> str`, `update(node: Node) -> None`,
`enable(node_id: NodeId) -> None`, `disable(node_id: NodeId) -> None`, `remove(node_id: NodeId) -> None`,
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