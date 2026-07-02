## Why

`yascheduler_nodes` has no primary key. `ip VARCHAR(15) UNIQUE` is the de-facto identity
everywhere — `Node.ip`, `Task.allocated_ip`, `ConnectedMachine.ip`, `MachineSession.ip`,
and every `NodeRepository` mutator (`get`/`enable`/`disable`/`remove`/`get_by_ips` key on
ip). This is MVP legacy:

1. `ip` is nullable and carries a fake placeholder (`'prov'||MD5(...)`) for temp cloud
   nodes in `insert_tmp.sql`; `PostgresNodeRepository.list_enabled` post-filters
   `"." in r["ip"]` to exclude them — a workaround that exists only because temp nodes
   have no stable identifier.
2. `VARCHAR(15)` cannot hold IPv6 (separate legacy, but blocks any future `inet` move).
3. Address:port is not truly unique long-term: machines behind different jump hosts may
   be reachable via the same private address. `ip UNIQUE` forbids storing duplicates
   today, but the long-term direction is id-based identity.

This change introduces `node_id SERIAL PRIMARY KEY` and a domain value object `NodeId`,
then **carries** `node_id` alongside `ip`. It does **not** replace ip-based
identification — scope is deliberately narrow: learn to carry node_id without losing it
or crashing, add id-based node lookup, show node_id in CLIs, and accept it as input in
`yasetnode`. Wholesale replacement of ip-keyed identification is a sequence of future
changes; this change is their prerequisite.

## What Changes

- **Migration `002_add_node_id.sql`:** `ALTER TABLE yascheduler_nodes ADD COLUMN node_id
  SERIAL PRIMARY KEY;`. One statement; PostgreSQL assigns sequential values to existing
  rows, creates the sequence, and adds the PK constraint. Per the `db-migrations` edit
  procedure, also bump the `last_migration` CONSTANT in `schema.sql` (`'001' → '002'`)
  and add `node_id SERIAL PRIMARY KEY` as the first column of the `yascheduler_nodes`
  `CREATE TABLE` snapshot (keeping `ip VARCHAR(15) UNIQUE`).

- **Domain split — `NewNode` / `Node` / `NodeId`** (in `yascheduler/domain/model.py`,
  exported from `yascheduler.domain`):
  - `NodeId` — `@dataclass(frozen=True)` with `value: int`; `__post_init__` asserts
    `value > 0` (SERIAL starts at 1); `__str__` returns `str(self.value)` so CLI and
    logging render cleanly. Frozen → hashable → usable as a dict key. NOT equal to bare
    `int` (the type-safety point).
  - `NewNode` — frozen dataclass: `ip, ncpus, enabled=True, cloud=None, username='root',
    port=22` — the pre-persistence shape (NO node_id).
  - `Node` — frozen dataclass: the same fields plus `node_id: NodeId` — the
    post-persistence shape. A `Node` always carries its identity.
  - Conversion from `NewNode` to `Node` happens in **exactly one place**:
    `NodeRepository.insert` (the method that persists and receives the generated id).

- **`NodeRepository` Protocol** (`yascheduler/domain/ports.py`):
  - Rename `add(node: Node) -> None` → `insert(new_node: NewNode) -> Node`. The impl
    runs `insert.sql` with `RETURNING node_id` and returns a full `Node`. Consistent
    with `TaskRepository.insert(task) -> Task`.
  - Add `get_by_id(node_id: NodeId) -> Node | None`.
  - `update(node: Node) -> None` is **unchanged** (keeps `WHERE ip = :ip`; `ip UNIQUE`
    protects). `get(ip)`, `get_by_ips(ips)`, `enable(ip)`, `disable(ip)`, `remove(ip)`,
    `list_enabled`, `list_disabled`, `list_all`, `count_by_status`, `add_tmp(cloud) ->
    str` are all **unchanged**.

- **`PostgresNodeRepository`** (`yascheduler/infra/persistence/postgres.py`):
  - `insert(new_node: NewNode) -> Node` — runs `insert.sql ... RETURNING node_id`,
    builds `Node(node_id=NodeId(int(rows[0]["node_id"])), ...)` via `_row_to_node`.
  - `get_by_id(node_id: NodeId) -> Node | None` — runs new `node/get_by_id.sql`
    (`WHERE node_id = :node_id`), passing `node_id.value` as the SQL param (pg8000
    cannot adapt a dataclass).
  - `_row_to_node` reads `node_id` and wraps `NodeId(int(row["node_id"]))`.

- **SQL queries** (`yascheduler/infra/persistence/sql/node/`):
  - `insert.sql` gains `RETURNING node_id`.
  - New `get_by_id.sql`: `SELECT node_id, ip, ncpus, enabled, cloud, username, port FROM
    yascheduler_nodes WHERE node_id = :node_id;`.
  - The 5 existing SELECTs (`get_by_ip.sql`, `list_all.sql`, `get_by_ips.sql`,
    `list_enabled.sql`, `list_disabled.sql`) add `node_id` to their column lists.
    `list_all.sql` additionally gains `ORDER BY node_id` (deterministic CLI output).
  - `update.sql`, `enable.sql`, `disable.sql`, `remove.sql`, `insert_tmp.sql`,
    `count_by_cloud.sql`, `count_by_status.sql` are **unchanged**.

