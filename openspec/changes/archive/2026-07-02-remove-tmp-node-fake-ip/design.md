## Context

`yascheduler_nodes` carries a legacy fake-IP placeholder for temp
cloud-provisioning nodes. `add_tmp(cloud)` runs `insert_tmp.sql` which inserts
`ip = 'prov' || SUBSTR(MD5(RANDOM()::TEXT), 0, 11)`, `enabled=FALSE`, and the
caller later resolves the row by that fake IP via `get(tmp_ip)` before
`remove(node.node_id)`. Two `"." in r["ip"]` python post-filters in
`PostgresNodeRepository.list_enabled` / `list_disabled` exist solely to
exclude these fake-IP rows from the real-node views. The `ip UNIQUE`
constraint was the original reason a fake placeholder was needed at all —
NULL wasn't an option because the codebase carried `ip` as a non-optional
`str` everywhere, and a unique placeholder was the workaround.

That was the state before `node_id`. Two prior changes rekeyed identity:
`add-node-id-identity` added `node_id SERIAL PRIMARY KEY` + `NodeId` /
`NewNode` / `Node`; `node-id-keyed-mutators` rekeyed the four mutators
(`enable`/`disable`/`remove`/`update`) to `node_id` and added the
`get(tmp_ip)` lookup in tmp-cleanup as a transitional step. This change
finishes the sequence: the fake IP has no remaining job, `node_id` carries the
identity, and the `UNIQUE` constraint is obsolete (duplicate IPs are valid
behind different jump hosts; `node_id` is the identity now).

