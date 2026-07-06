# Delta: postgres-persistence

## MODIFIED Requirements

### Requirement: SQL file layout and lazy loading

The system SHALL store all SQL queries in `infra/persistence/sql/` organized as
`sql/<entity>/<operation>.sql`, loaded via `load_query(name: str) -> str` which
reads the file from the package directory and caches the result (each file read
at most once per process).

- `sql/schema.sql` — the full latest snapshot (every `CREATE TABLE` includes
  all current columns; no inline `ALTER`s). The DO block's `last_migration`
  CONSTANT is the single manual edit point when a migration is added. After the
  task-schema-and-entity-cleanup change, `last_migration` is `'009'` and
  `yascheduler_tasks` reflects the final shape (`title` column, `task_status`
  enum, `created_at`/`updated_at` columns, no `ip` column).
- `sql/migrations/` — forward-only migration files (`{prefix_id}_{rest}.sql`
  or `.py`), applied by `apply_migrations` in string-sorted `prefix_id` order.
- `sql/task/insert.sql` — `INSERT INTO yascheduler_tasks (title, metadata,
  status, allocated_node_id) VALUES (:title, :metadata, :status, :node_id)
  RETURNING task_id, title, status, metadata, allocated_node_id, created_at,
  updated_at`. The `:title` named parameter binds the domain `Task.label`
  value (the DB column is `title`, the domain field is `label`). The `:status`
  named parameter binds the enum-label string (`task.status.name`, was the int
  `task.status.value`). `created_at`/`updated_at` are NOT bound (the DB
  `DEFAULT NOW()` populates them) and are read back via `RETURNING`. The `ip`
  column is absent (dropped by migration 009); the `:ip` named parameter is
  removed.
- `sql/task/update_by_id.sql` — `UPDATE yascheduler_tasks SET title=:title,
  status=:status, metadata=:metadata, allocated_node_id=:node_id WHERE
  task_id = :task_id RETURNING task_id` (partial update keyed by `task_id`;
  NOT an upsert). The `BEFORE UPDATE` trigger `yascheduler_tasks_touch_updated_at`
  sets `updated_at = NOW()` on the row (the application does not set it). The
  `ip=:ip` SET term is removed (the `ip` column is dropped).
- `sql/task/get_by_id.sql` — `SELECT task_id, title, status, metadata,
  allocated_node_id, created_at, updated_at FROM yascheduler_tasks WHERE
  task_id = :task_id`. The `label` column is renamed to `title`; the `ip`
  column is absent; `created_at`/`updated_at` are added.
- `sql/task/list_by_status.sql` — `SELECT task_id, title, status, metadata,
  allocated_node_id, created_at, updated_at FROM yascheduler_tasks WHERE
  status IN (...) ORDER BY task_id LIMIT :lim`. The `status IN (...)` filter
  uses `cast(:statuses AS task_status[])` (the enum-array cast; was
  `cast(:statuses AS int[])`).
- `sql/task/list_by_jobs.sql` — `SELECT task_id, title, status, metadata,
  allocated_node_id, created_at, updated_at FROM yascheduler_tasks WHERE
  task_id IN (...) ORDER BY task_id`.
- `sql/task/update_status.sql` — `UPDATE yascheduler_tasks SET status=...
  WHERE task_id = :task_id RETURNING task_id` (status-only update; does NOT
  touch `allocated_node_id`). The `:status` named parameter binds the
  enum-label string (`task.status.name`, was the int).
- `sql/task/get_ids_by_node_id_and_status.sql` — `SELECT task_id FROM
  yascheduler_tasks WHERE allocated_node_id = :node_id AND status = :status
  ORDER BY task_id` (renamed from `get_ids_by_ip_and_status.sql`; the filter
  key changes from `ip = :ip` to `allocated_node_id = :node_id`; the
  `:status` named parameter binds the enum-label string).