- **`CloudProvisioner.allocate`** (`yascheduler/domain/ports.py` Protocol and
  `yascheduler/infra/cloud/manager.py` impl): return type changes `Node → NewNode`.
  `_setup_vm` returns `NewNode(...)` instead of `Node(...)` (it builds a VM that has not
  been persisted yet — with `node_id` now required on `Node`, the old return was a type
  fiction; the split makes "pre-persistence" explicit). `allocate_task`'s call site
  (`application/allocate_task.py`, today `await uow.nodes.add(node)`) becomes
  `node = await uow.nodes.insert(new_node)` to obtain the persisted `Node`. `allocate`'s
  consumers (`orchestrator`, `deallocate_nodes`) see `NewNode` from `allocate` and, where
  they need the persisted identity, obtain it via `insert`'s return.

- **`yanodes`** (`yascheduler/entrypoints/cli/show_nodes.py`):
  - `_NodeView` gains `node_id: NodeId`.
  - `_fetch_nodes_view` sets `node_id=node.node_id`.
  - Table renderer: new `NODE_ID` column, placed FIRST (before `IP`).
  - JSON renderer: new `"node_id": int` field (serialized as `node.node_id.value`).

- **`yasetnode`** (`yascheduler/entrypoints/cli/manage_node.py`):
  - New positional argparse type `_parse_node_target(s) -> NodeTarget`. Discriminator:
    `s.isdigit()` → `NodeTarget(node_id=NodeId(int(s)), host_spec=None)`, else
    `NodeTarget(node_id=None, host_spec=_parse_host_spec(s))`. `_parse_host_spec` and its
    grammar are **untouched**.
  - `NodeTarget` is a frozen dataclass with `node_id: NodeId | None` and
    `host_spec: HostSpec | None` (exactly one is set).
  - Body validation: if `node_target.node_id is not None` and neither `--remove-soft` nor
    `--remove-hard` is set (i.e. the add path), call
    `parser.error("a node cannot be added by id; provide a host like user@host[:port][~ncpus]")`
    (exit 2) — a node cannot be added by id.
  - On the remove-by-id path: `uow.nodes.get_by_id(node_target.node_id)` → `Node` → use
    `node.ip` for `tasks.list_ids_by_ip_and_status(node.ip, ...)` and
    `nodes.disable/remove(node.ip)` (ip-keyed mutators are unchanged).
  - Validation UoW (`already_there` check): when `node_id` is given, resolve via
    `get_by_id`; when `host_spec` is given, via `get(ip)` (current behavior).

- **Out of scope (explicit non-goals):** `yastatus` node_id display;
  `MachineSession.node_id`; `ConnectedMachine.node_id`; changing `add_tmp`'s signature;
  switching `update/remove/enable/disable` to `WHERE node_id =`; relaxing the `ip UNIQUE`
  constraint. Each is a plausible follow-up change once node_id is carried.

No **BREAKING** changes to public APIs. The `Yascheduler` facade / Python client API is
unchanged (node management is CLI-only). The INI config format is unchanged. The DB
schema gains a PK column (additive; existing rows are backfilled by SERIAL). The
`CloudProvisioner.allocate` Protocol return type narrows from `Node` to `NewNode` — this
is an internal Protocol, not the public `Yascheduler` API; its consumers
(`orchestrator`, `deallocate_nodes`, `allocate_task`, and the unit/e2e tests that mock
`allocate`) are updated in the same change.

## Capabilities

### Modified Capabilities
- `domain-entities` — `Node` gains `node_id: NodeId`; add `NewNode` (pre-persistence)
  and `NodeId` (value object).
- `domain-ports` — `NodeRepository`: rename `add → insert` (returns `Node`), add
  `get_by_id`; `CloudProvisioner.allocate` return type `Node → NewNode`.
- `postgres-repositories` — `PostgresNodeRepository`: `insert`/`get_by_id`/`_row_to_node`
  updates; SELECT column lists grow `node_id`.
- `sql-queries` — `node/insert.sql` (`RETURNING node_id`), new `node/get_by_id.sql`, 5
  SELECTs grow `node_id`, `node/list_all.sql` gains `ORDER BY node_id`.
- `cli-commands` — `yanodes` table/JSON gain `node_id`; `yasetnode` positional accepts a
  node_id via the `NodeTarget` discriminator (grammar of `_parse_host_spec` unchanged).
- `db-migrations` — instance of the documented edit procedure (migration `002`, CONSTANT
  bump, snapshot DDL update); no contract change.
- `postgres-schema-apply` — the `schema.sql` snapshot content changes (the
  `yascheduler_nodes` `CREATE TABLE` gains `node_id SERIAL PRIMARY KEY` as its first
  column). The `apply_schema` *contract/behavior* is unchanged; only the snapshot text
  it loads is updated. Listed for blast-radius visibility.
