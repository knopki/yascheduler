## Why

`add_tmp` inserts temp cloud-provisioning nodes with a fake `prov||MD5(...)`
placeholder IP (`insert_tmp.sql`), and the rest of the system works around
that fake IP with `"." in r["ip"]` post-filters in `list_enabled` /
`list_disabled` and a `get(tmp_ip)` lookup before every tmp-node `remove`.
Now that `node_id SERIAL PRIMARY KEY` exists (migration `002`, change
`add-node-id-identity`) and the mutators key on `node_id` (change
`node-id-keyed-mutators`), the fake IP has no purpose: a tmp node can carry
an empty-string sentinel and be cleaned up by `node_id` directly. This change
abolishes `add_tmp`, converges on a single `insert(NewNode)` path, replaces
the fake-IP sentinel with `''`, removes the `"." in ip` filters, drops the
  now-obsolete `ip UNIQUE` constraint, and deletes the `get(tmp_ip)` lookup
  from tmp-cleanup paths.

  The empty-string sentinel (`''`) is chosen over `NULL` because `Node.ip`
  stays `str` (no `Optional` ripple across ~44 sites in `application/`,
  no `None == None` false-match footgun in ip comparisons), and the only thing
  `NULL` would buy — Postgres multi-NULL under `UNIQUE` — is moot once
  `ip UNIQUE` is dropped (duplicate IPs are valid behind different jump hosts).

## What Changes

- **`NewNode` defaults** (`yascheduler/domain/model.py`): `ip: str = ""` and
  `ncpus: int = 0` become defaults (were required). Lets the tmp path
  construct `NewNode(cloud=name, enabled=False)` without naming ip/ncpus.
  `NewNode.ip` and `NewNode.ncpus` keep their types (`str`, `int`) — **no**
  `Optional` ripple. Field order is unchanged (ip and ncpus still first, now
  with defaults).

- **`NodeRepository` Protocol** (`yascheduler/domain/ports.py`):
  `add_tmp(cloud: str) -> str` is **REMOVED**. `insert(new_node: NewNode) ->
  Node` is now the sole node-insertion path and serves both the tmp-reservation
  and real-node paths. The Protocol docstring's "`add_tmp` ... unchanged ...
  reworking it is a deferred follow-up" sentence is replaced with the
  abolition rationale.

- **`PostgresNodeRepository`** (`yascheduler/infra/persistence/postgres.py`):
  `add_tmp` method **REMOVED**. `insert` already runs `insert.sql ... RETURNING
  node_id` and returns a full `Node`; the tmp path calls it with
  `NewNode(cloud=name, enabled=False)` (ip="", ncpus=0) and receives the
  `Node` carrying the new `node_id`.

- **`_row_to_node`**: unchanged. `ip=row["ip"]` reads `""` for tmp rows; `""`
  is a valid `str`, the mapping works without changes.