**Stakeholders:** the daemon (`yascheduler`), cloud alloc critical section in
`allocate_task`, the migration runner (`yainit`'s `apply_migrations`), and
the test suite (unit + integration via testcontainers). No public API or CLI
surface is affected.

**Constraints:**

- DB schema changes require a migration file + `schema.sql` snapshot edit +
  `last_migration` CONSTANT bump (per `db-migrations` edit procedure).
- `NodeRepository` is an internal Protocol; removing a method is not a public
  break. The `Yascheduler` facade, Python client, INI config, and the six CLI
  commands are unchanged.
- Forward-only migrations; no down path.
- GRACE-lite: contracts, module map, change summary, and
  `docs/knowledge-graph.xml` must be updated in the same change.

## Goals / Non-Goals

**Goals:**

- Abolish `add_tmp` — converge on a single node-insertion path
  (`insert(NewNode) -> Node`), used by both the tmp-reservation and
  real-node-persistence flows.
- Replace the fake `prov...` IP sentinel with `''` (empty string), keeping
  `Node.ip: str` (no `Optional` ripple, no `None == None` footgun).
- Drop the `ip UNIQUE` constraint (obsolete; duplicate IPs valid behind
  different jump hosts; `node_id` is the identity).
- Remove the `"." in ip` python post-filters from `PostgresNodeRepository`
  — dead in `list_enabled` by the invariant, moved to SQL
  (`AND ip <> ''`) in `list_disabled`.
- Remove the `get(tmp_ip)` lookup from tmp-cleanup paths in `allocate_task` —
  the tmp `NodeId` is already in hand from `insert`'s return, so
  `remove(tmp_node_id)` is direct and idempotent.
- Single forward-only migration `003` that backfills `prov... → ''` and drops
  the `UNIQUE` constraint; no partial index, no `CHECK`.

**Non-Goals:**

- `VARCHAR(15)` widening for ipv6/DNS — separate migration (the column type
  is orthogonal to the sentinel/UNIQUE change and keeps this step minimal).
- `Task.allocated_ip → node_id` linkage — separate change (depends on the
  SSH layer being rekeyed to `node_id` first; the ip-keyed orchestrator queues
  feed this).
- SSH-layer `connect`/`disconnect`/`get_session`/`contains` rekey to
  `node_id` (Surface A — ip is the SSH transport address).
- `NodeRepository.get` / `get_by_ips` / `list_*` lookup methods rekey to
  `node_id` (Surface B-3 — deferred until the ip-keyed orchestrator queues
  that feed them are migrated).
- `CloudProvisioner.deallocate(cloud, ip)` rekey (ip is the cloud host
  address — out of scope to change here).
- Caller-side `"." in ip` filters in `deallocate_nodes.py` and elsewhere
  (they remain correct; out of scope).
- Format validation of the `ip` column (ipv4/ipv6/DNS) — the cloud provider
  owns format validity, not the DB.

## Decisions

### Decision 1: empty-string sentinel, not NULL

**Choice:** tmp-node `ip = ''` (empty string), `Node.ip: str` unchanged.

**Alternatives considered:**

- **`NULL` + `Node.ip: str | None`.** Rejected: forces `Optional` ripple
  across ~44 `node.ip` references in `application/` (deallocate_nodes,
  abandon_node, orchestrator all use `node.ip` for SSH/cloud operations and
  as dict keys); introduces `None == None` false-match footgun in comparisons
  like `t.allocated_ip == node.ip` against unallocated (`allocated_ip=None`)
  tasks; the only advantage (`NULL` is distinct under `UNIQUE`) is moot once
  `UNIQUE` is dropped.

- **Keep `prov...` fake IP, just rekey cleanup to `node_id`.** Rejected: keeps
  the fake-IP workaround alive, keeps the `"." in ip` filters alive, keeps
  `insert_tmp.sql` and a second insertion path — all of which exist only
  because there was no `node_id` before.

**Rationale:** `''` is a valid `str`, so `_row_to_node`'s `ip=row["ip"]` needs
no change, `Node.ip` stays `str`, and every existing `node.ip` consumer
compiles unchanged. The invariant (Decision 2) makes `''` semantically
unambiguous.

### Decision 2: the `ip == '' IFF enabled=FALSE AND tmp/pending` invariant

**Choice:** formalize the invariant `ip == ''` iff the node is a
tmp/pending cloud-provisioning row (which is always `enabled=FALSE`).

Consequences (these are the load-bearing implications, not separate
decisions):

- `list_enabled` (`WHERE enabled=TRUE`): by the invariant, no enabled row has
  `ip=''`, so the python `"." in ip` post-filter is dead code → **remove**.
- `list_disabled` (`WHERE enabled=FALSE`): disabled rows are a mix of
  tmp/pending (`ip=''`) and real-disabled-VM (`ip<>''`). The caller
  (`deallocate_nodes`) wants real-disabled-VMs only (they have a VM to
  delete); the presence test `ip <> ''` is the right semantic — **move to
  SQL** (`AND ip <> ''`), drop the python `"." in ip` post-filter.

**Alternatives considered:**

- **Format-based SQL filter (`ip ~ '^\d+\.\d+\.\d+\.\d+$'`).** Rejected: ties
  "real node" to ipv4 format; the `ip` column will hold ipv6 / DNS names
  later, and a format check would become a future migration blocker. Use a
  presence check (`ip <> ''`), not a format check.

- **Keep the python post-filters, just change the sentinel.** Rejected:
  perpetuates a python-side filter that belongs in SQL (the DB is the source
  of truth for `enabled` and `ip`), and obscures the invariant.

**Rationale:** the invariant is bidirectional and covers both filter sites
with one mental model. The presence check `ip <> ''` is format-agnostic and
survives a future ipv6/DNS migration without re-touching the filter.

### Decision 3: drop `ip UNIQUE`

**Choice:** `ALTER TABLE yascheduler_nodes DROP CONSTRAINT
yascheduler_nodes_ip_key` (PostgreSQL's default name for a column-level
`UNIQUE`).

**Alternatives considered:**

- **Keep `UNIQUE`, add a partial unique index `WHERE ip <> ''`.** Rejected:
  the partial index only made sense if `UNIQUE` stayed. Since `node_id` is
  the identity and duplicate IPs are valid (machines behind different jump
  hosts may share a private address), `UNIQUE` is obsolete. A partial index
  would be dead weight.

- **Keep `UNIQUE`, just change the sentinel to `''` (one empty string
  allowed).** Rejected: two parallel tmp allocations would collide on the
  single `''` row. The alloc critical section uses `allocation_lock` to
  serialize the capacity-read + select + insert block, so in practice tmp
  inserts don't race, but the `UNIQUE` constraint is the wrong mechanism to
  enforce this — the lock is. Drop `UNIQUE`; the lock already serializes.

**Rationale:** `UNIQUE` was a transition-window guard. Now that `node_id` is
the identity and the mutators key on it, `UNIQUE` on `ip` is dead constraint
that would only ever fire falsely (duplicate IPs behind jump hosts). Drop it.

### Decision 4: abolish `add_tmp`, single `insert` path

**Choice:** remove `NodeRepository.add_tmp` and `PostgresNodeRepository.add_tmp`;
  the tmp path calls `uow.nodes.insert(NewNode(cloud=selected_name,
  enabled=False))` (relying on the new `NewNode` defaults `ip=""`, `ncpus=0`).

**Alternatives considered:**

- **Keep `add_tmp`, return `Node` (RETURNING node_id + ip).** Rejected:
  perpetuates two insertion paths and a second SQL file (`insert_tmp.sql`),
  both of which exist only because there was no `node_id` before. The whole
  point is to converge.

- **Add `add_tmp(cloud) -> Node` as a thin wrapper around `insert`.**
  Rejected: a wrapper with no semantic value; the call site can construct
  `NewNode(cloud=..., enabled=False)` directly and the intent is clearer.

**Rationale:** `insert` already returns a `Node` carrying the generated
`node_id`; the tmp path needs exactly that. One insertion path, one SQL
file, one set of defaults.

### Decision 5: `_TmpSelection.ip: str → node_id: NodeId`, cleanup direct

**Choice:** `_TmpSelection(name: str, node_id: NodeId)`. The cleanup helpers
(`_cleanup_tmp_node_best_effort`, `_allocate_cloud_node`,
`_persist_node_with_cleanup`, `_provision_and_persist`) take
`tmp_node_id: NodeId` instead of `tmp_ip: str`. Both `get(tmp_ip)` lookups
and their `if node is not None` None-branches are removed; `remove(tmp_node_id)`
is called directly.

**Idempotency rationale:** `remove.sql` is `DELETE WHERE node_id = :node_id`.
If the row was already removed (e.g. a prior cleanup won the race, or the
persist path already removed it), the DELETE affects 0 rows — a no-op, no
error. This matches the prior no-op-on-0-rows behavior (which was implemented
via `if get returns None: skip remove`). The None-check was only there because
`remove` used to key on `ip` and the lookup-by-ip was the way to obtain the
`node_id`; now `node_id` is in hand, so the lookup is redundant.

**Alternatives considered:**

- **Keep `get(tmp_ip)` even with `node_id` in hand, "just in case".**
  Rejected: dead round-trip. The `node_id` came from `insert`'s `RETURNING
  node_id` in the same transaction a moment ago; the row exists. The only
  reason to `get` again would be TOCTOU paranoia, but the tmp row is
  just-inserted with a unique `node_id` under `allocation_lock`, and `remove`
  is idempotent anyway.

**Rationale:** two `get()` round-trips die, two None-branches die, the
control flow flattens. Net code reduction, not just a rekey.

### Decision 6: migration 003 is data + DROP CONSTRAINT only

**Choice:**

```sql
UPDATE yascheduler_nodes SET ip = '' WHERE ip LIKE 'prov%';
ALTER TABLE yascheduler_nodes DROP CONSTRAINT yascheduler_nodes_ip_key;
```

No partial index, no `CHECK` constraint, no `CREATE UNIQUE INDEX`.

**Alternatives considered:**

- **Add a `CHECK (ip IS NOT NULL AND ip <> '' ...)` or format CHECK.**
  Rejected: format validation is the cloud provider's job, not the DB's. A
  CHECK would block the future ipv6/DNS migration. The invariant is enforced
  by the application layer (only `insert(NewNode(cloud=..., enabled=False))`
  produces an `ip=''` row; real nodes always come from
  `clouds.allocate` with a real ip).

- **Split into two migrations (003 data, 004 DROP CONSTRAINT).** Rejected:
  the two operations are one logical change (drop the fake-IP mechanism);
  splitting adds a migration prefix for no benefit.

**Rationale:** minimal forward-only migration. The `schema.sql` snapshot edit
drops `UNIQUE` from the `ip` column line, so fresh databases match the
post-migration state.

## Risks / Trade-offs

- **[Risk] Existing rows with `prov...` IPs in production DBs.** → Mitigation:
  migration `003` backfills `prov... → ''` before dropping `UNIQUE`. The
  `WHERE ip LIKE 'prov%'` predicate is conservative (matches only the fake
  placeholder prefix). The `node-id-keyed-mutators` change already rekeyed
  mutators to `node_id`, so any in-flight tmp row keyed by its old fake IP is
  unrelated to the backfill (it's keyed by `node_id` now).

- **[Risk] A `prov...` IP that happens to be a real hostname.** → Mitigation:
  none of the four cloud providers (Azure, Hetzner, Upcloud, VastAI) produce
  IPs or DNS names starting with `prov` followed by a 10-char hex substring
  (the `insert_tmp.sql` format is `'prov' || SUBSTR(MD5(RANDOM()::TEXT), 0,
  11)`). The `LIKE 'prov%'` predicate is narrower than the actual format; a
  stricter match (`LIKE 'prov__________'` with exactly 10 underscores) could
  be used if paranoid, but the prefix is unique enough. Trade-off accepted.

- **[Risk] Two parallel tmp allocations colliding on `ip=''` after
  `UNIQUE` drops.** → Mitigation: the alloc critical section already
  serializes capacity-read + select + add_tmp under `allocation_lock`
  (`_select_and_insert_tmp`). The lock, not the `UNIQUE` constraint, is what
  prevents tmp-row races. Even if the lock were absent, two `ip=''` rows
  are distinct by `node_id`, which is the actual identity. No collision.

- **[Risk] `_row_to_node` reads `ip=''` and a downstream consumer treats it as
  a real ip.** → Mitigation: the invariant (Decision 2) says `ip=''` rows are
  always `enabled=FALSE`, and the only consumers that touch disabled rows
  (`list_disabled` → `deallocate_nodes`) now filter `ip <> ''` at the SQL
  layer; `deallocate_nodes`'s own `"." in node.ip` post-filter is a redundant
  second guard. No SSH/cloud operation is ever called against an `ip=''` row.

- **[Trade-off] `NewNode()` with no args is now a valid nonsense-node
  (`ip=""`, `ncpus=0`, `enabled=True`, `cloud=None`).** → Mitigation:
  `NewNode` is constructed in exactly two places (`CloudProvisioner.allocate`
  / `_setup_vm` returns a real node; `_select_and_insert_tmp` constructs the
  tmp-reservation node). Both pass explicit fields. The defaults are for
  ergonomics at the tmp call site, not a public API. Risk is nil in
  practice; trade-off accepted for clean call sites.

- **[Trade-off] `deallocate_nodes.py`'s own `"." in node.ip` filter stays.**
  → Mitigation: it's out of scope; it remains correct (now redundant for
  `ip=''` rows excluded by SQL, still filters non-ipv4 hostnames). A future
  change can clean it up when the `ip` column widens to ipv6/DNS (at which
  point all `"." in ip` checks across the codebase get revisited together).

## Migration Plan

1. **Add migration file** `infra/persistence/sql/migrations/003_drop_tmp_node_fake_ip.sql`
   with the `UPDATE ... SET ip='' WHERE ip LIKE 'prov%'` + `DROP CONSTRAINT`
   statements.
2. **Bump `last_migration`** CONSTANT in `schema.sql` from `'002'` to `'003'`.
3. **Edit `schema.sql` snapshot**: change `ip VARCHAR(15) UNIQUE` to
   `ip VARCHAR(15)` in the `yascheduler_nodes` `CREATE TABLE`.
4. **Apply code changes** in one atomic commit:
   - `domain/model.py`: `NewNode` defaults.
   - `domain/ports.py`: drop `add_tmp` from Protocol + docstring.
   - `infra/persistence/postgres.py`: drop `add_tmp` impl, drop two python
     post-filters.
   - `infra/persistence/sql/node/insert_tmp.sql`: **delete file**.
   - `infra/persistence/sql/node/list_disabled.sql`: add `AND ip <> ''`.
   - `application/allocate_task.py`: `_TmpSelection` field swap, 5 helper
     signatures, outer body `tmp_ip → tmp_node_id`.
   - Tests: update `StubNodeRepository` (drop `add_tmp`), tmp-cleanup test
     assertions, integration tmp-lifecycle test, new migration test.
   - GRACE-lite: knowledge-graph.xml, MODULE_CONTRACT/MODULE_MAP/
     CHANGE_SUMMARY, function contracts.
5. **Deploy**: `yainit` runs `apply_schema` (no-op on modern DBs except the
   snapshot `UNIQUE` drop is *not* applied to existing tables —
   `CREATE TABLE IF NOT EXISTS` is a no-op; the `UNIQUE` drop is applied by
   migration `003` via `apply_migrations`). Then `apply_migrations` runs
   `003`, backfilling any `prov...` rows and dropping the constraint.
6. **Rollback**: forward-only migrations; no down path. If `003` fails
   mid-application, the runner `ROLLBACK`s the migration transaction (the
   `UPDATE` and `DROP CONSTRAINT` are in one migration = one transaction);
   the DB is unchanged and `yainit` can be re-run after fixing the cause.

## Open Questions

(None — all design decisions are settled. The explore phase resolved the
sentinel choice, the UNIQUE drop, the migration contents, the cleanup
simplification, and all non-goals.)