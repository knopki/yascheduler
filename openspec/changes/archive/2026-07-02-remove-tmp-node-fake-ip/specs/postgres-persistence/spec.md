## MODIFIED Requirements

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with async
methods `get`, `get_by_id`, `list_enabled`, `list_disabled`, `list_all`,
`insert`, `update`, `enable`, `disable`, `remove`, `get_by_ips`,
`count_by_cloud`, `count_by_status`. `add_tmp` is **removed** — there is no
`add_tmp` method; the tmp-reservation flow uses `insert`.

`insert(new_node: NewNode) -> Node` SHALL run `node/insert.sql` with `RETURNING
node_id` and return a `Node` carrying the generated `NodeId`. When called with
`NewNode(cloud=..., enabled=False)` (the tmp-reservation path, with `ip=""`
and `ncpus=0` defaults from `NewNode`), it SHALL insert a row with
`ip=""`, `enabled=FALSE`, the given `cloud`, and `username`/`port` from the
`NewNode` defaults (`"root"`, `22`). The returned `Node` carries the generated
`node_id`, which is the tmp-node cleanup handle. `get_by_id(node_id: NodeId)`
SHALL run `node/get_by_id.sql` (`WHERE node_id = :node_id`), passing
`node_id.value`. `_row_to_node` SHALL read `node_id` from every node row and
construct `NodeId(int(row["node_id"]))`.

`list_all()` SHALL return nodes ordered by `node_id` ascending (the SQL
includes `ORDER BY node_id`); it returns ALL rows regardless of `enabled` or
`ip` (including tmp rows with `ip=""`), because `_count_nodes_by_cloud` in
`allocate_task` counts tmp rows toward `max_nodes` capacity.

`list_enabled()` SHALL run `node/list_enabled.sql` (`WHERE enabled = TRUE`)
with **no python post-filter**. By the invariant (after this change,
`ip == ''` IFF `enabled = FALSE` AND the node is tmp/pending), no enabled row
has `ip=""`, so the prior `"." in r["ip"]` post-filter was dead code and is
removed.

`list_disabled()` SHALL run `node/list_disabled.sql`
(`WHERE enabled = FALSE AND ip <> ''`). The `ip <> ''` predicate is a
**presence check** (this disabled row has a real address → it is a
real-disabled VM with a VM to delete, not a tmp/pending row), not a format
check. The prior python `"." in r["ip"]` post-filter is removed. Callers
outside `allocate_task` (e.g. `deallocate_nodes.py`) retain their own
caller-side `"." in node.ip` post-filters; those are out of scope and remain
correct (redundant for `ip=""` rows now excluded by SQL, still filtering
non-ipv4 hostnames).

`enable(node_id: NodeId)`, `disable(node_id: NodeId)`, and
`remove(node_id: NodeId)` SHALL run `node/{enable,disable,remove}.sql` with
`WHERE node_id = :node_id`, binding `node_id.value` as the SQL parameter
(pg8000 cannot adapt a `NodeId` dataclass — same pattern as `get_by_id`).

`update(node: Node)` SHALL run `node/update.sql` with `WHERE node_id = :node_id`,
binding `node.node_id.value` as the key parameter alongside the field params
(`ncpus`, `enabled`, `cloud`, `username`, `port`).

`_row_to_node` SHALL map `ip=row["ip"]` unchanged; `""` is a valid `str` and
the mapping works without changes.

#### Scenario: Insert returns Node with generated id
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned with `node_id == NodeId(<generated>)` and matching non-id fields

#### Scenario: Insert serves the tmp-reservation path
- **WHEN** `insert(NewNode(cloud="aws", enabled=False))` is called (relying on `NewNode.ip=""` and `NewNode.ncpus=0` defaults)
- **THEN** a row is inserted with `ip=""`, `enabled=FALSE`, `cloud="aws"`, `username="root"`, `port=22`; a `Node` is returned carrying the generated `node_id` (the tmp-node cleanup handle)

#### Scenario: Get by id returns None when missing
- **WHEN** `get_by_id(NodeId(999))` is called and no row matches
- **THEN** returns `None`; the SQL parameter is bound as `node_id.value` (the bare int)

#### Scenario: Row mapping wraps NodeId
- **WHEN** any node SELECT returns a row `{"node_id": 7, "ip": "10.0.0.1", ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(7)`

#### Scenario: Row mapping handles empty-string ip
- **WHEN** a node SELECT returns a row `{"node_id": 12, "ip": "", "enabled": false, ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(12)`, `ip == ""`, `enabled == False` (the `""` is a valid `str`, no mapping change)

#### Scenario: List all is ordered by node_id and includes tmp rows
- **WHEN** `list_all()` is called on a DB with a mix of enabled, disabled, and tmp (`ip=""`) rows
- **THEN** returns all rows (including `ip=""` tmp rows) ordered by `node_id` ascending

#### Scenario: List enabled has no python post-filter
- **WHEN** `list_enabled()` is called on a DB with enabled real nodes and disabled tmp rows (`ip=""`)
- **THEN** returns only `enabled=TRUE` rows (the SQL `WHERE enabled = TRUE` is the only filter); no python post-filter runs (the prior `"." in r["ip"]` is removed); by the invariant no enabled row has `ip=""`

#### Scenario: List disabled filters empty-ip rows in SQL
- **WHEN** `list_disabled()` is called on a DB with real-disabled VMs (`ip<>""`) and tmp rows (`ip=""`)
- **THEN** returns only disabled rows with `ip <> ""` (the SQL `WHERE enabled = FALSE AND ip <> ''` is the filter); no python post-filter runs (the prior `"." in r["ip"]` is removed); the `ip <> ''` is a presence check, not a format check

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

#### Scenario: No add_tmp method
- **WHEN** `PostgresNodeRepository` is inspected for `add_tmp`
- **THEN** no `add_tmp` method is defined; the tmp path uses `insert`; `node/insert_tmp.sql` is removed from the SQL file layout