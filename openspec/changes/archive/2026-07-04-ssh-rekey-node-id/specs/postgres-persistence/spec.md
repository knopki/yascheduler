## MODIFIED Requirements

### Requirement: SQL file layout and lazy loading

The system SHALL store all SQL queries in `infra/persistence/sql/` organized as
`sql/<entity>/<operation>.sql`, loaded via `load_query(name: str) -> str` which
reads the file from the package directory and caches the result (each file read
at most once per process).

- `sql/schema.sql` — the full latest snapshot (every `CREATE TABLE` includes
  all current columns; no inline `ALTER`s). The DO block's `last_migration`
  CONSTANT is the single manual edit point when a migration is added.
- `sql/migrations/` — forward-only migration files (`{prefix_id}_{rest}.sql`
  or `.py`), applied by `apply_migrations` in string-sorted `prefix_id` order.
- `sql/task/insert.sql` — `INSERT INTO yascheduler_tasks (label, metadata, ip,
  status, allocated_node_id) VALUES (:label, :metadata, :ip, :status, :node_id)
  RETURNING task_id, label, ip, status, metadata, allocated_node_id`.
- `sql/task/update_by_id.sql` — `UPDATE yascheduler_tasks SET label=:label,
  ip=:ip, status=:status, metadata=:metadata, allocated_node_id=:node_id WHERE
  task_id = :task_id RETURNING task_id` (partial update keyed by `task_id`; NOT
  an upsert).
- `sql/task/get_by_id.sql` — `SELECT task_id, label, ip, status, metadata,
  allocated_node_id FROM yascheduler_tasks WHERE task_id = :task_id`.
- `sql/task/list_by_status.sql` — `SELECT task_id, label, ip, status, metadata,
  allocated_node_id FROM yascheduler_tasks WHERE status IN (...) ORDER BY
  task_id LIMIT :lim`.
- `sql/task/list_by_jobs.sql` — `SELECT task_id, label, ip, status, metadata,
  allocated_node_id FROM yascheduler_tasks WHERE task_id IN (...) ORDER BY
  task_id`.
- `sql/task/update_status.sql` — `UPDATE yascheduler_tasks SET status=...
  WHERE task_id = :task_id RETURNING task_id` (status-only update; does NOT
  touch `allocated_node_id`).
- `sql/task/get_ids_by_ip_and_status.sql` — `SELECT task_id FROM
  yascheduler_tasks WHERE ip = :ip AND status = :status ORDER BY task_id`
  (returns task_ids only; this is a read-path lookup that stays ip-keyed —
  `ip` is the cloud host identifier, not node identity).
- `sql/task/count_by_status.sql` — aggregate; no `allocated_node_id` column.
- `sql/node/insert.sql` — `INSERT ... VALUES (...) RETURNING node_id`.
- `sql/node/get_by_id.sql` — `WHERE node_id = :node_id`.
- `sql/node/get_by_ids.sql` — `SELECT node_id, ip, ncpus, enabled, cloud,
  username, port FROM yascheduler_nodes WHERE node_id = ANY(:node_ids)` (batch
  lookup by primary-key list; returns 0..N rows).
- `sql/node/list_all.sql` — includes `ORDER BY node_id` (deterministic CLI output).
- `sql/node/enable.sql` — `UPDATE yascheduler_nodes SET enabled=TRUE WHERE node_id = :node_id`.
- `sql/node/disable.sql` — `UPDATE yascheduler_nodes SET enabled=FALSE WHERE node_id = :node_id`.
- `sql/node/remove.sql` — `DELETE FROM yascheduler_nodes WHERE node_id = :node_id`.
- `sql/node/update.sql` — `UPDATE yascheduler_nodes SET ... WHERE node_id = :node_id`.
- The ip-keyed SQL files `sql/node/get_by_ip.sql` and
  `sql/node/get_by_ips.sql` are REMOVED — no caller resolves a node by ip
  after the `ssh-rekey-node-id` change.
- Every node SELECT (`list_all`, `get_by_ids`, `list_enabled`,
  `list_disabled`, `get_by_id`) SHALL include `node_id` in its column list.

SQL files SHALL use `:param_name` syntax for pg8000 named-parameter binding.
The `:node_id` named parameter in task SQL files binds the
`allocated_node_id` column of `yascheduler_tasks`. The `:node_ids` named
parameter in `node/get_by_ids.sql` binds a list of `node_id.value` ints
(pg8000 adapts a Python list to a PostgreSQL array for `= ANY(:node_ids)`).

#### Scenario: load_query reads then caches