- `sql/task/count_by_status.sql` — aggregate (`GROUP BY status`, works with
  the enum); no `allocated_node_id` column.
- `sql/node/insert.sql` — `INSERT ... VALUES (...) RETURNING node_id`.
- `sql/node/get_by_id.sql` — `WHERE node_id = :node_id`.
- `sql/node/get_by_ids.sql` — `SELECT node_id, ip, ncpus, enabled, cloud,
  username, port FROM yascheduler_nodes WHERE node_id = ANY(:node_ids)` (batch
  lookup by primary-key list; returns 0..N rows).
- `sql/node/list_all.sql` — includes `ORDER BY node_id` (deterministic CLI output).
- `sql/node/enable.sql` — `UPDATE yascheduler_nodes SET enabled=TRUE WHERE node_id = :node_id`.
- `sql/node/disable.sql` — `UPDATE yascheduler_nodes SET enabled=FALSE WHERE node_id = :node_id`.
- `sql/node/remove.sql` — `DELETE FROM yascheduler_nodes WHERE node_id = :node_id`.
- `sql/node/update.sql` — `UPDATE yascheduler_nodes SET ... WHERE node_id = :node_id`.
- The ip-keyed SQL files `sql/node/get_by_ip.sql` and
  `sql/node/get_by_ips.sql` are REMOVED — no caller resolves a node by ip
  after the `ssh-rekey-node-id` change.
- The ip-keyed SQL file `sql/task/get_ids_by_ip_and_status.sql` is REMOVED
  and replaced by `sql/task/get_ids_by_node_id_and_status.sql` (filter by
  `allocated_node_id`, not `ip`).
- Every node SELECT (`list_all`, `get_by_ids`, `list_enabled`,
  `list_disabled`, `get_by_id`) SHALL include `node_id` in its column list.

SQL files SHALL use `:param_name` syntax for pg8000 named-parameter binding.
The `:node_id` named parameter in task SQL files binds the
`allocated_node_id` column of `yascheduler_tasks`. The `:node_ids` named
parameter in `node/get_by_ids.sql` binds a list of `node_id.value` ints
(pg8000 adapts a Python list to a PostgreSQL array for `= ANY(:node_ids)`).
The `:title` named parameter in task SQL files binds the domain `Task.label`
value. The `:status` named parameter in task SQL files binds the enum-label
string (`task.status.name`).

#### Scenario: load_query reads then caches

- **WHEN** `load_query("task/get_by_id")` is called twice
- **THEN** the file `sql/task/get_by_id.sql` is read from disk once; the second call returns the cached string

#### Scenario: Node list_all is ordered by node_id

- **WHEN** `sql/node/list_all.sql` is inspected
- **THEN** it contains `ORDER BY node_id`

#### Scenario: Node SELECTs include node_id

- **WHEN** any of `list_all.sql`, `get_by_ids.sql`, `list_enabled.sql`, `list_disabled.sql`, `get_by_id.sql` is inspected
- **THEN** the column list includes `node_id`

#### Scenario: get_by_ids.sql uses ANY array binding

- **WHEN** `sql/node/get_by_ids.sql` is inspected
- **THEN** the WHERE clause is `WHERE node_id = ANY(:node_ids)` and the column list includes `node_id, ip, ncpus, enabled, cloud, username, port`

#### Scenario: get_by_ip.sql and get_by_ips.sql are removed

- **WHEN** the `sql/node/` directory is inspected
- **THEN** `get_by_ip.sql` and `get_by_ips.sql` are NOT present; the only lookup SQL files are `get_by_id.sql` and `get_by_ids.sql`

#### Scenario: Node mutator SQL keys on node_id

- **WHEN** any of `sql/node/enable.sql`, `sql/node/disable.sql`, `sql/node/remove.sql`, `sql/node/update.sql` is inspected
- **THEN** the `WHERE` clause is `WHERE node_id = :node_id` (not `WHERE ip = :ip`)

#### Scenario: Task SELECTs include created_at and updated_at

