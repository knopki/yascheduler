# Design: task-schema-and-entity-cleanup

## Context

`yascheduler_tasks` and the `Task` domain entity have drifted. The
`allocated_ip` column was the original allocation signal but has been
superseded by `allocated_node_id` (a foreign key to `yascheduler_nodes`),
which is now the canonical allocation signal used by all read paths
(`show_nodes`, `abandon_node`, `check_status` node joins, domain events).
`allocated_ip` survives only as (a) a guard field in `Task.allocate_to`/
`Task.mark_running` and (b) a display field in the `yastatus --json` and
`Yascheduler` facade outputs. The `label` column is a PostgreSQL keyword
(legal but awkward). The `status` column is `SMALLINT` with no DB-level
constraint guaranteeing membership in `{0,1,2}`. There are no audit
timestamps. These four issues are bundled into one change because they all
touch the same table and entity, and migrating them together avoids four
separate schema snapshots.

Constraints:
- Public API stability is a project rule (AGENTS.md), so the two breaking
  wire-format changes (`yastatus --json`, `Yascheduler` facade dict) are
  accepted explicitly here and must be called out in the proposal.
- The webhook payload (`{task_id, status, custom_params}`) does not carry
  `allocated_ip`, so it is unaffected.
- The AiiDA scheduler plugin parses `yastatus` default mode
  (`task_id   STATUS`) and does not read the JSON output; confirm during
  implementation.
- `TaskStatus` is a Python `IntEnum`; the external API exposes `.value`
  (int 0/1/2) via the facade dict and `.name` (string) via `yastatus --json`.
  The DB-level enum must not perturb these external shapes.
- pg8000.native returns rows positionally; `PostgresTaskRepository._run`
  zips them into dicts via `self._conn.columns`. After the enum change,
  `row["status"]` is a Python `str` (the enum label), not an int.

Stakeholders: daemon, CLI users, AiiDA plugin, external `Yascheduler`
client consumers.

## Goals / Non-Goals

**Goals**
- `yascheduler_tasks` has `created_at`/`updated_at`, with `updated_at`
  auto-set by a trigger on every update.
- `allocated_ip` is gone from the table, the entity, and all code paths;
  `allocated_node_id` is the sole allocation signal.
- The `label` column is renamed to `title` (no PG keyword).
- `status` is a PostgreSQL enum; the DB enforces valid values.
- External wire formats are updated to the nested-`node` shape, with
  `created_at`/`updated_at` added to `yastatus --json`.
- Four ordered migrations bring a legacy DB to the new shape; `schema.sql`
  reflects the final snapshot.

**Non-Goals**
- No change to the webhook payload wire format.
- No change to the `TaskStatus` Python type (stays `IntEnum`).
- No change to the numeric value of `TaskStatus` in the facade dict
  (`t.status` IntEnum, `.value` = 0/1/2).
- No change to the `yastatus --json` `"status"` field (still `task.status.name`).
- No change to domain field names (`Task.label` stays `label`).
- No index on `allocated_node_id` is added in this change (separate concern;
  the FK already exists per the task-allocated-node-id change).
- No change to the `query_tasks` use case call signature (only its return
  type widens to a tuple).

## Decisions

### D1: `updated_at` auto-update via trigger function

PostgreSQL has no `ON UPDATE` clause for column defaults (that is MySQL/
MariaDB syntax). The standard PostgreSQL mechanism is a `BEFORE UPDATE`
trigger that sets `NEW.updated_at = NOW()`.

- Create `FUNCTION yascheduler_touch_updated_at() RETURNS trigger` that sets
  `NEW.updated_at = NOW()` and returns `NEW`.
- Create `TRIGGER yascheduler_tasks_touch_updated_at BEFORE UPDATE ON
  yascheduler_tasks FOR EACH ROW EXECUTE FUNCTION yascheduler_touch_updated_at()`.
- `updated_at` also has `DEFAULT NOW()` so inserts populate it without the
  trigger (the trigger only fires on UPDATE).

**Alternatives considered:** application-layer `updated_at` set in
`PostgresTaskRepository.save` — rejected because the user explicitly
requested DB-side auto-update, and a trigger is the only PG-native way;
application-layer code would also miss direct SQL updates from migrations
or ad-hoc admin queries.

