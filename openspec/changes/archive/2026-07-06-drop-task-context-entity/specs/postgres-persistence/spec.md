# Spec Delta: postgres-persistence

## MODIFIED Requirements

### Requirement: SQL file layout

The system SHALL keep task SQL in versioned files under
`yascheduler/infra/persistence/sql/task/` loaded via `load_query` (see
`M-PERSISTENCE-SQLLOADER`). The file set and column lists reflect the post-010
schema (`engine`, `remote_folder`, `local_folder`, `webhook_url`, `error`,
`webhook_custom_params`, `extra` typed columns; `metadata` column dropped):

- `sql/schema.sql` — the full latest snapshot (every `CREATE TABLE` includes
  all current columns; no inline `ALTER`s). The DO block's `last_migration`
  CONSTANT is the single manual edit point when a migration is added. After the
  drop-task-context-entity change, `last_migration` is `'010'` and
  `yascheduler_tasks` reflects the final shape (`title` column, `task_status`
  enum, `created_at`/`updated_at` columns, no `ip` column, seven new typed
  columns extracted from the former `metadata` JSONB, no `metadata` column).
- `sql/migrations/` — forward-only migration files (`{prefix_id}_{rest}.sql`
  or `.py`), applied by `apply_migrations` in string-sorted `prefix_id` order.
- `sql/task/insert.sql` — `INSERT INTO yascheduler_tasks (title, engine,
  remote_folder, local_folder, webhook_url, error, webhook_custom_params, extra,
  status, allocated_node_id) VALUES (:title, :engine, :remote_folder,
  :local_folder, :webhook_url, :error, :webhook_custom_params, :extra, :status,
  :node_id) RETURNING task_id, title, engine, remote_folder, local_folder,
  webhook_url, error, webhook_custom_params, extra, status, allocated_node_id,
  created_at, updated_at`. The `:title` named parameter binds the domain
  `Task.label` value. The `:status` named parameter binds the enum-label string
  (`new_task.status.name`). `:engine`, `:remote_folder`, `:local_folder`,
  `:webhook_url`, `:error` bind the typed `NewTask` fields (`remote_folder` and
  `error` are NOT on `NewTask`, so they are bound as `NULL` via the SQL default
  or explicitly `None`). `:webhook_custom_params` and `:extra` bind the JSONB
  dicts (pg8000 adapts `dict` to JSONB natively; no `json.dumps` at the call
  site). `created_at`/`updated_at` are NOT bound (the DB `DEFAULT NOW()`
  populates them) and are read back via `RETURNING`. The `metadata` column and
  `:metadata` parameter are removed.
- `sql/task/update_by_id.sql` — `UPDATE yascheduler_tasks SET title=:title,
  engine=:engine, remote_folder=:remote_folder, local_folder=:local_folder,
  webhook_url=:webhook_url, error=:error, webhook_custom_params=
  :webhook_custom_params, extra=:extra, status=:status, allocated_node_id=
  :node_id WHERE task_id = :task_id RETURNING task_id` (partial update keyed by
  `task_id`; NOT an upsert). The `BEFORE UPDATE` trigger
  `yascheduler_tasks_touch_updated_at` sets `updated_at = NOW()` on the row.
  The `metadata=:metadata` SET term is removed.
- `sql/task/get_by_id.sql` — `SELECT task_id, title, engine, remote_folder,
  local_folder, webhook_url, error, webhook_custom_params, extra, status,
  allocated_node_id, created_at, updated_at FROM yascheduler_tasks WHERE
  task_id = :task_id`. The `metadata` column is absent.
- `sql/task/list_by_status.sql` — `SELECT task_id, title, engine,
  remote_folder, local_folder, webhook_url, error, webhook_custom_params,
  extra, status, allocated_node_id, created_at, updated_at FROM
  yascheduler_tasks WHERE status IN (...) ORDER BY task_id LIMIT :lim`. The
  `status IN (...)` filter uses `cast(:statuses AS task_status[])`.