- **SQL queries** (`yascheduler/infra/persistence/sql/node/`):
  - `insert_tmp.sql` is **REMOVED** (no caller).
  - `list_enabled.sql`: **unchanged** (`WHERE enabled = TRUE`); the python
    post-filter `"." in r["ip"]` is **removed** from `PostgresNodeRepository`
    — dead code by the invariant (see below).
  - `list_disabled.sql`: gains `AND ip <> ''`. The python post-filter
    `"." in r["ip"]` is **removed** from `PostgresNodeRepository`. The
    presence check (`ip <> ''`) is semantically "this disabled node has a
    real address → it has a VM → eligible for cloud deallocation", not a
    format check.
  - All other node SQL files (`get_by_ip`, `get_by_id`, `get_by_ips`,
    `list_all`, `insert`, `enable`, `disable`, `remove`, `update`,
    `count_by_cloud`, `count_by_status`) are **unchanged**.

  **Invariant** (load-bearing for the two filter removals above): after this
  change, `ip == '' IFF enabled = FALSE AND node is tmp/pending`. Real-disabled
  VMs (deleted-but-not-removed rows) keep their real IP; real-enabled nodes
  always have a real IP. This makes `"." in ip` dead in `list_enabled` (only
  one direction needed: `enabled=TRUE ⇒ ip<>''`) and makes `ip <> ''` the
  correct real-node presence test in `list_disabled` (the converse: a
  disabled row with `ip<>''` is a real-disabled VM, not a tmp row).

  Callers of `list_disabled` outside `allocate_task` retain their own
  `"." in ip` filters (e.g. `deallocate_nodes.py`'s `node.ip not in busy_ips
  and "." in node.ip and node.cloud` post-filter); those caller-side filters
  are out of scope and stay as-is — they remain correct (redundant for
  `ip=''` rows now excluded by SQL, still filter non-ipv4 hostnames).

- **Migration `003_drop_tmp_node_fake_ip.sql`**
  (`infra/persistence/sql/migrations/`):
  ```sql
  UPDATE yascheduler_nodes SET ip = '' WHERE ip LIKE 'prov%';
  ALTER TABLE yascheduler_nodes DROP CONSTRAINT yascheduler_nodes_ip_key;
  ```
  Data backfill (`prov... → ''`) + drop the legacy column-level `UNIQUE`
  constraint (PostgreSQL default name `yascheduler_nodes_ip_key` for a
  column-level `UNIQUE`). No partial index, no `CHECK` constraint. Per
  `db-migrations` edit procedure, `last_migration` CONSTANT in `schema.sql`
  is bumped `'002' → '003'`, and the `yascheduler_nodes` snapshot DDL changes
  `ip VARCHAR(15) UNIQUE` → `ip VARCHAR(15)`.

- **`allocate_task` tmp-cleanup** (`yascheduler/application/allocate_task.py`):
  - `_TmpSelection` (NamedTuple): field `ip: str` is **replaced** with
    `node_id: NodeId`.
  - `_select_and_insert_tmp`: `add_tmp(selected_name) -> ip` is replaced
    with `uow.nodes.insert(NewNode(cloud=selected_name, enabled=False)) ->
    Node`; returns `_TmpSelection(name=selected_name, node_id=tmp_node.node_id)`.
  - `_cleanup_tmp_node_best_effort`, `_allocate_cloud_node`,
    `_persist_node_with_cleanup`, `_provision_and_persist`: the `tmp_ip: str`
    parameter becomes `tmp_node_id: NodeId`. The `uow.nodes.get(tmp_ip)` lookup
    and its `if node is not None` None-branch are **removed** in both cleanup
    sites; `uow.nodes.remove(tmp_node_id)` is called directly (idempotent:
    `DELETE WHERE node_id=?` affecting 0 rows is a no-op, matching the prior
    no-op-on-0-rows behavior — no rowcount check added).
  - `allocate_task` outer body: `tmp_ip: str | None` becomes
    `tmp_node_id: NodeId | None`; `selected.ip → selected.node_id`.

- **GRACE-lite**: `docs/knowledge-graph.xml` `M-DOMAIN-PORTS`,
  `M-PERSISTENCE`, `M-APPLICATION-ALLOCATE-TASK` annotations updated;
  MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY in `ports.py`, `model.py`
  (`NewNode`), `postgres.py`, `allocate_task.py`; function contracts on
  removed/changed methods/helpers.

- **Tests** (signatures changed; tests reflect the new contract):
  - `tests/unit/test_domain_ports.py`: `StubNodeRepository.add_tmp` removed;
    `insert` stub now also serves the tmp path.
  - `tests/unit/test_application_use_cases.py`: tmp-cleanup tests assert
    `uow.nodes.insert(NewNode(cloud=..., enabled=False))` for tmp insertion
    and `uow.nodes.remove(tmp_node_id)` for cleanup (no `get(tmp_ip)`
    expectation).
  - `tests/integration/test_db_integration.py`: tmp-node lifecycle test
    inserts via `insert(NewNode(cloud=..., enabled=False))`, asserts the row
    has `ip=""` and `enabled=False`, then `remove(node_id)` cleans up.
  - New migration test: applies `003` on a DB seeded with a `prov...` row and
    asserts the row's `ip` becomes `''` and the `UNIQUE` constraint is gone
    (a duplicate `ip` insert succeeds).

No **BREAKING** changes to public APIs. The `Yascheduler` facade / Python
client API / INI config / CLI command surfaces are unchanged. The
`NodeRepository` Protocol is internal; removing `add_tmp` affects only
`allocate_task` (in-repo) and tests. The DB schema loses a constraint
(UNIQUE on `ip`); the migration runs in `yainit`'s `apply_migrations` step.

## Capabilities

### New Capabilities

(None — this change modifies existing capabilities; no new spec file is
created.)

### Modified Capabilities

- `domain-entities`: `NewNode` REQUIREMENT changes — `ip` and `ncpus` gain
  defaults (`""` and `0`); field types unchanged. The "no Optional ripple"
  invariant is stated.
- `domain-ports`: `NodeRepository` REQUIREMENT changes — `add_tmp` is removed;
  `insert` is now the sole node-insertion path and serves the tmp-reservation
  path via `NewNode(cloud=..., enabled=False)`. The "tmp path uses insert"
  contract is stated.
- `postgres-persistence`: `PostgresNodeRepository` REQUIREMENT changes —
  `add_tmp` is removed; `list_enabled` drops the python `"." in ip` post-filter
  (dead by the `enabled=TRUE ⇒ ip<>''` invariant); `list_disabled` moves the
  real-node filter to SQL (`AND ip <> ''`) and drops the python post-filter.
  The SQL-file-layout requirement drops `node/insert_tmp.sql`.
- `db-migrations`: instance of the documented edit procedure (migration `003`,
  CONSTANT bump, snapshot DDL edit — drop `UNIQUE` from `ip`); no contract
  change.
- `postgres-schema-apply`: the `schema.sql` snapshot content changes (the
  `yascheduler_nodes` `CREATE TABLE` drops `UNIQUE` from the `ip` column). The
  `apply_schema` *contract/behavior* is unchanged; only the snapshot text it
  loads is updated. Listed for blast-radius visibility.
- `use-cases`: `AllocateTask` REQUIREMENT changes — the tmp-cleanup path
  resolves the tmp `NodeId` directly from `insert`'s return (no `get(tmp_ip)`
  lookup), calls `remove(tmp_node_id)` idempotently (no None-branch), and
  `_TmpSelection` carries `node_id` instead of `ip`.

## Impact

- **Code**: `yascheduler/domain/model.py` (`NewNode` defaults),
  `yascheduler/domain/ports.py` (Protocol: drop `add_tmp`),
  `yascheduler/infra/persistence/postgres.py` (drop `add_tmp`, drop two
  python post-filters), `yascheduler/application/allocate_task.py`
  (`_TmpSelection` + 5 helper signatures + outer body),
  `yascheduler/infra/persistence/sql/node/insert_tmp.sql` (REMOVED),
  `yascheduler/infra/persistence/sql/node/list_disabled.sql` (`AND ip <> ''`),
  `yascheduler/infra/persistence/sql/migrations/003_drop_tmp_node_fake_ip.sql`
  (NEW), `yascheduler/infra/persistence/sql/schema.sql` (CONSTANT bump + drop
  `UNIQUE`), `tests/unit/test_domain_ports.py`, `tests/unit/test_application_use_cases.py`,
  `tests/integration/test_db_integration.py`.
- **DB migration**: `003_drop_tmp_node_fake_ip.sql` — backfills `prov... → ''`
  and drops `yascheduler_nodes_ip_key`. Runs forward-only via `apply_migrations`.
- **No public-API break**: `Yascheduler` facade / Python client / INI config /
  CLI commands surface unchanged. `NodeRepository` is internal.
- **No new dependencies**.
- **Out of scope (explicit non-goals)**: `VARCHAR(15) → wider` for ipv6/DNS
  (separate migration); `Task.allocated_ip → node_id` linkage (separate
  change, deferred until SSH layer is rekeyed); SSH-layer
  `connect`/`disconnect`/`get_session`/`contains` rekey to `node_id` (Surface
  A); `NodeRepository.get` / `get_by_ips` / `list_*` lookup methods rekey to
  `node_id` (Surface B-3); `CloudProvisioner.deallocate(cloud, ip)` rekey (ip =
  cloud host, out of scope).