# Explore Brief — remove-tmp-node-fake-ip

## Rejected alternatives

- **NULL sentinel for tmp-node ip.** Loses `Node.ip: str` type purity — 44 sites
  in `application/` would need `str | None` + mypy guards/casts; `None == None`
  false-matches in ip comparisons (e.g. `allocated_ip == node.ip` against
  unallocated tasks). The only thing NULL bought was Postgres multi-NULL under
  UNIQUE; but UNIQUE is being dropped anyway (node_id is the key, duplicate ip
  valid behind different jump hosts), so NULL's single advantage evaporates.
- **Keep `add_tmp` separate, return `Node`** (RETURNING node_id + ip). Rekey
  cleanup by node_id but leave two insertion paths. Rejected: the whole point
  is to converge on one insertion path (`insert(NewNode)`); keeping `add_tmp`
  perpetuates the divergence. Abolish.
- **Format-based SQL filter (`ip ~ '^\d+\.\d+\.\d+\.\d+$'`).** Rejected: ip
  column will hold ipv6 / DNS names later; tying "real node" to ipv4 format is
  a future migration blocker. Use presence check (`ip <> ''`), not format
  check.
- **Partial unique index on `ip` if "" sentinel.** Only needed if UNIQUE
  stayed. UNIQUE is being dropped (node_id is the identity; duplicate ip valid
  behind different jump hosts), so no partial index. Migrations stays
  data-only + DROP CONSTRAINT.
- **VARCHAR(15) widening in this change.** Explicit non-goal. The column
  widening for ipv6/DNS is a separate migration. Keep this change minimal.

## Final approach: "" sentinel + abolish add_tmp + node_id cleanup

### Sentinel & invariant

- `yascheduler_nodes.ip` keeps type `VARCHAR(15)` (no widening here).
- Tmp/pending nodes carry `ip = ''` (empty string sentinel).
- Invariant: `ip == '' IFF enabled = FALSE AND node is tmp/pending`
  (real-disabled VMs keep their real ip; real-enabled always have real ip).
- No DB UNIQUE on ip (DROP constraint in migration); node_id is the identity.
  Duplicate ip allowed (machines behind different jump hosts).
- No CHECK constraint: format/format-validation is the app/cloud layer's job,
  not the DB's. Migration is data + DROP only.

### Mapping tables

#### NodeRepository surface (after change)

| Method        | Before                         | After                          |
| ------------- | ------------------------------ | ------------------------------ |
| `add_tmp`     | `(cloud) -> str` (fake ip)      | **REMOVED**                     |
| `insert`      | `(new_node: NewNode) -> Node`   | unchanged (now also the tmp path) |
| `get`         | `(ip: str) -> Node | None`      | unchanged (ip-keyed; out of scope to rekey) |
| `get_by_id`   | `(node_id: NodeId) -> Node|None`| unchanged                      |
| `list_enabled`| `()` post-filter `"." in ip`   | `()` no python filter (SQL `enabled=TRUE` suffices by invariant) |
| `list_disabled`| `()` post-filter `"." in ip`  | `()` SQL adds `AND ip <> ''`   |
| `enable/disable/remove` | node_id-keyed (already)   | unchanged                      |
| `update`      | node_id-keyed (already)        | unchanged                      |

#### NewNode defaults

| Field    | Before default | After default | Reason                       |
| -------- | -------------- | ------------- | ---------------------------- |
| `ip`     | (required)     | `""`          | tmp path constructs without ip |
| `ncpus`  | (required)     | `0`           | tmp path: no CPU info yet     |
| others   | unchanged      | unchanged     |                              |

#### _TmpSelection shape

| Field    | Before | After          |
| -------- | ------ | -------------- |
| `name`   | `str`  | `str`          |
| `ip`     | `str`  | **REMOVED**    |
| `node_id`| —      | `NodeId` (added) |

#### Migration 003 contents