- `sql/task/list_by_jobs.sql` — `SELECT task_id, title, engine, remote_folder,
  local_folder, webhook_url, error, webhook_custom_params, extra, status,
  allocated_node_id, created_at, updated_at FROM yascheduler_tasks WHERE
  task_id IN (...) ORDER BY task_id`.
- `sql/task/update_status.sql` — unchanged (status-only update; does NOT touch
  the typed columns or `allocated_node_id`).
- `sql/task/get_ids_by_node_id_and_status.sql` — unchanged (returns `task_id`
  only; no typed-column read needed).
- `sql/task/count_by_status.sql` — unchanged (aggregate; no typed-column read
  needed).
- `sql/task/update_meta.sql` — DELETED (dead; zero callers in source and
  tests). The `load_query("task/update_meta")` call path is removed.

#### Scenario: insert.sql binds typed columns
- **WHEN** `task/insert.sql` is inspected for its column list
- **THEN** it includes `title, engine, remote_folder, local_folder, webhook_url, error, webhook_custom_params, extra, status, allocated_node_id` in the INSERT column list and `:title, :engine, :remote_folder, :local_folder, :webhook_url, :error, :webhook_custom_params, :extra, :status, :node_id` in the VALUES; `:metadata` is absent

#### Scenario: update_by_id.sql binds typed columns
- **WHEN** `task/update_by_id.sql` is inspected for its SET clause
- **THEN** it SETs `title=:title, engine=:engine, remote_folder=:remote_folder, local_folder=:local_folder, webhook_url=:webhook_url, error=:error, webhook_custom_params=:webhook_custom_params, extra=:extra, status=:status, allocated_node_id=:node_id`; `metadata=:metadata` is absent

#### Scenario: get_by_id.sql selects typed columns
- **WHEN** `task/get_by_id.sql` is inspected for its SELECT list
- **THEN** it includes `task_id, title, engine, remote_folder, local_folder, webhook_url, error, webhook_custom_params, extra, status, allocated_node_id, created_at, updated_at`; `metadata` is absent

#### Scenario: list_by_status.sql and list_by_jobs.sql select typed columns
- **WHEN** `task/list_by_status.sql` and `task/list_by_jobs.sql` are inspected for their SELECT lists
- **THEN** both include `task_id, title, engine, remote_folder, local_folder, webhook_url, error, webhook_custom_params, extra, status, allocated_node_id, created_at, updated_at`; `metadata` is absent

#### Scenario: update_meta.sql is deleted
- **WHEN** the `sql/task/` directory is inspected for `update_meta.sql`
- **THEN** the file is absent (dead; zero callers); `load_query("task/update_meta")` is not called anywhere

### Requirement: Task repository write semantics

`save(task)` and `update_status(task_id, status)` SHALL execute
`UPDATE ... WHERE task_id = :task_id ... RETURNING task_id`, passing
`task_id.value` as the SQL param (pg8000 cannot adapt a `TaskId` dataclass).
When the UPDATE affects 0 rows (the `task_id` does not exist), they SHALL raise
`TaskRowNotFoundError` (`infra/persistence/exceptions.py`, a `RuntimeError`
subclass taking `task_id: TaskId`). The row-existence check SHALL happen BEFORE
`save()` appends the task to the UoW's `_saved_tasks` list, so a raise never
leaves an orphan task that `publish_events` would later dispatch for.

`save(task)` SHALL bind `node_id=task.allocated_node_id.value` (or `None` when
`task.allocated_node_id is None`) as the pg8000 named parameter for the
`allocated_node_id` column, alongside `title` (the DB column name for the
domain `label` field), `status` (the `task.status.name` string), `engine`,
`remote_folder`, `local_folder`, `webhook_url`, `error`, `webhook_custom_params`,
`extra` in the `task/update_by_id.sql` UPDATE. The SQL SHALL SET all of these
columns. The SQL SHALL NOT set `ip` (dropped) and SHALL NOT set `updated_at`
(the `BEFORE UPDATE` trigger sets it). `webhook_custom_params` and `extra` are
bound as the dict values from `task.webhook_custom_params` / `task.extra`
(pg8000 adapts `dict` to JSONB natively; no `json.dumps` at the call site).