- **WHEN** `load_query("task/get_by_id")` is called twice
- **THEN** the file `sql/task/get_by_id.sql` is read from disk once; the second call returns the cached string

#### Scenario: Node list_all is ordered by node_id

- **WHEN** `sql/node/list_all.sql` is inspected
- **THEN** it contains `ORDER BY node_id`

#### Scenario: Node SELECTs include node_id

- **WHEN** any of `list_all.sql`, `get_by_ids.sql`, `list_enabled.sql`, `list_disabled.sql`, `get_by_id.sql` is inspected
- **THEN** the column list includes `node_id`

#### Scenario: get_by_ids.sql uses ANY array binding

- **WHEN** `sql/node/get_by_ids.sql` is inspected
- **THEN** the WHERE clause is `WHERE node_id = ANY(:node_ids)` and the column list includes `node_id, ip, ncpus, enabled, cloud, username, port`

#### Scenario: get_by_ip.sql and get_by_ips.sql are removed

- **WHEN** the `sql/node/` directory is inspected
- **THEN** `get_by_ip.sql` and `get_by_ips.sql` are NOT present; the only lookup SQL files are `get_by_id.sql` and `get_by_ids.sql`

#### Scenario: Node mutator SQL keys on node_id

- **WHEN** any of `sql/node/enable.sql`, `sql/node/disable.sql`, `sql/node/remove.sql`, `sql/node/update.sql` is inspected
- **THEN** the `WHERE` clause is `WHERE node_id = :node_id` (not `WHERE ip = :ip`)

#### Scenario: Task SELECTs include allocated_node_id

- **WHEN** any task SELECT clause (`get_by_id`, `list_by_status`, `list_by_jobs`) or `insert`'s RETURNING clause is inspected
- **THEN** the column list includes `allocated_node_id`

#### Scenario: Task insert binds allocated_node_id

- **WHEN** `sql/task/insert.sql` is inspected
- **THEN** the INSERT column list includes `allocated_node_id` and the RETURNING clause includes `allocated_node_id`; the VALUES binds `:node_id` for that column

#### Scenario: Task update_by_id binds allocated_node_id

- **WHEN** `sql/task/update_by_id.sql` is inspected
- **THEN** the SET clause includes `allocated_node_id = :node_id`

#### Scenario: Task update_status does not touch allocated_node_id

- **WHEN** `sql/task/update_status.sql` is inspected
- **THEN** the SET clause sets only `status`; `allocated_node_id` is NOT in the SET clause (status-only update)

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with async
methods `get_by_id`, `get_by_ids`, `list_enabled`, `list_disabled`, `list_all`,
`insert`, `update`, `enable`, `disable`, `remove`, `count_by_cloud`,
`count_by_status`. The ip-keyed methods `get(ip: str)` and `get_by_ips(ips:
list[str])` are REMOVED. `add_tmp` is **removed** — there is no `add_tmp`
method; the tmp-reservation flow uses `insert`.