- **WHEN** any task SELECT clause (`get_by_id`, `list_by_status`, `list_by_jobs`) or `insert`'s RETURNING clause is inspected
- **THEN** the column list includes `allocated_node_id`, `created_at`, and `updated_at` (and uses `title`, not `label`, for the label column)

#### Scenario: Task insert binds title and status name

- **WHEN** `sql/task/insert.sql` is inspected
- **THEN** the INSERT column list includes `allocated_node_id` (uses `title`, not `label`); the RETURNING clause includes `allocated_node_id`, `created_at`, `updated_at`; the VALUES binds `:node_id` for `allocated_node_id`, `:title` for the label, `:status` for the status; the `ip` column and `:ip` parameter are absent

#### Scenario: Task update_by_id binds title and status name

- **WHEN** `sql/task/update_by_id.sql` is inspected
- **THEN** the SET clause includes `allocated_node_id = :node_id`, `title = :title`, `status = :status`; the `ip = :ip` SET term is absent; `updated_at` is NOT in the SET clause (the trigger sets it)

#### Scenario: Task update_status does not touch allocated_node_id

- **WHEN** `sql/task/update_status.sql` is inspected
- **THEN** the SET clause sets only `status`; `allocated_node_id` is NOT in the SET clause (status-only update)

#### Scenario: list_by_status uses task_status array cast

- **WHEN** `sql/task/list_by_status.sql` is inspected
- **THEN** the status filter uses `cast(:statuses AS task_status[])` (the enum-array cast), NOT `cast(:statuses AS int[])`

#### Scenario: get_ids_by_node_id_and_status.sql replaces ip-keyed file

- **WHEN** the `sql/task/` directory is inspected
- **THEN** `get_ids_by_ip_and_status.sql` is NOT present; `get_ids_by_node_id_and_status.sql` IS present with `WHERE allocated_node_id = :node_id AND status = :status`

### Requirement: PostgresTaskRepository implements TaskRepository

`PostgresTaskRepository` SHALL satisfy the `TaskRepository` Protocol with async
methods `get`, `save`, `insert`, `update_status`, `list_by_status`,
`list_by_jobs`, `list_ids_by_node_id_and_status`, `count_by_status`. The
method `list_ids_by_ip_and_status` is REMOVED and replaced by
`list_ids_by_node_id_and_status(node_id: NodeId, status: TaskStatus)`
(filtering by `allocated_node_id = :node_id` instead of `ip = :ip`).

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
domain `label` field), `status` (the `task.status.name` string — the DB column
is a PostgreSQL enum `task_status`, see the `db-migrations` capability),
`metadata` in the `task/update_by_id.sql` UPDATE. The SQL SHALL SET
`allocated_node_id = :node_id`, `title = :title`, `status = :status`. The SQL
SHALL NOT set `ip` (the column is dropped) and SHALL NOT set `updated_at` (the
`BEFORE UPDATE` trigger sets it). The `label` pg8000 named parameter carries
the value of `task.label` (the param name is `title`, matching the DB column;
the domain field name is `label`).

`insert(new_task: NewTask) -> Task` SHALL run
`task/insert.sql ... RETURNING task_id, title, status, metadata,
allocated_node_id, created_at, updated_at` and return `_row_to_task(rows[0])`
(the `NewTask.task_id` is ignored — none exists; the DB generates it),
avoiding a second `get` round-trip. `insert` SHALL bind
`node_id=new_task.allocated_node_id.value` (or `None`) as the pg8000 named
parameter for the `allocated_node_id` column, alongside `title` (carrying
`new_task.label`), `metadata`, `status` (the `new_task.status.name` string).
`created_at`/`updated_at` are NOT bound — the DB `DEFAULT NOW()` populates them
on insert, and they are read back via `RETURNING`.

