## MODIFIED Requirements

### Requirement: SQL file layout and lazy loading

The system SHALL store all SQL queries in `infra/persistence/sql/` organized as
`sql/<entity>/<operation>.sql`, loaded via `load_query(name: str) -> str` which
reads the file from the package directory and caches the result (each file read
at most once per process).

- `sql/task/update_by_id.sql` — `UPDATE yascheduler_tasks SET ... WHERE task_id = :task_id ... RETURNING task_id` (partial update keyed by `task_id`; NOT an upsert).
- `sql/task/update_status.sql` — includes `RETURNING task_id` so the repository detects a 0-row outcome.
- `sql/task/insert.sql` — `... RETURNING task_id, label, ip, status, metadata`.
- `sql/node/insert.sql` — `INSERT ... VALUES (...) RETURNING node_id`.
- `sql/node/get_by_id.sql` — `WHERE node_id = :node_id`.
- `sql/node/list_all.sql` — includes `ORDER BY node_id` (deterministic CLI output).
- `sql/node/enable.sql` — `UPDATE yascheduler_nodes SET enabled=TRUE WHERE node_id = :node_id`.
- `sql/node/disable.sql` — `UPDATE yascheduler_nodes SET enabled=FALSE WHERE node_id = :node_id`.
- `sql/node/remove.sql` — `DELETE FROM yascheduler_nodes WHERE node_id = :node_id`.
- `sql/node/update.sql` — `UPDATE yascheduler_nodes SET ... WHERE node_id = :node_id`.
- Every node SELECT (`get_by_ip`, `list_all`, `get_by_ips`, `list_enabled`, `list_disabled`, `get_by_id`) SHALL include `node_id` in its column list.

SQL files SHALL use `:param_name` syntax for pg8000 named-parameter binding.

#### Scenario: load_query reads then caches
- **WHEN** `load_query("task/get_by_id")` is called twice
- **THEN** the file `sql/task/get_by_id.sql` is read from disk once; the second call returns the cached string

#### Scenario: Node list_all is ordered by node_id
- **WHEN** `sql/node/list_all.sql` is inspected
- **THEN** it contains `ORDER BY node_id`

#### Scenario: Node SELECTs include node_id
- **WHEN** any of `get_by_ip.sql`, `list_all.sql`, `get_by_ips.sql`, `list_enabled.sql`, `list_disabled.sql`, `get_by_id.sql` is inspected
- **THEN** the column list includes `node_id`

#### Scenario: Node mutator SQL keys on node_id
- **WHEN** any of `sql/node/enable.sql`, `sql/node/disable.sql`, `sql/node/remove.sql`, `sql/node/update.sql` is inspected
- **THEN** the `WHERE` clause is `WHERE node_id = :node_id` (not `WHERE ip = :ip`)

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with async
methods `get`, `get_by_id`, `list_enabled`, `list_disabled`, `list_all`,
`insert`, `add_tmp`, `update`, `enable`, `disable`, `remove`, `get_by_ips`,
`count_by_cloud`, `count_by_status`.

`insert(new_node: NewNode) -> Node` SHALL run `node/insert.sql` with `RETURNING
node_id` and return a `Node` carrying the generated `NodeId`. `get_by_id(node_id:
NodeId)` SHALL run `node/get_by_id.sql` (`WHERE node_id = :node_id`), passing
`node_id.value`. `_row_to_node` SHALL read `node_id` from every node row and
construct `NodeId(int(row["node_id"]))`. `list_all()` SHALL return nodes ordered
by `node_id` ascending; `list_enabled()` / `list_disabled()` continue to
post-filter rows whose `ip` contains `"."` (excluding `prov*` placeholders).

`enable(node_id: NodeId)`, `disable(node_id: NodeId)`, and
`remove(node_id: NodeId)` SHALL run `node/{enable,disable,remove}.sql` with
`WHERE node_id = :node_id`, binding `node_id.value` as the SQL parameter
(pg8000 cannot adapt a `NodeId` dataclass — same pattern as `get_by_id`).

`update(node: Node)` SHALL run `node/update.sql` with `WHERE node_id = :node_id`,
binding `node.node_id.value` as the key parameter alongside the field params
(`ip`, `ncpus`, `enabled`, `cloud`, `username`, `port`).

`add_tmp(cloud)` inserts a disabled tmp-node with a
generated `prov*` IP and `username` left to the DB default (`'root'`); it SHALL
NOT bind a `:username` parameter.

#### Scenario: Insert returns Node with generated id
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned with `node_id == NodeId(<generated>)` and matching non-id fields

#### Scenario: Get by id returns None when missing
- **WHEN** `get_by_id(NodeId(999))` is called and no row matches
- **THEN** returns `None`; the SQL parameter is bound as `node_id.value` (the bare int)

#### Scenario: Row mapping wraps NodeId
- **WHEN** any node SELECT returns a row `{"node_id": 7, "ip": "10.0.0.1", ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(7)`

#### Scenario: List all is ordered by node_id
- **WHEN** `list_all()` is called
- **THEN** returns all nodes regardless of enabled status, ordered by `node_id` ascending

#### Scenario: Add temporary node
- **WHEN** `add_tmp(cloud)` is called
- **THEN** a node row is inserted with a `prov*` IP, `enabled=FALSE`, the given cloud, and `username` defaulting to `'root'` (DB default, no caller-supplied value)

#### Scenario: Enable binds node_id.value
- **WHEN** `enable(NodeId(7))` is called
- **THEN** `node/enable.sql` runs with `:node_id` bound to `7` (the bare int from `NodeId.value`)

#### Scenario: Disable binds node_id.value
- **WHEN** `disable(NodeId(7))` is called
- **THEN** `node/disable.sql` runs with `:node_id` bound to `7` (the bare int from `NodeId.value`)

#### Scenario: Remove binds node_id.value
- **WHEN** `remove(NodeId(7))` is called
- **THEN** `node/remove.sql` runs with `:node_id` bound to `7` (the bare int from `NodeId.value`)

#### Scenario: Update binds node.node_id.value as key
- **WHEN** `update(node)` is called with a `Node` whose `node_id == NodeId(7)`
- **THEN** `node/update.sql` runs with `:node_id` bound to `7` (from `node.node_id.value`) as the `WHERE` key, alongside the field params