`insert(new_task: NewTask) -> Task` SHALL run `task/insert.sql ... RETURNING
task_id, title, engine, remote_folder, local_folder, webhook_url, error,
webhook_custom_params, extra, status, allocated_node_id, created_at,
updated_at` and return `_row_to_task(rows[0])` (the `NewTask.task_id` is
ignored — none exists; the DB generates it), avoiding a second `get`
round-trip. `insert` SHALL bind `node_id=new_task.allocated_node_id.value` (or
`None`) as the pg8000 named parameter for the `allocated_node_id` column,
alongside `title` (carrying `new_task.label`), `engine`, `local_folder`,
`webhook_url`, `webhook_custom_params`, `extra`, `status` (the
`new_task.status.name` string). `remote_folder` and `error` are NOT on
`NewTask`; they are bound as `None` (the column is nullable; the DB stores
NULL until `with_remote_folder` / `fail` / `reject` sets them on a subsequent
`save`). `created_at`/`updated_at` are NOT bound — the DB `DEFAULT NOW()`
populates them on insert, and they are read back via `RETURNING`.

`get`, `_row_to_task`, `list_by_jobs`, `list_ids_by_node_id_and_status` SHALL
wrap `TaskId(int(row["task_id"]))` / `task_id.value` at the boundary.
`_row_to_task` SHALL read `allocated_node_id` from the row and construct
`allocated_node_id=NodeId(int(row["allocated_node_id"]))` when
`row["allocated_node_id"]` is not None, else `allocated_node_id=None`.
`_row_to_task` SHALL read `created_at` and `updated_at` from the row (pg8000
returns `datetime` for `TIMESTAMPTZ` columns). `_row_to_task` SHALL read
`status` as a Python `str` (the enum label) and construct the domain enum via
`TaskStatus[row["status"]]` (name lookup). `_row_to_task` SHALL read `title`
and map it to the `label` field of `Task`. `_row_to_task` SHALL read the seven
typed columns (`engine`, `remote_folder`, `local_folder`, `webhook_url`,
`error`, `webhook_custom_params`, `extra`) directly from the row and assign
them to the corresponding `Task` fields. `webhook_custom_params` and `extra`
arrive as Python `dict` (pg8000 adapts JSONB to `dict` natively); if pg8000
returns them as a `str`, `_row_to_task` SHALL `json.loads` them (defensive —
pg8000's JSONB adaptation normally returns `dict`, but a str fallback path is
preserved). `_row_to_task` SHALL NOT read a `metadata` column (the column is
dropped). `_row_to_task` SHALL NOT construct a `TaskContext` (the value object
is removed — see the `domain-entities` delta). The 4 task SQL files that
return task rows (`get_by_id`, `list_by_status`, `list_by_jobs`, `insert`'s
RETURNING) SHALL include `title, engine, remote_folder, local_folder,
webhook_url, error, webhook_custom_params, extra, status, allocated_node_id,
created_at, updated_at` in their SELECT/RETURNING column lists.
`update_by_id.sql`'s RETURNING SHALL include only `task_id` (the current
`save` does not refresh the in-memory `Task`; `updated_at` is observable via
the trigger on the next read).

#### Scenario: save binds typed columns
- **WHEN** `save(task)` is called on a Task with `engine="cp2k"`, `remote_folder="/r"`, `local_folder="/l"`, `webhook_url=None`, `error=None`, `webhook_custom_params={"parent": 42}`, `extra={"input.in": "ATOMS"}`
- **THEN** the SQL binds `:engine="cp2k"`, `:remote_folder="/r"`, `:local_folder="/l"`, `:webhook_url=None`, `:error=None`, `:webhook_custom_params={"parent": 42}` (dict → JSONB via pg8000), `:extra={"input.in": "ATOMS"}` (dict → JSONB), alongside `:title=task.label`, `:status=task.status.name`, `:node_id=task.allocated_node_id.value or None`; `:metadata` is NOT bound (the column and parameter are removed)

