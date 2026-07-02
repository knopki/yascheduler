# Explore Brief — add-node-id-identity

## Problem
`yascheduler_nodes` has **no primary key**. `ip VARCHAR(15) UNIQUE` is the de-facto
identity everywhere: `Node.ip`, `Task.allocated_ip`, `ConnectedMachine.ip`,
`MachineSession.ip`, and every `NodeRepository` mutator (`get/enable/disable/remove/
get_by_ips` key on ip). This is MVP legacy for three reasons:

1. `ip` is nullable and carries a fake placeholder (`'prov'||MD5(...)`) for temp cloud
   nodes (`insert_tmp.sql`); `list_enabled` post-filters `"." in r["ip"]` to exclude
   them — a костыль that exists only because temp nodes have no stable id.
2. `VARCHAR(15)` cannot hold IPv6 (separate legacy, but blocks any future `inet` move).
3. Address:port is not truly unique long-term: machines behind different jump hosts may
   be reachable via the same private address. `ip UNIQUE` forbids storing duplicates
   today, but the long-term direction is id-based identity.

This change introduces `node_id SERIAL PRIMARY KEY` and a domain value object
`NodeId`, then **carries** `node_id` alongside `ip` — it does NOT replace ip-based
identification. Scope is deliberately narrow: learn to carry node_id without losing it,
add id-based lookup, show it in CLIs, accept it in `yasetnode`.

## Rejected alternatives
- **`Node.node_id: int | None = None` (nullable)** — every consumer must handle `None`;
  uncomfortable and leaky. Rejected in favor of a `NewNode` (pre-persistence) / `Node`
  (post-persistence, always carries `NodeId`) split, so the type system makes "node not
  yet persisted" unrepresentable as a `Node`.
- **`NodeId = typing.NewType('NodeId', int)`** — zero runtime type safety (erased to
  `int`); no methods, no validation. Rejected in favor of a frozen dataclass value
  object `NodeId(value: int)`.
- **`NodeId` as an `int` subclass** — defeats value-object ergonomics and the explicit
  user decision ("frozen dataclass with value: int"). Rejected.
- **`get_by_ids` (batch lookup mirroring `get_by_ips`)** — no consumer identified.
  Rejected; only `get_by_id` is added.
- **`yasetnode` accepts node_id via a `--node-id N` flag** — rejected; a "smart"
  positional (`yasetnode 5`) is more ergonomic, matches the id-first long-term vision,
  and avoids a host/flag mutual-exclusion tangle. Discriminator: `s.isdigit()` → node_id.
- **Rewriting `_parse_host_spec` grammar to include the integer branch inline** — the
  grammar and its dozen `cli-commands` spec scenarios are frozen; rewriting them is
  high-churn. Rejected in favor of a `NodeTarget` wrapper produced by a new positional
  type `_parse_node_target`, leaving `_parse_host_spec` untouched.
- **Changing `add_tmp(cloud) -> str` now** — the temp-cloud reservation path is
  sensitive (used as an allocation slot marker in `allocate_task`); its `tmp_ip` ripple
  is out of scope. Deferred to a follow-up. (This is the most "fake-ip-as-handle" place,
  so it is the highest-value follow-up target.)
- **Switching `update/remove/enable/disable` `WHERE ip=` to `WHERE node_id=` now** —
  scope discipline; this change carries node_id, it does not replace ip. `ip UNIQUE`
  still protects ip-keyed writes today. Deferred to a future change that relaxes
  `ip UNIQUE`.
- **`MachineSession.node_id` / `ConnectedMachine.node_id` in this change** — no consumer
  reads them yet; including them is scope creep. Deferred.
- **`yastatus` node_id display now** — node_id is not consumed on that path yet.
  Deferred.
- **Renaming `update → save` alongside `add → insert`** — over-alignment with
  `TaskRepository`'s `save`; extra churn for no semantic gain. Only `add → insert`.