`get`, `_row_to_task`, `list_by_jobs`, `list_ids_by_node_id_and_status` SHALL
wrap `TaskId(int(row["task_id"]))` / `task_id.value` at the boundary.
`_row_to_task` SHALL read `allocated_node_id` from the row and construct
`allocated_node_id=NodeId(int(row["allocated_node_id"]))` when
`row["allocated_node_id"]` is not None, else `allocated_node_id=None`.
`_row_to_task` SHALL read `created_at` and `updated_at` from the row (pg8000
returns `datetime` for `TIMESTAMPTZ` columns). `_row_to_task` SHALL read
`status` as a Python `str` (the enum label, e.g. `"TO_DO"`) and construct the
domain enum via `TaskStatus[row["status"]]` (name lookup — NOT
`TaskStatus(row["status"])`, which is an int cast and would raise on a
string). `_row_to_task` SHALL NOT read an `ip`/`allocated_ip` column (the
column is dropped). `_row_to_task` SHALL read `title` (the renamed column)
and map it to the `label` field of `Task`. The 4 task SQL files that return
task rows (`get_by_id`, `list_by_status`, `list_by_jobs`, `insert`'s
RETURNING) SHALL include `title, status, metadata, allocated_node_id,
created_at, updated_at` in their SELECT/RETURNING column lists (renamed from
`label` to `title`, dropped `ip`, added `created_at`/`updated_at`).
`update_by_id.sql`'s RETURNING SHALL include only `task_id` (the current `save`
does not refresh the in-memory `Task`; `updated_at` is observable via a
subsequent read).

`list_by_status(statuses: set[TaskStatus], limit: int | None)` SHALL pass
`statuses=[s.name for s in statuses]` (a `list[str]` of enum labels, was a
`list[int]` of `.value`) to `task/list_by_status.sql`, which SHALL cast the
param via `cast(:statuses AS task_status[])` (the SQL `int[]` cast is replaced
by the enum array cast). `list_by_status.sql` SHALL be verified to work with
pg8000 binding a Python `list[str]` to a `task_status[]` cast (the
`cast(:statuses AS text[])` form FAILS with `operator does not exist:
task_status = text`; the direct `cast(:statuses AS task_status[])` form
works).

`count_by_status()` SHALL run `task/count_by_status.sql` (`GROUP BY status`,
which works with the enum) and return `{TaskStatus[row["status"]]:
row["count"] for row in rows}` — the key construction uses **name lookup**
(`TaskStatus[row["status"]]`, where `row["status"]` is the enum-label string),
NOT int cast (`TaskStatus(row["status"])` would raise on a string).

`list_ids_by_node_id_and_status(node_id: NodeId, status: TaskStatus)` SHALL
run `task/get_ids_by_node_id_and_status.sql` (renamed from
`get_ids_by_ip_and_status.sql`) with predicate
`WHERE allocated_node_id = :node_id AND status = :status`, binding
`node_id=node_id.value` and `status=status.name` (the enum-label string).
It SHALL return `list[TaskId]` (each `TaskId(int(row["task_id"]))`).

`update_status(task_id, status)` SHALL pass `status=status.name` (the enum
label string, was `status.value` the int) to `task/update_status.sql`.

#### Scenario: Get non-existent task
- **WHEN** `get(TaskId(999))` is called and no such row exists
- **THEN** returns `None`

#### Scenario: Save non-existent task raises
- **WHEN** `save(task)` is called with a `task.task_id` that does not exist
- **THEN** `TaskRowNotFoundError` is raised (carrying the `TaskId`) and the task is NOT appended to `_saved_tasks`

#### Scenario: Insert returns Task with generated TaskId, allocated_node_id, and audit timestamps
- **WHEN** `insert(NewTask(label="job", context=ctx))` is called (with `allocated_node_id=None`)
- **THEN** a `Task` with the DB-generated `task_id=TaskId(int(row["task_id"]))`, `allocated_node_id=None`, `created_at` and `updated_at` (DB-generated `datetime` instances) is returned

