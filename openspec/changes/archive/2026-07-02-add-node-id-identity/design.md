## Context

`yascheduler_nodes` has no primary key. `ip VARCHAR(15) UNIQUE` (`schema.sql:22`) is the
de-facto identity at every layer: `Node.ip` (`domain/model.py:376`), `Task.allocated_ip`,
`ConnectedMachine.ip` (`domain/model.py:388`), `MachineSession.ip` (`domain/ports.py:154`,
`infra/ssh/session.py:114`), and the entire `NodeRepository` surface (`domain/ports.py:73`)
— `get/enable/disable/remove/get_by_ips` all key on ip. `ip` is nullable and carries a
fake `'prov'||MD5(...)` placeholder for temp cloud nodes (`sql/node/insert_tmp.sql`);
`PostgresNodeRepository.list_enabled` post-filters `"." in r["ip"]` (`postgres.py:290`) to
exclude them. `Node` is a frozen dataclass (`model.py:372`); `NodeRepository` is a
`@runtime_checkable Protocol`.

Key codebase anchors (frozen unless this change touches them):

- `NodeRepository.add(node: Node) -> None` (`ports.py:82`) — the create method; its impl
  `PostgresNodeRepository.add` (`postgres.py:311`) runs `node/insert.sql` (a plain
  `INSERT`, no `RETURNING`). Callers: `application/allocate_task.py:381`
  (`await uow.nodes.add(node)` to persist a cloud node) and
  `entrypoints/cli/manage_node.py:278` (CLI add).
- `TaskRepository.insert(task: Task) -> Task` (`ports.py:59`, impl `postgres.py:164`) —
  the consistency anchor: it runs `task/insert.sql` with `RETURNING task_id` and returns
  the enriched `Task`. `NodeRepository.insert` will mirror this shape.
- `CloudProvisioner.allocate(provider: str) -> Node` (`ports.py:343`); impl
  `CloudProvisionerImpl.allocate` (`infra/cloud/manager.py:149`) delegates to
  `_setup_vm` (`manager.py:341`) which builds and returns `Node(ip=ip_addr, ncpus, ...)`
  (`manager.py:402`) **before** the node is persisted. Persistence happens later in
  `allocate_task.py:381`. Consumers of `allocate`: `orchestrator`, `deallocate_nodes`,
  `allocate_task`, plus unit/e2e mocks.
- `add_tmp(cloud: str) -> str` (`ports.py:84`, impl `postgres.py:330`) returns the fake
  prov-ip; the single caller `allocate_task.py:274` (`tmp_ip = await
  uow.nodes.add_tmp(selected_name)`) uses it as an in-flight allocation marker.
- `PostgresNodeRepository._row_to_node` (`postgres.py:433`) maps a DB row dict to `Node`.
- The 5 node SELECT files (`sql/node/get_by_ip.sql`, `list_all.sql`, `get_by_ips.sql`,
  `list_enabled.sql`, `list_disabled.sql`) each select `ip, ncpus, enabled, cloud,
  username, port`.
- `yanodes` = `show_nodes.py`: `_NodeView` (frozen DTO, `show_nodes.py:49`), table columns
  `IP, PORT, NCPUS, ENABLED, CLOUD, TASK_ID, LABEL` (`show_nodes.py:195`), JSON schema
  (`show_nodes.py:233`). `_fetch_nodes_view` joins `tasks_by_ip` (`show_nodes.py:127`).
- `yasetnode` = `manage_node.py`: `_parse_host_spec` grammar `[user@]host[:port][~ncpus]`
  → `HostSpec` (`manage_node.py:67`); helpers `_add_node`/`_remove_node_soft`/
  `_remove_node_hard` key everything on `spec.host` (treated as ip).
- Migration system (`db-migrations` spec): `apply_migrations` scans
  `infra/persistence/sql/migrations/`, applies pending `{prefix_id}_*` files in
  string-sorted order; the edit procedure is (1) create the file, (2) bump the
  `last_migration` CONSTANT in `schema.sql`'s DO block (`schema.sql:8`), (3) update the
  snapshot DDL. Today `last_migration = '001'`; one migration exists
  (`001_add_username_port.sql`).