## Final approach (decisions locked with user)
| Axis | Decision |
|---|---|
| Migration | New `migrations/002_add_node_id.sql`: `ALTER TABLE yascheduler_nodes ADD COLUMN node_id SERIAL PRIMARY KEY;`. Bump `schema.sql` `last_migration` CONSTANT `'001' → '002'`. Update snapshot `CREATE TABLE` to list `node_id SERIAL PRIMARY KEY` first (ip stays `VARCHAR(15) UNIQUE`). |
| Domain split | `NewNode` (frozen; fields `ip, ncpus, enabled=True, cloud=None, username='root', port=22` — NO node_id) = pre-persistence. `Node` (frozen; same fields + `node_id: NodeId`) = post-persistence. Conversion happens ONLY in `NodeRepository.insert` (the one place that persists and assigns id). |
| `NodeId` | `@dataclass(frozen=True) class NodeId: value: int` with `__post_init__` asserting `value > 0` (SERIAL ≥ 1) and `__str__` returning `str(self.value)` (so CLI/logging render cleanly). NOT equal to bare `int` (the point). Frozen → hashable → usable as dict key. |
| `NodeRepository.insert` | Replaces `add(node)->None`. Signature `async insert(new_node: NewNode) -> Node`. SQL `insert.sql` gains `RETURNING node_id`; impl builds full `Node` with `NodeId(int(row["node_id"]))`. Consistent with `TaskRepository.insert(task)->Task`. |
| `NodeRepository.update` | UNCHANGED signature `(node: Node) -> None`; keeps `WHERE ip = :ip` (ip UNIQUE protects). |
| `NodeRepository.get_by_id` | NEW `async get_by_id(node_id: NodeId) -> Node | None`. SQL `get_by_id.sql` `WHERE node_id = :node_id` (param passed as `node_id.value`). |
| Existing ip-keyed API | `get(ip)`, `get_by_ips(ips)`, `enable/disable/remove(ip)`, `list_*`, `count_*` — ALL unchanged. `add_tmp(cloud)->str` UNCHANGED. |
| `CloudProvisioner.allocate` | Return type `Node → NewNode` (it returns a pre-persistence VM). `_setup_vm → NewNode`. `allocate_task` calls `insert(new_node) -> Node` to persist. |
| `_row_to_node` | Reads `node_id` from every row; builds `Node(node_id=NodeId(int(row["node_id"])), ...)`. |
| SELECTs | All 5 node SELECTs (`get_by_ip`, `list_all`, `get_by_ips`, `list_enabled`, `list_disabled`) add `node_id` to the column list. `list_all.sql` additionally gains `ORDER BY node_id` (deterministic CLI output). |
| `yanodes` | `_NodeView` gains `node_id: NodeId`. Table: new `NODE_ID` column FIRST. JSON: new `"node_id": int` field. `_fetch_nodes_view` reads `node.node_id`. |
| `yasetnode` | New positional type `_parse_node_target(s) -> NodeTarget` discriminates `s.isdigit() → NodeId(int(s))` else `_parse_host_spec(s)`. `NodeTarget` frozen: `node_id: NodeId | None`, `host_spec: HostSpec | None` (exactly one set). `_parse_host_spec` grammar UNCHANGED. Body validates `node_id present AND add-path` via `parser.error` (exit 2). On remove-by-id: `get_by_id` → `Node` → use `node.ip` for task lookup + ip-keyed mutators. |
| `yastatus` | OUT of scope. |
| `MachineSession` / `ConnectedMachine` | OUT of scope (deferred). |
| Public `Yascheduler` facade / client API | UNCHANGED (node ops are CLI-only; facade exposes task submit/query only). |

## Cross-module data flows
- **Create (CLI add):** `yasetnode 1.2.3.4` → `_parse_host_spec` (host grammar) →
  `_add_node` builds `NewNode(ip=spec.host, port, username, ncpus, enabled=True)` →
  `uow.nodes.insert(new_node)` runs `insert.sql ... RETURNING node_id` → `Node`.
  SSH `connect(ip=spec.host, ...)` still happens BEFORE insert (no node_id yet) —
  unchanged.
- **Create (cloud):** `allocate_task` → `provisioner.allocate(provider)` → `_setup_vm`
  returns `NewNode(ip=ip_addr, ncpus, enabled=True, cloud, username, port=22)` →
  `uow.nodes.insert(new_node)` → `Node` (today's `nodes.add(node)` call site at
  `allocate_task.py:381` becomes `insert`).
- **Read by id (yasetnode remove-by-id):** `yasetnode 5 --remove-soft` →
  `_parse_node_target("5")` → `NodeTarget(node_id=NodeId(5))` →
  `uow.nodes.get_by_id(NodeId(5))` runs `get_by_id.sql` (`:node_id` = `5`) →
  `Node | None` → remove helpers use `node.ip` for
  `tasks.list_ids_by_ip_and_status(node.ip, ...)` and `nodes.disable/remove(node.ip)`.
- **List (yanodes):** `uow.nodes.list_all()` → `list_all.sql` (SELECT includes node_id,
  `ORDER BY node_id`) → `[Node]` → `_NodeView(node_id=node.node_id, ...)` →
  table/JSON render.
- **Migration apply:** `yainit` → `apply_schema` (snapshot now has `node_id SERIAL
  PRIMARY KEY`) → `apply_migrations` → `002_add_node_id.sql` (`ALTER TABLE ... ADD
  COLUMN node_id SERIAL PRIMARY KEY`). Fresh DB: gets node_id via snapshot, seeded to
  `'002'` (migration skipped). Legacy DB: snapshot is no-op (`CREATE TABLE IF NOT
  EXISTS`), migration adds node_id + backfills existing rows with SERIAL values.

## Open questions
All resolved (see Decisions table above). None outstanding.