#### Scenario: Insert binds allocated_node_id when provided
- **WHEN** `insert(NewTask(label="job", context=ctx, allocated_node_id=NodeId(5)))` is called
- **THEN** the INSERT binds `:node_id=5` (the pg8000 named param for the `allocated_node_id` column) and `:status="TO_DO"` (the enum label string, was the int `0`); the returned `Task` carries `allocated_node_id=NodeId(5)`

#### Scenario: Save binds allocated_node_id and status name
- **WHEN** `save(task)` is called with a `task` whose `allocated_node_id=NodeId(7)` and `status=TaskStatus.RUNNING`
- **THEN** the UPDATE binds `:node_id=7` (the pg8000 named param for the `allocated_node_id` column) and `:status="RUNNING"` (the enum label string, was the int `1`); the `BEFORE UPDATE` trigger sets `updated_at` on the row

#### Scenario: Save binds NULL allocated_node_id
- **WHEN** `save(task)` is called with a `task` whose `allocated_node_id=None` (e.g. an unallocated task or a task whose node was deleted)
- **THEN** the UPDATE binds `:node_id=None`

#### Scenario: Update status non-existent task raises
- **WHEN** `update_status(TaskId(999), TaskStatus.RUNNING)` is called and no row with task_id=999 exists
- **THEN** `TaskRowNotFoundError` is raised (carrying `TaskId(999)`)

#### Scenario: List IDs by node_id and status returns TaskIds
- **WHEN** `list_ids_by_node_id_and_status(NodeId(7), TaskStatus.RUNNING)` is called
- **THEN** returns a `list[TaskId]` (each `TaskId(int(row["task_id"]))`), NOT a `list[int]`; the SQL filters by `allocated_node_id = :node_id` (was `ip = :ip`)

#### Scenario: _row_to_task wraps TaskId and NodeId
- **WHEN** `_row_to_task(row)` is called with a row whose `task_id` is the int `7` and `allocated_node_id` is the int `5`
- **THEN** the returned `Task` has `task_id=TaskId(7)` and `allocated_node_id=NodeId(5)`

#### Scenario: _row_to_task handles NULL allocated_node_id
- **WHEN** `_row_to_task(row)` is called with a row whose `allocated_node_id` is NULL (or absent)
- **THEN** the returned `Task` has `allocated_node_id=None`

#### Scenario: _row_to_task reads status by name lookup
- **WHEN** `_row_to_task(row)` is called with a row whose `status` is the string `"RUNNING"`
- **THEN** the returned `Task` has `status=TaskStatus.RUNNING` (constructed via `TaskStatus["RUNNING"]`, NOT `TaskStatus("RUNNING")` which would raise on a string)

#### Scenario: _row_to_task reads title as label
- **WHEN** `_row_to_task(row)` is called with a row whose `title` is the string `"my_job"`
- **THEN** the returned `Task` has `label="my_job"` (the DB column is `title`, the domain field is `label`)

#### Scenario: _row_to_task reads audit timestamps
- **WHEN** `_row_to_task(row)` is called with a row whose `created_at` and `updated_at` are `datetime` instances
- **THEN** the returned `Task` has `created_at` and `updated_at` set to those `datetime` instances

#### Scenario: count_by_status uses name lookup
- **WHEN** `count_by_status()` is called and the rows carry `status` as the enum-label strings `"TO_DO"`, `"RUNNING"`, `"DONE"`
- **THEN** the returned mapping has keys `TaskStatus["TO_DO"]`, `TaskStatus["RUNNING"]`, `TaskStatus["DONE"]` (name lookup, NOT int cast)

#### Scenario: list_by_status passes enum-label strings
- **WHEN** `list_by_status({TaskStatus.TO_DO, TaskStatus.RUNNING})` is called
- **THEN** the SQL is run with `:statuses=["TO_DO", "RUNNING"]` (a `list[str]`, was a `list[int]` of `.value`) and `cast(:statuses AS task_status[])`