```sql
UPDATE yascheduler_nodes SET ip = '' WHERE ip LIKE 'prov%';
ALTER TABLE yascheduler_nodes DROP CONSTRAINT yascheduler_nodes_ip_key;
```
No partial index, no CHECK. `schema.sql`: `last_migration := '003'`;
`ip VARCHAR(15) UNIQUE` → `ip VARCHAR(15)` (UNIQUE dropped from snapshot).

### Cross-module data flows

#### Cloud alloc critical section (after)

```
_select_and_insert_tmp (under allocation_lock):
  list_all → _count_nodes_by_cloud → select_provider
  tmp_node = uow.nodes.insert(NewNode(cloud=selected_name, enabled=False))  # ip="" ncpus=0 defaults
  commit → lock released
  return _TmpSelection(name=selected_name, node_id=tmp_node.node_id)

_provision_and_persist:
  node = await _allocate_cloud_node(...)        # clouds.allocate(name) -> NewNode (real ip)
  _persist_node_with_cleanup(node, ..., tmp_node_id):
    uow.nodes.insert(node)                      # real node, real ip
    uow.nodes.remove(tmp_node_id)               # idempotent: 0 rows ok if already gone
    commit
```

#### Cleanup paths (after)

```
_cleanup_tmp_node_best_effort(uow_factory, tmp_node_id, ...):
  uow.nodes.remove(tmp_node_id)                  # no get() lookup, no None-check
  commit                                          # idempotent DELETE

_allocate_cloud_node failure:
  ... clouds.allocate raised ...
  _cleanup_tmp_node_best_effort(..., tmp_node_id, "cloud-alloc-failed")
  raise
```

### Key call-site changes (allocate_task.py)

- `_TmpSelection`: drop `ip: str`, add `node_id: NodeId`.
- `_select_and_insert_tmp`: `add_tmp(name) -> ip` → `insert(NewNode(cloud=name, enabled=False)) -> Node`; return `.node_id`.
- `_cleanup_tmp_node_best_effort`: signature `tmp_ip: str → tmp_node_id: NodeId`; body drops `get(tmp_ip)`, calls `remove(tmp_node_id)` directly.
- `_persist_node_with_cleanup`: signature `tmp_ip: str → tmp_node_id: NodeId`; body drops `get(tmp_ip)` + None-branch, calls `remove(tmp_node_id)` directly.
- `_allocate_cloud_node`: signature `tmp_ip: str → tmp_node_id: NodeId`; passes through to cleanup.
- `_provision_and_persist`: signature `tmp_ip: str → tmp_node_id: NodeId`; passes through.
- `allocate_task` outer body: `tmp_ip: str | None → tmp_node_id: NodeId | None`; `selected.ip → selected.node_id`.

### Spec capabilities touched (deltas)

- `domain-entities`: `NewNode.ip` default `""`, `NewNode.ncpus` default `0`.
- `domain-ports`: `NodeRepository.add_tmp` REMOVED; Protocol docstring updated.
- `postgres-persistence`: `PostgresNodeRepository.add_tmp` REMOVED; `list_enabled` drops python `"." in ip` filter (dead by invariant); `list_disabled` filter moves to SQL (`AND ip <> ''`); `_row_to_node` unchanged (ip still `str`, `""` is a valid str).
- `db-migrations`: instance of the edit procedure (migration 003, CONSTANT bump, snapshot DDL update — drop UNIQUE from ip).
- `postgres-schema-apply`: snapshot content changes (`ip VARCHAR(15) UNIQUE` → `ip VARCHAR(15)`); contract/behavior unchanged.
- `use-cases`: `AllocateTask` tmp-cleanup requirement changes — cleanup by `tmp_node_id: NodeId` directly, no `get(tmp_ip)` lookup, no None-branch.

### Open questions

None outstanding. All resolved in explore:
- sentinel "" vs NULL → ""
- DROP UNIQUE → yes
- migration data + DROP only, no partial index / CHECK → yes
- abolish add_tmp → yes
- VARCHAR(15) widening → non-goal
- `t.allocated_ip → node_id` linkage → non-goal (separate change)
- NewNode defaults `ip=""`, `ncpus=0` → yes
- `"." in ip` filter → remove entirely (dead in list_enabled, move to SQL `ip <> ''` in list_disabled)