### D2: `created_at`/`updated_at` are on the domain `Task` and in `yastatus --json`

The fields are DB-generated (absent from `NewTask`). `_row_to_task` reads
them; `insert.sql`/`get_by_id.sql`/`list_by_status.sql`/`list_by_jobs.sql`
include them in `RETURNING`/`SELECT`. `update_by_id.sql` does NOT return
them (the current `save` does not refresh the in-memory `Task`; `updated_at`
is observable via a subsequent read). `yastatus --json` emits them as
ISO-8601 strings via `row["created_at"].isoformat()` (pg8000 returns
`datetime`).

**Alternatives considered:** keep them as DB-only audit fields not surfaced
in the entity or JSON — rejected; the user explicitly asked for them in
`Task` and in `yastatus --json`.

### D3: Drop `allocated_ip`; guards switch to `allocated_node_id`

`Task.allocate_to` guard: `if self.allocated_ip is not None` →
`if self.allocated_node_id is not None` (raise `TaskAlreadyAllocatedError`).
`Task.mark_running` guard: `if self.allocated_ip is None` →
`if self.allocated_node_id is None` (raise `TaskNotAllocatedError`).
`allocated_node_id` is the canonical "is allocated" signal and is already
used by every other read path. `Task.allocate_to` returns
`replace(self, allocated_node_id=node.node_id, ...)` (already the case;
`allocated_ip` is dropped from the `replace` call).

### D4: `yastatus --json` and `Yascheduler` facade use a nested `node` object

`yastatus --json` new object shape:
```
{
  "task_id": int,
  "status": str,                  # task.status.name — unchanged
  "label": str,                   # task.label — unchanged
  "engine": str,
  "local_folder": str | null,
  "remote_folder": str | null,
  "created_at": str,              # ISO-8601 — new
  "updated_at": str,              # ISO-8601 — new
  "node": {                       # null when allocated_node_id is None
    "ip": str,
    "port": int,
    "username": str,
    "cloud": str | null
  } | null
}
```

`Yascheduler.queue_get_tasks*` dict shape:
```
{
  "task_id": int,                 # unchanged
  "label": str,                   # unchanged
  "status": TaskStatus,           # IntEnum — unchanged
  "metadata": dict,               # unchanged
  "node": {                       # null when allocated_node_id is None
    "ip": str,
    "port": int,
    "username": str,
    "cloud": str | null
  } | null
}
```

`node` is built from `nodes_by_id.get(task.allocated_node_id)`. For
`yastatus --json`, `nodes_by_id` is already built in
`_check_status_async` via `uow.nodes.get_by_ids(...)`. For the facade,
the use case `query_tasks` now returns `(tasks, nodes_by_id)` (see D6).

### D5: `label` column → `title`; domain name stays `label`

DB column rename: `yascheduler_tasks.label` → `yascheduler_tasks.title`.
SQL files rename `label` → `title` in column lists and `:label` → `:title`
in params. The persistence layer renames the pg8000 named param:
`label=task.label` → `title=task.label` (param name changes, value
unchanged) and `row["label"]` → `row["title"]` in `_row_to_task`. The
domain field `Task.label` and the JSON/dict key `"label"` are unchanged.

`title` was chosen over `name` because `name` is too generic and risks
alias confusion in future joins; `title` is a non-reserved PostgreSQL
keyword and reads as a column name without quoting.

### D6: `status` SMALLINT → PG enum; `TaskStatus` stays IntEnum (write `.name`, read by name)

- `CREATE TYPE task_status AS ENUM ('TO_DO', 'RUNNING', 'DONE');`
- Migration 008: `ALTER TABLE yascheduler_tasks ALTER COLUMN status TYPE
  task_status USING CASE status WHEN 0 THEN 'TO_DO' WHEN 1 THEN 'RUNNING'
  WHEN 2 THEN 'DONE' END;`
- Write path: `status=task.status.value` (int) → `status=task.status.name`
  (string) in `save`, `insert`, `update_status`,
  `list_ids_by_node_id_and_status`.
- Read path: `TaskStatus(row["status"])` (int cast, current) →
  `TaskStatus[row["status"]]` (name lookup) in `_row_to_task` and
  `count_by_status`.