## Design

### The identity problem and the carrying strategy

The change introduces `node_id SERIAL PRIMARY KEY` and a `NodeId` value object, then
**carries** node_id alongside ip. It does not replace ip-based identification: `ip` remains
the key for `Task.allocated_ip`, `ConnectedMachine.ip`, `MachineSession`, and every
existing ip-keyed mutator. The `ip UNIQUE` constraint still protects ip-keyed writes, so
keeping `WHERE ip =` in `update/remove/enable/disable` is safe today; switching those to
`WHERE node_id =` is an explicit non-goal, deferred until `ip UNIQUE` is relaxed in a
future change. This change is the prerequisite for that future: it makes a stable,
non-ip identity available everywhere a `Node` flows.

### Domain model: `NewNode` / `Node` / `NodeId`

A nullable `node_id: int | None` was rejected because it forces every consumer to handle
`None`. Instead the type system expresses persistence state:

```python
@dataclass(frozen=True)
class NodeId:
    value: int
    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError(f"NodeId must be > 0, got {self.value}")
    def __str__(self) -> str:
        return str(self.value)

@dataclass(frozen=True)
class NewNode:
    """Pre-persistence node record — no identity yet."""
    ip: str
    ncpus: int
    enabled: bool = True
    cloud: str | None = None
    username: str = "root"
    port: int = 22

@dataclass(frozen=True)
class Node:
    """Post-persistence node record — always carries its identity."""
    node_id: NodeId
    ip: str
    ncpus: int
    enabled: bool = True
    cloud: str | None = None
    username: str = "root"
    port: int = 22
```

`node_id` is the **first** field of `Node` (identity first); `NewNode` mirrors the
non-id fields with identical defaults. Field order for `Node` puts `node_id` before
`ip`/`ncpus` (both required) — valid for dataclasses since `node_id` has no default and
precedes other required fields; the defaulted fields follow. Construction sites use
keyword args (verified at `manage_node.py:279`, `manager.py:402`, `postgres.py:436`), so
reordering is safe.

The conversion `NewNode → Node` happens in **exactly one place**:
`NodeRepository.insert`. No other code constructs a `Node` from a `NewNode`; a `Node` only
ever comes from the database (via `_row_to_node`) or from `insert`'s return. This makes
"don't lose node_id" structural rather than convention-based.

`NodeId` is a frozen dataclass, not `typing.NewType` (which erases to `int` at runtime and
gives no methods/validation) and not an `int` subclass (which defeats value-object
ergonomics). `__post_init__` enforces `value > 0` (SERIAL starts at 1), catching
accidental `0`/negative ids at construction. `__str__` returns the bare integer string so
CLI rendering and logging produce `5`, not `NodeId(value=5)`.

#### `NodeId` at boundaries

Because `NodeId` is intentionally not an `int`, every external boundary must handle the
unwrap explicitly:

- **pg8000 params** — `get_by_id.sql` uses `WHERE node_id = :node_id`;
  `PostgresNodeRepository.get_by_id` passes `node_id=node_id.value` (pg8000 cannot adapt a
  dataclass). Same for any future node_id-keyed param.
- **DB read** — `_row_to_node` wraps `NodeId(int(row["node_id"]))`. pg8000 returns
  `node_id` as a Python `int`.
- **JSON** (`yanodes --json`) — `"node_id": node.node_id.value`. Explicit `.value` (a
  dataclass is not JSON-serializable).
- **CLI table / logging** — `str(node.node_id)` or f-`{node.node_id}` render via
  `__str__`.
- **argparse** — `_parse_node_target` does `NodeId(int(s))` after `s.isdigit()` validates
  the token.

`NodeId` is hashable (frozen) and usable as a dict key, but `NodeId(5) == 5` is `False` —
the type-safety point. Callers must not mix `NodeId` and bare `int` keys.

