# Explore Brief — task-schema-and-entity-cleanup

One change proposal bundling four related `yascheduler_tasks` / `Task` cleanups.
All four touch the same table and entity, and migrate together. Decisions
below are the design commitments; the proposal/design/specs/tasks must cover
every item.

## A. `created_at` / `updated_at` on `yascheduler_tasks`

- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `updated_at` auto-updated by a PG trigger (no MySQL-style `ON UPDATE` in PG):
  - `CREATE FUNCTION yascheduler_touch_updated_at() RETURNS trigger AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;`
  - `CREATE TRIGGER yascheduler_tasks_touch_updated_at BEFORE UPDATE ON yascheduler_tasks FOR EACH ROW EXECUTE FUNCTION yascheduler_touch_updated_at();`
- Both fields ARE added to the domain `Task` (user's explicit decision). They
  are DB-generated; `NewTask` does NOT carry them (only `Task`, post-persistence).
- `_row_to_task` reads `created_at`/`updated_at` from the row.
- Surface to `yastatus --json`: yes — add `created_at` and `updated_at` to the
  JSON object (see B for the new shape). ISO-8601 strings via
  `row["created_at"].isoformat()` (pg8000 returns `datetime`).

## B. Drop `allocated_ip` from `Task` + `NewTask` + `yascheduler_tasks`

Confirmed: this is an accepted breaking change to `yastatus --json` and
`Yascheduler` client facade. `allocated_ip` is **not** in the webhook payload
(`WebhookPayload = {task_id, status, custom_params}`) — webhook wire format is
untouched.

### Domain changes

- `Task`: drop `allocated_ip`; add `created_at: datetime`, `updated_at: datetime`.
- `NewTask`: drop `allocated_ip` (never meaningful pre-persistence).
- `Task.allocate_to` guard: `if self.allocated_ip is not None` →
  `if self.allocated_node_id is not None` (the canonical "is allocated" signal).
- `Task.mark_running` guard: `if self.allocated_ip is None` →
  `if self.allocated_node_id is None`.

### Persistence changes

- `_row_to_task`: drop `allocated_ip=row.get("ip")`; add `created_at`/`updated_at`
  reads. Read `status` as a **string** (see D) → `TaskStatus[row["status"]]`
  (name lookup, not int cast).
- `save`: drop `ip=task.allocated_ip`; write `status=task.status.name` (string,
  per D). Read `created_at`/`updated_at` from `RETURNING` if we want to refresh
  the in-memory Task (decision: do NOT refresh — `save` returns `None` today and
  callers don't use a refreshed Task; `updated_at` is observable via re-fetch).
- `insert`: drop `ip=new_task.allocated_ip`; write `status=new_task.status.name`.
- SQL files: drop `ip` column from `insert.sql`, `update_by_id.sql`,
  `get_by_id.sql`, `list_by_status.sql`, `list_by_jobs.sql`. Add
  `created_at`, `updated_at` to `RETURNING`/`SELECT` lists of `insert.sql`,
  `get_by_id.sql`, `list_by_status.sql`, `list_by_jobs.sql` (NOT `update_by_id.sql`
  — `save` does not refresh). `count_by_status.sql`, `get_ids_by_ip_and_status.sql`
  (rename? see below), `update_status.sql`, `update_meta.sql` — unaffected
  (they don't select/return these columns).

### `get_ids_by_ip_and_status.sql` → `get_ids_by_node_id_and_status.sql`

Resolved (verified by reading callers): both callers
(`entrypoints/cli/manage_node.py:_remove_node_hard:236` and
`_remove_node_soft:261`) already hold a fully-resolved `Node` object with
`node.node_id` — they pass `node.ip` only to find tasks on **that specific node**.
With `allocated_ip` gone, the natural key is `allocated_node_id = node.node_id`,
which they already have.

Decision: rename the SQL file to `get_ids_by_node_id_and_status.sql` and the
repository method to `list_ids_by_node_id_and_status(node_id: NodeId, status:
TaskStatus) -> list[TaskId]`. The predicate changes
`WHERE ip = :ip AND status = :status` →
`WHERE allocated_node_id = :node_id AND status = :status`.
Both call sites change `node.ip` → `node.node_id`. The
`port `:ip` named param becomes `:node_id` (pg8000 named param, takes
`node_id.value`). `docs/BUGS.md:12` note about "no index on ip" becomes moot
(the FK on `allocated_node_id` is the natural index target — consider adding
one in the migration, but that's a separate concern, not in this change).

### `yastatus` CLI output (accepted break)

- `_render_default` (AiiDA default, `task_id   STATUS`): unchanged.
- `_render_info` (`-i`): `task_id=...\tstatus=...\tlabel=...\tip=...` → replace
  `ip={allocated_ip}` with `node_id={allocated_node_id}` (the user's
  "обычный вывод yastatus меняем ip на node_id").
- `_render_json` (`--json`): new shape (see below).
- `_render_view` (`-v`, verbose): line currently shows
  `... at {username}@{task.allocated_ip}:{cloud_str}:...`. Replace
  `task.allocated_ip` with `node.ip` (the resolved `Node` already has `ip`).
  No spec change needed (verbose format is not pinned).

### New `yastatus --json` object shape (user's decision)

Keep raw task fields, drop `allocated_ip`/`port`/`cloud` flat fields, add nested
`node`:

```
{
  "task_id": int,
  "status": str,                      // task.status.name ("TO_DO"/"RUNNING"/"DONE")
  "label": str,                        // task.label (DB column still "title" after C)
  "engine": str,
  "local_folder": str | null,
  "remote_folder": str | null,
  "created_at": str,                   // ISO-8601
  "updated_at": str,                   // ISO-8601
  "node": {                            // null when task.allocated_node_id is None
    "ip": str,
    "port": int,
    "username": str,
    "cloud": str | null
  } | null
}
```

`node` is built by joining `nodes_by_id.get(task.allocated_node_id)` (already
the pattern). `node == null` for TO_DO / unallocated / orphaned (FK null).

### `Yascheduler` client facade (`client._task_to_dict`) — accepted break

Current 6-key dict: `{task_id, label, ip, status, metadata, cloud}`.
New shape per user: keep `task_id`, `label`, `status`, `metadata`; drop `ip`,
`cloud`; add nested `node` with `{ip, port, username, cloud}`:

```
{
  "task_id": int,
  "label": str,
  "status": TaskStatus,                // IntEnum member (preserves .name/.value, D2)
  "metadata": dict,
  "node": {                            // null when allocated_node_id is None
    "ip": str,
    "port": int,
    "username": str,
    "cloud": str | null
  } | null
}
```

Problem: `client.py` currently does NOT load nodes — `_task_to_dict` is a pure
projection of `Task` with no node lookup. To populate `node`, the client path
must also fetch nodes. Two options:

- (a) `query_tasks` use case additionally returns nodes, or the facade joins
  via `uow.nodes.get_by_ids([...])` (extra round-trip).
- (b) `node` is populated only when a node is resolvable from the current UoW
  context; if the client path doesn't open a nodes query, `node` is `null`.

Open question (see below): how does the client path obtain the `Node` for the
nested `node` field?

### `package-facades` spec changes

The spec currently pins `ip = allocated_ip or ""` and `cloud = None`. Both are
removed. New spec must pin the `node` nested object (or `null`) and the
unchanged `{task_id, label, status, metadata}` keys. The "six-key dict shape"
scenario becomes a five-key-with-nested-node shape.

### `cli` spec changes

The `yastatus --json` requirement (9-field object) is replaced with the new
shape above. The "TO_DO task → allocated_ip null" scenario becomes "TO_DO task
→ node null". The `yanodes` references to `allocated_ip == node.ip` are already
stale (ssh-rekey-node-id rekeyed to `allocated_node_id`); this change cleans
them up.

## C. `label` column → `title` (PG keyword avoidance)

- User rejected `name` (too generic). Decision: **`title`**.
- Domain field stays `Task.label` / `NewTask.label` (unchanged).
- DB column: `yascheduler_tasks.label` → `yascheduler_tasks.title`.
- SQL files: `insert.sql`, `update_by_id.sql`, `get_by_id.sql`,
  `list_by_status.sql`, `list_by_jobs.sql`: `label` → `title` in column lists;
  `:label` → `:title` in params.
- `postgres.py`: `label=task.label` → `title=task.label` (param rename only,
  value unchanged); `row["label"]` → `row["title"]` in `_row_to_task`.
- `yastatus --json` and `client._task_to_dict`: the JSON/dict key stays `"label"`
  (external wire unchanged — the field is the domain name, not the column name).
- Migration: `ALTER TABLE yascheduler_tasks RENAME COLUMN label TO title;`
- `title` is a non-reserved PG keyword, safe as a column name without quoting.

## D. `status: SMALLINT` → PG enum (D2: domain stays IntEnum)

- `CREATE TYPE task_status AS ENUM ('TO_DO', 'RUNNING', 'DONE');`
- `ALTER TABLE yascheduler_tasks ALTER COLUMN status TYPE task_status USING
  CASE status WHEN 0 THEN 'TO_DO' WHEN 1 THEN 'RUNNING' WHEN 2 THEN 'DONE' END;`
- Domain `TaskStatus` stays `IntEnum` (`TO_DO=0, RUNNING=1, DONE=2`) — external
  API keeps `.value` = 0/1/2 (numeric, as pinned).
- Write path: `status=task.status.value` (int) → `status=task.status.name`
  (string) in `save`, `insert`, `update_status`, `list_ids_by_ip_and_status`.
- Read path: `TaskStatus(row["status"])` (int cast, current) →
  `TaskStatus[row["status"]]` (name lookup) in `_row_to_task`.
- `list_by_status` SQL: `cast(:statuses AS int[])` →
  `cast(:statuses AS task_status[])` — **verified** by a pg8000 testcontainers
  spike that `cast(:list AS task_status[])` works when `:list` is a Python
  `list[str]` of enum labels (`['TO_DO', 'RUNNING']`). Form `cast(:statuses AS
  text[])` alone FAILS (`operator does not exist: task_status = text` — no
  implicit cast); `cast(:statuses AS text[])::task_status[]` works as a fallback
  but is redundant. Direct `cast(:statuses AS task_status[])` is the chosen form.
  `status = ANY(cast(:statuses AS task_status[]))` also works (alternative to the
  `IN (SELECT unnest(...))` pattern).
- `count_by_status`: `GROUP BY status` works with enum; the `status` column is
  returned by pg8000.native as a **Python `str`** (e.g. `'TO_DO'`), not an int.
  The caller (`postgres.py:237`) currently does `TaskStatus(row["status"])`
  (int cast) — this **breaks** after the enum change. Must switch to
  `TaskStatus[row["status"]]` (name lookup). Confirmed edit, not a hypothesis.
- `get_ids_by_node_id_and_status.sql`: `status = :status` with a scalar string
  param works against enum — **verified** by spike (Form 5).
- pg8000 row mechanics (relevant to all reads): `pg8000.native.Connection`
  returns rows as `list` (positional); `PostgresTaskRepository._run` (lines
  62-68) manually zips them into dicts via `self._conn.columns`. So `row["status"]`
  in `_row_to_task`/`count_by_status` is dict access over a str value — confirms
  `TaskStatus[row["status"]]` is the correct read form.
- External API impact: NONE. `yastatus --json` still emits `task.status.name`
  (string, same as today). `client._task_to_dict` still emits `t.status`
  (IntEnum, same as today). Webhook still emits `status.value` (int 0/1/2, same).
- `webhook.py:87` `status=status.value`: unchanged (IntEnum `.value` = int).

## Migration ordering

```
006_rename_label_to_title.sql       -- ALTER TABLE ... RENAME COLUMN label TO title
007_add_created_updated_at.sql      -- ADD COLUMN created_at/updated_at + trigger fn + trigger
008_status_to_enum.sql              -- CREATE TYPE + ALTER COLUMN ... USING CASE
009_drop_allocated_ip.sql           -- ALTER TABLE ... DROP COLUMN ip
```

`schema.sql` updated to final snapshot (all four applied); `last_migration`
CONSTANT → `'009'`. Fresh-DB path gets the final shape directly; legacy DBs run
006–009 in order. Each migration is its own transaction (per db-migrations spec).

Ordering rationale: do the additive/rename first (safe, reversible), enum
conversion (data transform), then the destructive column drop last (so a
rollback of the API break can re-add the column without losing the enum/title
work).

## Cross-module data flow (who calls who)

```
submit_task ──▶ NewTask(label, context) ──▶ TaskRepository.insert
                                              │
                                              ▼ INSERT (title, metadata, status, allocated_node_id)
                                            RETURNING task_id, title, status, metadata, allocated_node_id, created_at, updated_at
                                              │
                                              ▼ _row_to_task(row)
                                            Task(task_id, label=title-row, context, status=TaskStatus[row["status"]],
                                                 allocated_node_id, created_at, updated_at)

Task.allocate_to(node) ──▶ replace(allocated_node_id=node.node_id)   [guard: allocated_node_id is not None]
Task.mark_running()    ──▶ replace(status=RUNNING)                  [guard: allocated_node_id is not None]

TaskRepository.save(task) ──▶ UPDATE (title=:label, status=:status.name, metadata, allocated_node_id=:node_id)
                             WHERE task_id = :task_id RETURNING task_id
                             [trigger sets updated_at = NOW()]

yastatus --json ──▶ _query_tasks(uow) ──▶ list_by_status/list_by_jobs
                  ──▶ uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if ...])  [batch, unchanged]
                  ──▶ nodes_by_id: dict[NodeId, Node]
                  ──▶ _render_json: for each task, node = nodes_by_id.get(allocated_node_id)
                                   emit {task_id, status: .name, label, engine, local_folder,
                                         remote_folder, created_at, updated_at,
                                         node: {ip, port, username, cloud} | None}

Yascheduler.queue_get_tasks_async ──▶ query_tasks(jobs, statuses, uow_factory)
                                          │ use case opens ONE UoW
                                          ▼
                                        async with uow_factory() as uow:
                                            tasks = uow.tasks.list_by_status/list_by_jobs
                                            node_ids = {t.allocated_node_id for t in tasks if ...}
                                            nodes = uow.nodes.get_by_ids(list(node_ids))  [batch]
                                        return (tasks, nodes_by_id)
                  ──▶ facade unpacks (tasks, nodes_by_id)
                  ──▶ _task_to_dict(t, nodes_by_id): {task_id, label, status: IntEnum, metadata,
                                                      node: {ip, port, username, cloud} | None}
```

## Open questions

1. ~~`list_ids_by_ip_and_status` / `get_ids_by_ip_and_status.sql`~~ — **RESOLVED**:
   rename to `list_ids_by_node_id_and_status` / `get_ids_by_node_id_and_status.sql`,
   filter by `allocated_node_id = :node_id`. Both callers (`manage_node._remove_node_hard`,
   `_remove_node_soft`) already hold `node.node_id`.

2. ~~`count_by_status` caller int-cast~~ — **RESOLVED**: `postgres.py:237`
   `TaskStatus(row["status"])` (int cast) breaks after enum change (pg8000 returns
   the enum as a Python `str`). Switch to `TaskStatus[row["status"]]` (name
   lookup). Confirmed by spike.

3. ~~pg8000 enum-array binding~~ — **RESOLVED**: `cast(:statuses AS task_status[])`
   works with `list[str]` params. Use that form directly. `cast(:statuses AS
   text[])` alone FAILS (no implicit cast); `::task_status[]` suffix is the
   fallback if ever needed.

4. ~~Client facade node lookup~~ — **RESOLVED** (user chose option a; verified
   single caller). The use case `query_tasks` (in
   `yascheduler/application/query_tasks.py`) is the **sole** production caller of
   the UoW-opening path on the client query route; `check_status.py:124`
   `_query_tasks` is a *different* (private, same-named) helper that takes an
   already-open `uow` and reads the repository directly — it never calls the use
   case and is unrelated to this change.

   Decision: change `query_tasks` return type from `list[Task]` to
   `tuple[list[Task], dict[NodeId, Node]]`. Inside the existing single UoW, after
   fetching tasks, batch-load nodes via `uow.nodes.get_by_ids(list({t.allocated_node_id
   for t in tasks if t.allocated_node_id}))` and return `(tasks, nodes_by_id)`.
   The facade `client.py:191` unpacks the tuple and passes `nodes_by_id` to
   `_task_to_dict`, which projects the nested `node {ip, port, username, cloud}`.

   The facade does **NOT** open its own UoW (my earlier claim was wrong — the
   facade delegates to the use case, which owns the UoW). The use-case return
   type change is the only signature impact.

   Spec impact: `use-cases` (return type of `query_tasks`),
   `package-facades` (facade behavior — unpack tuple, nested node dict shape),
   `postgres-persistence` (no change — `get_by_ids` already exists on
   `NodeRepository`).

5. **`abandon_node.py` CHANGE_SUMMARY** mentions `t.allocated_ip == node.ip`
   historically; the code was already rekeyed to `allocated_node_id`. Verify no
   lingering `allocated_ip` reads in `abandon_node`/`orchestrator` beyond the
   `orchestrator.py:454 ip = task.allocated_ip or ""` (which feeds a log line —
   switch to `node.ip` via the resolved node, or drop the `ip` from the log).

6. **AiiDA plugin** — parses `yastatus` default mode (`task_id   STATUS`),
   unaffected. But confirm no AiiDA code reads `yastatus --json` or
   `queue_get_tasks()["ip"]`. (Quick grep of `aiida_plugin.py` suggests it only
   uses default mode + `_MAP_STATUS_YASCHEDULER` — confirm during implementation.)

7. **`show_nodes` / `yanodes`** — already rekeyed to `tasks_by_node_id`
   (`allocated_node_id`-keyed). Verify no remaining `allocated_ip` reads in
   `show_nodes.py` beyond the `CHANGE_SUMMARY` comment (stale text to clean up).

8. **e2e tests** — `tests/e2e/test_hetzner_live.py` and `test_full_cycle.py`
   assert on `task.allocated_ip`. These need rewriting to assert on
   `task.allocated_node_id` + a node lookup, or on the new `node.ip` JSON field.
   List all e2e/integration assertions touching `allocated_ip`.

## Specs to update (proposal must enumerate)

- `openspec/specs/domain-entities/spec.md` — `Task`/`NewTask` field lists,
  `allocate_to`/`mark_running` guard text.
- `openspec/specs/postgres-persistence/spec.md` — `insert.sql`/`update_by_id.sql`
  /`get_by_id.sql` column lists, `_row_to_task` mapping (name lookup for status,
  no `allocated_ip`, `created_at`/`updated_at` reads).
- `openspec/specs/db-migrations/spec.md` — migrations 006–009.
- `openspec/specs/postgres-schema-apply/spec.md` — `last_migration` CONSTANT
  `'005'` → `'009'`; schema snapshot description.
- `openspec/specs/cli/spec.md` — `yastatus --json` object shape (9→new),
  `_render_info` `ip`→`node_id`, stale `allocated_ip` references in `yanodes`
  section.
- `openspec/specs/package-facades/spec.md` — `Yascheduler` query dict shape
  (6-key → 5-key + nested `node`), remove `ip`/`cloud` pins.
- `openspec/specs/domain-engine-types/spec.md` — likely untouched (engine
  types), confirm.
- `openspec/specs/domain-events-and-dispatch/spec.md` — confirm no change
  (events already use `allocated_node_id`).