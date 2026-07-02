## MODIFIED Requirements

### Requirement: PostgresNodeRepository implements NodeRepository

The system SHALL provide a `PostgresNodeRepository` class that satisfies
the `NodeRepository` Protocol with async methods: `get`, `get_by_id`,
`list_enabled`, `list_disabled`, `list_all`, `insert`, `add_tmp`, `update`,
`enable`, `disable`, `remove`, `get_by_ips`, `count_by_cloud`,
`count_by_status`.

`insert(new_node: NewNode) -> Node` (renamed from `add`) SHALL run
`node/insert.sql` with `RETURNING node_id` and return a `Node` carrying the
generated `NodeId`. The returned `Node`'s non-id fields SHALL match the input
`NewNode`. This mirrors `PostgresTaskRepository.insert(task) -> Task`.

`get_by_id(node_id: NodeId) -> Node | None` SHALL run `node/get_by_id.sql`
(`WHERE node_id = :node_id`), passing `node_id.value` as the SQL parameter
(pg8000 cannot adapt a `NodeId` dataclass). Returns `None` if no row matches.

`_row_to_node` SHALL read the `node_id` column from every node row and
construct `NodeId(int(row["node_id"]))`. Every node SELECT
(`get_by_ip`, `list_all`, `get_by_ips`, `list_enabled`, `list_disabled`,
`get_by_id`) SHALL include `node_id` in its column list so `_row_to_node`
always receives it.

`update(node: Node) -> None` SHALL keep `WHERE ip = :ip` (unchanged; `ip
UNIQUE` protects the write). The other ip-keyed mutators (`enable`, `disable`,
`remove`) and `add_tmp` are unchanged.

`add_tmp(cloud: str) -> str` inserts a tmp-node row with a generated IP,
`enabled=FALSE`, the given cloud, and `username` left to the DB default
(`yascheduler_nodes.username DEFAULT 'root'`). It SHALL NOT bind a
`:username` parameter; the `node/insert_tmp.sql` query lists only
`(ip, enabled, cloud)` columns. `add_tmp` is unchanged by this change.

`list_all()` SHALL return nodes ordered by `node_id` ascending
(`node/list_all.sql` includes `ORDER BY node_id`) so CLI output is
deterministic. `list_enabled()` and `list_disabled()` continue to post-filter
rows whose `ip` contains `"."` (excluding `prov*` placeholder temp rows).

#### Scenario: Insert returns Node with generated id
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a row is inserted and a `Node` is returned with `node_id == NodeId(<generated>)`, `ip="10.0.0.1"`, `ncpus=4`

#### Scenario: Get node by id
- **WHEN** `get_by_id(NodeId(5))` is called and a row with node_id=5 exists
- **THEN** returns a `Node` with `node_id == NodeId(5)`; the SQL parameter is bound as `node_id.value` (the bare int `5`)

#### Scenario: Get by id returns None when missing
- **WHEN** `get_by_id(NodeId(999))` is called and no row with node_id=999 exists
- **THEN** returns `None`

#### Scenario: Row mapping wraps NodeId
- **WHEN** any node SELECT returns a row `{"node_id": 7, "ip": "10.0.0.1", ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(7)`

#### Scenario: Add and retrieve node
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called followed by `get(ip="10.0.0.1")`
- **THEN** the returned Node matches the inserted values and carries its `node_id`

#### Scenario: List all nodes
- **WHEN** `list_all()` is called
- **THEN** returns all nodes regardless of enabled status, ordered by `node_id` ascending (deterministic CLI output)

#### Scenario: Enable and disable node
- **WHEN** `disable(ip)` is called on an enabled node, then `get(ip)`
- **THEN** `node.enabled` is False

#### Scenario: List enabled nodes
- **WHEN** `list_enabled()` is called with a mix of enabled and disabled nodes
- **THEN** returns only nodes with `enabled=True` and valid IPs (containing ".")

#### Scenario: Add temporary node
- **WHEN** `add_tmp(cloud)` is called
- **THEN** a node row is inserted with generated IP, the given cloud, and `username` defaulting to `'root'` (from the DB column default, not a caller-supplied value); the placeholder ip is returned (unchanged)

#### Scenario: Update node fields by ip
- **WHEN** `update(node)` is called with modified fields
- **THEN** all mutable fields are persisted, keyed by `WHERE ip = :ip` (unchanged)

#### Scenario: Get nodes by IPs
- **WHEN** `get_by_ips(["10.0.0.1", "10.0.0.2"])` is called
- **THEN** returns a dict keyed by IP for matching nodes; each value carries its `node_id`

#### Scenario: Count by cloud
- **WHEN** `count_by_cloud()` is called
- **THEN** returns a mapping of cloud provider name to node count

#### Scenario: Count by status
- **WHEN** `count_by_status()` is called
- **THEN** returns a mapping of enabled (bool) to node count

#### Scenario: Remove node
- **WHEN** `remove(ip)` is called
- **THEN** the node row is deleted from the database (unchanged, keyed by ip)