`insert(new_node: NewNode) -> Node` SHALL run `node/insert.sql` with `RETURNING
node_id` and return a `Node` carrying the generated `NodeId`. When called with
`NewNode(cloud=..., enabled=False)` (the tmp-reservation path, with `ip=""`
and `ncpus=0` defaults from `NewNode`), it SHALL insert a row with
`ip=""`, `enabled=FALSE`, the given `cloud`, and `username`/`port` from the
`NewNode` defaults (`"root"`, `22`). The returned `Node` carries the generated
`node_id`, which is the tmp-node cleanup handle AND the real-node identity
reused by `clouds.allocate`. `get_by_id(node_id: NodeId)` SHALL run
`node/get_by_id.sql` (`WHERE node_id = :node_id`), passing `node_id.value`.
`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]` SHALL run
`node/get_by_ids.sql` (`WHERE node_id = ANY(:node_ids)`), passing
`[n.value for n in node_ids]` as the SQL param, and return a dict keyed by
`NodeId` (constructed from each row's `node_id`). `_row_to_node` SHALL read
`node_id` from every node row and construct `NodeId(int(row["node_id"]))`.

`list_all()` SHALL return nodes ordered by `node_id` ascending (the SQL
includes `ORDER BY node_id`); it returns ALL rows regardless of `enabled` or
`ip` (including tmp rows with `ip=""`), because `_count_nodes_by_cloud` in
`allocate_task` counts tmp rows toward `max_nodes` capacity.

`list_enabled()` SHALL run `node/list_enabled.sql` (`WHERE enabled = TRUE`)
with **no python post-filter**.

`list_disabled()` SHALL run `node/list_disabled.sql`
(`WHERE enabled = FALSE AND ip <> ''`).

`enable(node_id: NodeId)`, `disable(node_id: NodeId)`, and
`remove(node_id: NodeId)` SHALL run `node/{enable,disable,remove}.sql` with
`WHERE node_id = :node_id`, binding `node_id.value` as the SQL parameter.

`update(node: Node)` SHALL run `node/update.sql` with `WHERE node_id = :node_id`,
binding `node.node_id.value` as the key parameter alongside the field params
(`ip`, `ncpus`, `enabled`, `cloud`, `username`, `port`). The `ip` field MUST be
in the `SET` clause — the V1 cloud-allocation lifecycle relies on `update` to
flip the tmp row's `ip` from `""` (the NewNode default) to the real VM ip in a
single `UPDATE`; an `update.sql` without `ip` in `SET` would leave cloud nodes
unreachable after daemon restart and excluded from `list_disabled.sql`'s
`WHERE ip <> ''` filter (VM leak).

`_row_to_node` SHALL map `ip=row["ip"]` unchanged; `""` is a valid `str` and
the mapping works without changes.

#### Scenario: Insert returns Node with generated id

- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned with `node_id == NodeId(<generated>)` and matching non-id fields

#### Scenario: Get by id returns None when missing

- **WHEN** `get_by_id(NodeId(999))` is called and no row matches
- **THEN** returns `None`; the SQL parameter is bound as `node_id.value` (the bare int)

#### Scenario: Get by ids returns dict keyed by NodeId

- **WHEN** `get_by_ids([NodeId(5), NodeId(7)])` is called and rows with node_id=5 and node_id=7 exist
- **THEN** a `dict[NodeId, Node]` is returned with keys `NodeId(5)` and `NodeId(7)`; missing node_ids are absent from the dict; the SQL parameter is `[5, 7]` (the bare ints from `NodeId.value`)

#### Scenario: Get by ids with empty list returns empty dict

- **WHEN** `get_by_ids([])` is called
- **THEN** `node/get_by_ids.sql` runs with `:node_ids = []` (empty array); the result is empty; an empty `dict[NodeId, Node]` is returned

#### Scenario: Row mapping wraps NodeId

- **WHEN** any node SELECT returns a row `{"node_id": 7, "ip": "10.0.0.1", ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(7)`

#### Scenario: List all is ordered by node_id and includes tmp rows

- **WHEN** `list_all()` is called on a DB with a mix of enabled, disabled, and tmp (`ip=""`) rows
- **THEN** returns all rows (including `ip=""` tmp rows) ordered by `node_id` ascending

#### Scenario: List enabled has no python post-filter

- **WHEN** `list_enabled()` is called on a DB with enabled real nodes and disabled tmp rows (`ip=""`)
- **THEN** returns only `enabled=TRUE` rows (the SQL `WHERE enabled = TRUE` is the only filter); no python post-filter runs

#### Scenario: List disabled filters empty-ip rows in SQL

- **WHEN** `list_disabled()` is called on a DB with real-disabled VMs (`ip<>""`) and tmp rows (`ip=""`)
- **THEN** returns only disabled rows with `ip <> ""` (the SQL `WHERE enabled = FALSE AND ip <> ''` is the filter)

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

#### Scenario: Insert serves the tmp-reservation path

- **WHEN** `insert(NewNode(cloud="aws", enabled=False))` is called (relying on `NewNode.ip=""` and `NewNode.ncpus=0` defaults)
- **THEN** a row is inserted with `ip=""`, `enabled=FALSE`, `cloud="aws"`, `username="root"`, `port=22`; a `Node` is returned carrying the generated `node_id` (the tmp-node cleanup handle AND the real-node identity reused by `clouds.allocate`)

#### Scenario: Row mapping handles empty-string ip

- **WHEN** a node SELECT returns a row `{"node_id": 12, "ip": "", "enabled": false, ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(12)`, `ip == ""`, `enabled == False` (the `""` is a valid `str`, no mapping change)

#### Scenario: No get(ip) method

- **WHEN** `PostgresNodeRepository` is inspected for `get`
- **THEN** no `get(ip: str)` method is defined; node lookups are `get_by_id` / `get_by_ids` only

#### Scenario: No get_by_ips method

- **WHEN** `PostgresNodeRepository` is inspected for `get_by_ips`
- **THEN** no `get_by_ips(ips: list[str])` method is defined; batch lookups are `get_by_ids` only

#### Scenario: No add_tmp method

- **WHEN** `PostgresNodeRepository` is inspected for `add_tmp`
- **THEN** no `add_tmp` method is defined; the tmp path uses `insert`; `node/insert_tmp.sql` is removed from the SQL file layout