### `NodeRepository`: `insert` and `get_by_id`

```python
async def insert(self, new_node: NewNode) -> Node: ...
async def get_by_id(self, node_id: NodeId) -> Node | None: ...
```

`insert` replaces `add` and mirrors `TaskRepository.insert`:
`insert.sql` becomes `INSERT INTO yascheduler_nodes (ip, ncpus, enabled, cloud, username,
port) VALUES (...) RETURNING node_id;`. The impl runs it, reads `rows[0]["node_id"]`, and
returns `_row_to_node` of the returned row (or constructs `Node` directly from
`new_node`'s fields plus `NodeId(int(rows[0]["node_id"]))`). Returning the full `Node`
(not just `NodeId`) avoids a second `get_by_id` round-trip in `allocate_task` and the CLI
add path, and matches `TaskRepository.insert -> Task`.

`get_by_id` is additive — a new `node/get_by_id.sql` selecting all columns
`WHERE node_id = :node_id`. No batch `get_by_ids` (no consumer identified; rejected).

Unchanged ip-keyed API: `get(ip)`, `get_by_ips(ips)`, `enable(ip)`, `disable(ip)`,
`remove(ip)`, `update(node)` (keeps `WHERE ip = :ip`), `list_enabled`, `list_disabled`,
`list_all`, `count_by_status`, `add_tmp(cloud) -> str`, `count_by_cloud`. `update`'s
argument is now a `Node` (which carries `node_id`), but the SQL still keys on ip — a
deliberate scope boundary, not an oversight.

### `CloudProvisioner.allocate → NewNode`: the non-obvious ripple

Today `_setup_vm` (`manager.py:402`) returns `Node(ip=ip_addr, ...)` for a VM that has
**not been persisted yet**. With `node_id` now required on `Node`, that return becomes a
type error — there is no `node_id` to give it. The split resolves this honestly:
`allocate` and `_setup_vm` return `NewNode` (pre-persistence), and `allocate_task` is the
site that converts via `insert`:

```
allocate_task:
  new_node = await provisioner.allocate(provider)   # NewNode (was Node)
  node = await uow.nodes.insert(new_node)            # Node, node_id assigned here
```

This is an internal Protocol change, not a `Yascheduler` public-API change. Consumers
updated in-scope: `allocate_task` (the `nodes.add` → `nodes.insert` call site at line
381, and the `allocate` return assignment), `orchestrator` and `deallocate_nodes` (they
hold the `allocate` result; where they need the persisted identity they use `insert`'s
return), and the unit/e2e tests that mock `allocate` (return a `NewNode`). Mocks returning
a bare `Node` fail the type check and are updated mechanically.

`add_tmp` is deliberately **not** changed in this change: its `tmp_ip` marker is consumed
sensitively in `allocate_task:274+`, and reworking it is the highest-value follow-up (it
is the most fake-ip-as-handle spot) but out of scope here.

### Migration design

`migrations/002_add_node_id.sql`:
```sql
ALTER TABLE yascheduler_nodes
ADD COLUMN node_id SERIAL PRIMARY KEY;
```
One statement; PostgreSQL creates the sequence `yascheduler_nodes_node_id_seq`, backfills
existing rows (including the `prov*` temp rows) with sequential values in physical order,
and adds the PK constraint. The assigned ids are arbitrary but permanent; operators cannot
choose them. Valid for a populated table — no special handling needed.

Per the `db-migrations` edit procedure, two more edits accompany the file:
1. `schema.sql` DO block: `last_migration CONSTANT TEXT := '001'` → `'002'`
   (`schema.sql:8`).
2. `schema.sql` `CREATE TABLE IF NOT EXISTS yascheduler_nodes` snapshot: add
   `node_id SERIAL PRIMARY KEY` as the first column; `ip VARCHAR(15) UNIQUE` stays.

The three DB cohorts converge: **fresh** DB gets node_id via the snapshot and is seeded to
`'002'` (migration `002` skipped); **legacy** DB (has `yascheduler_nodes`, tracker empty)
gets the snapshot as a no-op (`CREATE TABLE IF NOT EXISTS` won't add the column — the
table already exists) and then migration `002` adds the column via `ALTER`; **modern** DB
(tracker at `'001'`) runs only migration `002`.

### `list_all` ordering

`node/list_all.sql` gains `ORDER BY node_id`. Today the order is unspecified (no
`ORDER BY`); `yanodes` preserves `list_all()` order by spec. Adding `ORDER BY node_id`
makes CLI output deterministic (insertion-order-ish) without changing any contract —
"preserve list_all() order" still holds, the order is just now defined. Low-risk; the
natural order now that a stable PK exists.

### `yanodes` rendering

`_NodeView` gains `node_id: NodeId`. `_fetch_nodes_view` sets it from `node.node_id`.
Table: new `NODE_ID` column placed **first** (before `IP`); the cell renders
`str(row.node_id)` (no display transformation — ids are not "default-hidden" like port 22
or MAX-for-0). JSON: new `"node_id": r.node_id.value` field added to each object. The
`cli-commands` spec's table-column list and JSON schema are updated to include `node_id`.

### `yasetnode` smart positional

A new positional argparse type wraps the existing grammar without touching it:

```python
@dataclass(frozen=True)
class NodeTarget:
    node_id: NodeId | None
    host_spec: HostSpec | None  # exactly one of the two is set

def _parse_node_target(s: str) -> NodeTarget:
    if s.isdigit():
        return NodeTarget(node_id=NodeId(int(s)), host_spec=None)
    return NodeTarget(node_id=None, host_spec=_parse_host_spec(s))
```

The positional's `type=` changes from `_parse_host_spec` to `_parse_node_target`.
`_parse_host_spec` and its grammar (`[user@]host[:port][~ncpus]`) are **untouched**, so
its specced scenarios remain valid verbatim — the `cli-commands` spec gains *new*
scenarios for the discriminator and `NodeTarget`, not edits to the existing grammar
scenarios.

The discriminator `s.isdigit()` is safe: IPv4 literals contain `.`, IPv6 must be
bracketed (`[...]`), and FQDNs contain `.`/letters — none are pure-digit. A bare integer
is unambiguously a node_id. Edge cases accepted as trade-offs: `"0"` → `NodeId(0)` →
rejected by `__post_init__` (ValueError surfaces as exit 1, or reject at parse time — see
tasks); `"-5"` → `isdigit()` is False → falls through to the host grammar, which rejects
it (no dots/brackets, malformed); leading zeros like `"007"` → `int("007") == 7` →
`NodeId(7)`, harmless.

Add-path rejection: a node cannot be added by id (adding requires a real host). After
`parse_args`, if `node_target.node_id is not None and not (args.remove_soft or
args.remove_hard)`, call
`parser.error("a node cannot be added by id; provide a host like user@host[:port][~ncpus]")`
(exit 2 — an argument-combination error, consistent with the existing
`--skip-setup × remove` `parser.error` at `manage_node.py:185`).

Remove-by-id flow: `uow.nodes.get_by_id(node_target.node_id)` → `Node | None`. If `None`,
the existing "Host NOT in DB" validation path applies (exit 1). If found, the remove
helpers use `node.ip` for `tasks.list_ids_by_ip_and_status(node.ip, TaskStatus.RUNNING)`
and `nodes.disable/remove(node.ip)` — the ip-keyed mutators are unchanged, ip is just now
obtained from the looked-up `Node` rather than the CLI positional. The validation UoW's
`already_there` check branches: `get_by_id(node_id)` when `node_id` is set, else `get(ip)`
(current behavior).

### `yastatus`, `MachineSession`, `ConnectedMachine`: explicit non-goals

`yastatus` does not display node_id (node_id is not consumed on the task-status path).
`MachineSession.node_id` and `ConnectedMachine.node_id` are not added (no consumer reads
them; including them is scope creep). Each is a plausible follow-up change once a consumer
appears.