- `list_by_status` SQL: `cast(:statuses AS int[])` →
  `cast(:statuses AS task_status[])`. Verified by a pg8000 testcontainers
  spike that `cast(:list AS task_status[])` works with a Python `list[str]`
  of enum labels. (`cast(:statuses AS text[])` alone FAILS with
  `operator does not exist: task_status = text`; `::task_status[]` suffix is
  a redundant fallback.)
- pg8000 returns the enum column as a Python `str` (verified by spike:
  `row["status"]` is `'TO_DO'`/`'RUNNING'`/`'DONE'`, type `str`). This is why
  `count_by_status` MUST switch from `TaskStatus(row["status"])` (int cast,
  which would raise on a string) to `TaskStatus[row["status"]]` (name
  lookup).

**External API impact: none.** `yastatus --json` still emits
`task.status.name` (string, unchanged). `client._task_to_dict` still emits
`t.status` (IntEnum, `.value` = 0/1/2, unchanged). Webhook still emits
`status.value` (int, unchanged).

**Alternatives considered:**
- Make `TaskStatus` a `StrEnum`/`str`-valued enum — rejected; breaks the
  facade dict (`t.status` would no longer be an IntEnum with `.value` = int)
  and the webhook payload (`status.value` would be a string).
- Store `status` as `VARCHAR` with a `CHECK` constraint — rejected; a PG
  enum is more efficient and self-documenting, and the migration cost is
  the same.

### D7: `list_ids_by_ip_and_status` → `list_ids_by_node_id_and_status`

Both call sites (`manage_node._remove_node_hard:236`,
`_remove_node_soft:261`) already hold a fully-resolved `Node` with
`node.node_id`; they pass `node.ip` only to find tasks on that specific
node. With `allocated_ip` gone, the natural filter is
`allocated_node_id = node.node_id`, which they already have.

- SQL file: `get_ids_by_ip_and_status.sql` →
  `get_ids_by_node_id_and_status.sql`; predicate
  `WHERE ip = :ip AND status = :status` →
  `WHERE allocated_node_id = :node_id AND status = :status`.
- Repository method: `list_ids_by_ip_and_status(ip: str, status)` →
  `list_ids_by_node_id_and_status(node_id: NodeId, status)`; param
  `:ip` → `:node_id` (binds `node_id.value`).
- Call sites: `node.ip` → `node.node_id`.

The `docs/BUGS.md` note about "no index on ip" becomes moot (the
`allocated_node_id` FK is the natural index target; adding an index is a
separate concern, not in this change).

### D8: `query_tasks` return type widens to `(list[Task], dict[NodeId, Node])`

The use case `query_tasks` is the sole production caller of the
UoW-opening path on the client query route (verified: `client.py:191` is
the only production caller; `check_status.py:124` `_query_tasks` is a
different, same-named private helper that takes an already-open `uow` and
never calls the use case). The facade does not open its own UoW — it
delegates to `query_tasks`, which owns the UoW.

- Inside the existing single UoW, after fetching tasks, batch-load nodes:
  `node_ids = {t.allocated_node_id for t in tasks if t.allocated_node_id}`;
  `nodes = await uow.nodes.get_by_ids(list(node_ids)) if node_ids else {}`.
- Return `(tasks, nodes)`.
- The facade unpacks the tuple and passes `nodes_by_id` to `_task_to_dict`,
  which projects the nested `node` object.

`NodeRepository.get_by_ids` already exists (used by `check_status`). No
new repository method is needed.

**Alternatives considered:**
- A second use case `query_tasks_with_nodes` — rejected; only one caller
  exists, so a second use case is dead weight.
- The facade opens its own UoW for nodes — rejected; violates the
  use-case boundary discipline (the facade delegates to use cases, it does
  not own UoWs), and the user did not choose this.

### D9: Migration ordering — additive/rename first, transform, then destructive drop

```
006_rename_label_to_title.sql       ALTER TABLE ... RENAME COLUMN label TO title
007_add_created_updated_at.sql      ADD COLUMN created_at/updated_at + trigger fn + trigger
008_status_to_enum.sql              CREATE TYPE + ALTER COLUMN ... USING CASE
009_drop_allocated_ip.sql           ALTER TABLE ... DROP COLUMN ip
```

`schema.sql` is updated to the final snapshot (all four applied);
`last_migration` constant becomes `'009'`. Fresh DBs get the final shape
directly from `schema.sql`; legacy DBs run 006–009 in order. Each
migration is its own transaction (per the db-migrations spec).