#### Scenario: insert binds typed columns and NULLs for NewTask-absent fields
- **WHEN** `insert(new_task)` is called on a NewTask with `engine="cp2k"`, `local_folder="/l"`, `webhook_custom_params={}`, `extra={"input.in": "ATOMS"}`
- **THEN** the SQL binds `:engine="cp2k"`, `:local_folder="/l"`, `:webhook_url=None`, `:webhook_custom_params={}` (dict → JSONB), `:extra={"input.in": "ATOMS"}` (dict → JSONB), alongside `:title=new_task.label`, `:status="TO_DO"`, `:node_id=None`; `:remote_folder=None` and `:error=None` are bound (the columns are nullable and `NewTask` carries no such fields); `:metadata` is NOT bound

#### Scenario: _row_to_task reads typed columns
- **WHEN** `_row_to_task(row)` is called on a row with `row["engine"]="cp2k"`, `row["remote_folder"]="/r"`, `row["local_folder"]="/l"`, `row["webhook_url"]=None`, `row["error"]=None`, `row["webhook_custom_params"]={"parent": 42}`, `row["extra"]={"input.in": "ATOMS"}`
- **THEN** the returned `Task` has `engine="cp2k"`, `remote_folder="/r"`, `local_folder="/l"`, `webhook_url=None`, `error=None`, `webhook_custom_params={"parent": 42}`, `extra={"input.in": "ATOMS"}`; no `TaskContext` is constructed; `row["metadata"]` is NOT accessed

#### Scenario: _row_to_task json.loads fallback for JSONB-as-str
- **WHEN** `_row_to_task(row)` is called on a row where pg8000 returned `row["webhook_custom_params"]` as a `str` (e.g. `'{"parent": 42}'`)
- **THEN** `_row_to_task` SHALL `json.loads` the string into a `dict` before assigning it to `Task.webhook_custom_params` (defensive fallback; pg8000 normally returns `dict` for JSONB)

#### Scenario: No metadata column read
- **WHEN** `_row_to_task(row)` is inspected for access to `row["metadata"]`
- **THEN** no such access exists (the column is dropped; the field is removed from the SQL SELECT/RETURNING lists)

#### Scenario: No TaskContext construction in _row_to_task
- **WHEN** `_row_to_task` is inspected for `TaskContext` references
- **THEN** no `TaskContext.from_metadata` call and no `TaskContext(...)` construction exist (the value object is removed)

#### Scenario: No json.dumps in insert or save
- **WHEN** `insert` and `save` are inspected for `json.dumps` calls
- **THEN** no `json.dumps` exists on the `:metadata` parameter (the `metadata` column is removed); `webhook_custom_params` and `extra` are bound as `dict` values and pg8000 adapts them to JSONB natively

## REMOVED Requirements

### Requirement: JSONB metadata roundtrip

**Reason**: The `metadata` JSONB column is extracted into seven typed columns
(migration 010, see the `db-migrations` delta) plus `extra` JSONB. There is no
single `metadata` JSONB to round-trip. `TaskContext.to_metadata()` /
`TaskContext.from_metadata()` are removed (see the `domain-entities` delta);
persistence reads/writes typed columns directly. `webhook_custom_params` and
`extra` are JSONB columns adapted natively by pg8000 (dict ↔ JSONB), so no
manual `json.dumps`/`json.loads` is needed for those columns except the
defensive str-fallback in `_row_to_task`.

**Migration**:
- `insert` / `save` bind typed columns directly (`:engine`, `:remote_folder`, `:local_folder`, `:webhook_url`, `:error`, `:webhook_custom_params`, `:extra`); no `:metadata` parameter; no `json.dumps(task.context.to_metadata())`
- `_row_to_task` reads typed columns directly; no `TaskContext.from_metadata(row["metadata"])`; no `json.loads(row["metadata"])`
- The flat `metadata` dict for the public `queue_get_tasks*` facade is reconstructed at read time in `_task_to_dict` (`client.py`, see the `package-facades` delta), not by `TaskContext.to_metadata()`