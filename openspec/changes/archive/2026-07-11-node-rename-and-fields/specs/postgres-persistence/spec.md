## MODIFIED Requirements

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with async
methods `get_by_id`, `get_by_ids`, `list_enabled`, `list_disabled`, `list_all`,
`insert`, `update`, `enable`, `disable`, `remove`, `count_by_cloud`,
`count_by_status`. The hostname-keyed methods `get(ip: str)` and `get_by_ips(ips:
list[str])` are REMOVED. `add_tmp` is **removed** — there is no `add_tmp`
method; the tmp-reservation flow uses `insert`.

`insert(new_node: NewNode) -> Node` SHALL run INSERT with RETURNING
`node_id` and return a `Node` carrying the generated `NodeId`. When called with
`NewNode(cloud=..., enabled=False)` (the tmp-reservation path, with `hostname=""`
and `ncpus=0` defaults from `NewNode`), it SHALL insert a row with
`hostname=""`, `enabled=FALSE`, the given `cloud`, and `username`/`port` from the
`NewNode` defaults (`"root"`, `22`). The returned `Node` carries the generated
`node_id`, which is the tmp-node cleanup handle AND the real-node identity
reused by `clouds.allocate`. `get_by_id(node_id: NodeId)` SHALL run
`WHERE node_id = :node_id`, passing `node_id.value`.
`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]` SHALL run
`WHERE node_id = ANY(:node_ids)`, passing
`[n.value for n in node_ids]` as the SQL param, and return a dict keyed by
`NodeId` (constructed from each row's `node_id`). Node row mapping SHALL read
`node_id` from every node row and construct `NodeId(int(row["node_id"]))`.

`list_all()` SHALL return nodes ordered by `node_id` ascending (the SQL
includes `ORDER BY node_id`); it returns ALL rows regardless of `enabled` or
`hostname` (including tmp rows with `hostname=""`), because the allocator counts
tmp rows toward `max_nodes` capacity.

`list_enabled()` SHALL filter `WHERE enabled = TRUE` with **no python
post-filter**.

`list_disabled()` SHALL filter `WHERE enabled = FALSE AND hostname <> ''`.

`enable(node_id: NodeId)`, `disable(node_id: NodeId)`, and
`remove(node_id: NodeId)` SHALL run with `WHERE node_id = :node_id`, binding
`node_id.value` as the SQL parameter.

`update(node: Node)` SHALL run with `WHERE node_id = :node_id`, binding
`node.node_id.value` as the key parameter alongside the field params
(`hostname`, `ncpus`, `enabled`, `cloud`, `username`, `port`, `jump_host`,
`jump_port`, `jump_username`, `external_id`, `status`). The `hostname` field
MUST be in the `SET` clause — the V1 cloud-allocation lifecycle relies on
`update` to flip the tmp row's `hostname` from `""` (the NewNode default) to
the real VM hostname in a single `UPDATE`; an `update` without `hostname` in
`SET` would leave cloud nodes unreachable after daemon restart and excluded
from `list_disabled`'s `WHERE hostname <> ''` filter (VM leak).

Node row mapping SHALL map `hostname=row["hostname"]` unchanged; `""` is a
valid `str` and the mapping works without changes. Row mapping SHALL also read
`created_at`, `updated_at`, `jump_host`, `jump_port`, `jump_username`,
`external_id`, and `status` (converting the `NODE_STATUS` label string to
`NodeStatus[row["status"]]`).

`count_by_status.sql` SHALL use `COUNT(node_id)` (not `COUNT(hostname)` or
`COUNT(*)`).

The `get(ip)`, `get_by_ips`, and `add_tmp` methods are removed — node lookups
use `get_by_id` / `get_by_ids` only, and the tmp path uses `insert`.

#### Scenario: Row mapping wraps NodeId
- **WHEN** any node SELECT returns a row `{"node_id": 7, "hostname": "[IP]", ...}`
- **THEN** the mapped `Node` has `node_id == NodeId(7)`

#### Scenario: Row mapping reads created_at and updated_at
- **WHEN** a node SELECT returns a row with `created_at` and `updated_at` columns
- **THEN** the mapped `Node` carries `created_at` and `updated_at` as `datetime` values

#### Scenario: Row mapping reads status as NodeStatus
- **WHEN** a node SELECT returns a row with `status = "OTHER"`
- **THEN** the mapped `Node` has `status == NodeStatus.OTHER`