Rationale: do the additive and rename first (safe, reversible), then the
enum conversion (data transform), then the destructive column drop last.
This ordering means a rollback of the API-breaking column drop can re-add
the column without losing the enum/title/timestamp work.

## Risks / Trade-offs

- **[Breaking `yastatus --json` and `Yascheduler` facade wire format] →**
  Accepted. The proposal calls the breaks out explicitly. External
  consumers of these formats must update. Mitigation: the AiiDA plugin
  does not read these fields (confirm during implementation); the webhook
  payload is unaffected. The change is called out in the changelog and
  the spec deltas.
- **[pg8000 enum read returns `str`, not int] →** Verified by spike. The
  two read sites that currently do `TaskStatus(row["status"])` (int cast)
  are `_row_to_task` and `count_by_status`; both switch to
  `TaskStatus[row["status"]]` (name lookup). Missing one would raise
  `ValueError` at runtime — caught by the unit/integration tests for
  `count_by_status` and `_row_to_task`.
- **[Migration 008 `USING CASE` is a data transform] →** The CASE maps
  0/1/2 to the enum labels. Any out-of-range integer (e.g. 3) would map to
  NULL and violate the `NOT NULL` constraint, failing the migration. This
  is desirable (a corrupt row surfaces early). Mitigation: the migration
  is run in a transaction; on failure it rolls back and the DB is
  unchanged.
- **[Trigger function is a persistent DB object] →** The trigger function
  `yascheduler_touch_updated_at()` lives in the DB after migration 007. It
  is idempotent (re-running the CREATE FUNCTION updates the definition).
  It is dropped only by an explicit `DROP FUNCTION` (not in this change).
- **[Four migrations in one change] →** More surface area, but all touch
  the same table and are interdependent in the final snapshot. Splitting
  into four changes would mean four intermediate `schema.sql` snapshots
  and four `last_migration` bumps — more churn, no benefit.

## Migration Plan

1. Deploy code that is compatible with both the old and new shapes is NOT
   possible for the wire-format breaks (`yastatus --json`, facade dict) —
   these are hard breaks. Deploy the code and the migrations together.
2. Run migrations 006 → 007 → 008 → 009 in order. Each is a separate
   transaction.
3. Restart the daemon and CLI consumers; they read the new schema.
4. **Rollback:** reverse the migrations in reverse order (009 → 008 → 007
   → 006). 009 re-adds `ip` (backfill from `allocated_node_id` join to
   `yascheduler_nodes.ip`); 008 reverts status to `SMALLINT` (cast enum
   label back to int via `CASE status WHEN 'TO_DO' THEN 0 ...`); 007 drops
   the trigger/trigger-function/columns; 006 renames `title` back to
   `label`. Rollback of 009 loses `ip` values for tasks allocated after the
   forward migration (acceptable — the column is being dropped). The
   rollback SQL is out of scope for this change's spec files (the
   db-migrations spec does not require reversible migrations), but the
   forward migrations are written to be reversible if needed.

## Open Questions

- **e2e tests:** `tests/e2e/test_hetzner_live.py` and `test_full_cycle.py`
  assert on `task.allocated_ip`. These must be rewritten to assert on
  `task.allocated_node_id` + a node lookup, or on the new `node.ip` JSON
  field. To be enumerated in tasks.md.
- **AiiDA plugin grep:** confirm no AiiDA code reads `yastatus --json` or
  `queue_get_tasks()["ip"]`. A quick grep during implementation suffices.
- **`show_nodes` / `yanodes` stale text:** the `CHANGE_SUMMARY` comments in
  `show_nodes.py` still mention the old `allocated_ip`-keyed join. Clean up
  the stale text during implementation (no behavior change).
- **`orchestrator.py:454` `ip = task.allocated_ip or ""`** feeds a log line.
  Switch to `node.ip` via the resolved node (the orchestrator resolves the
  node already), or drop `ip` from the log line. To be decided during
  implementation (trivial).
- **`abandon_node.py` CHANGE_SUMMARY** mentions `t.allocated_ip == node.ip`
  historically; the code is already rekeyed to `allocated_node_id`. Verify
  no lingering `allocated_ip` reads during implementation.