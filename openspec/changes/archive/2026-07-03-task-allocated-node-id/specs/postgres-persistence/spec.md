## MODIFIED Requirements

### Requirement: PostgresTaskRepository implements TaskRepository

`PostgresTaskRepository` SHALL satisfy the `TaskRepository` Protocol with async
methods `get`, `save`, `insert`, `update_status`, `list_by_status`,
`list_by_jobs`, `list_ids_by_ip_and_status`, `count_by_status`.

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
`allocated_node_id` column, alongside `label`, `status`, `ip`, `metadata` in
the `task/update_by_id.sql` UPDATE. The SQL SHALL SET
`allocated_node_id = :node_id`.

`insert(new_task: NewTask) -> Task` SHALL run
`task/insert.sql ... RETURNING task_id, label, ip, status, metadata,
allocated_node_id` and return `_row_to_task(rows[0])` (the `NewTask.task_id` is
ignored — none exists; the DB generates it), avoiding a second `get` round-trip.
`insert` SHALL bind `node_id=new_task.allocated_node_id.value` (or `None`) as
the pg8000 named parameter for the `allocated_node_id` column, alongside
`label`, `metadata`, `ip`, `status`.

`get`, `_row_to_task`, `list_by_jobs`, `list_ids_by_ip_and_status` SHALL wrap
`TaskId(int(row["task_id"]))` / `task_id.value` at the boundary. `_row_to_task`
SHALL read `allocated_node_id` from the row and construct
`allocated_node_id=NodeId(int(row["allocated_node_id"]))` when
`row["allocated_node_id"]` is not None, else `allocated_node_id=None`. The 5
task SQL files that return task rows (`get_by_id`, `list_by_status`,
`list_by_jobs`, `insert`'s RETURNING, `update_by_id`'s RETURNING) SHALL include
`allocated_node_id` in their SELECT/RETURNING column lists so `_row_to_task`
can read it.

#### Scenario: Get non-existent task
- **WHEN** `get(TaskId(999))` is called and no such row exists
- **THEN** returns `None`

#### Scenario: Save non-existent task raises
- **WHEN** `save(task)` is called with a `task.task_id` that does not exist
- **THEN** `TaskRowNotFoundError` is raised (carrying the `TaskId`) and the task is NOT appended to `_saved_tasks`

#### Scenario: Insert returns Task with generated TaskId and allocated_node_id
- **WHEN** `insert(NewTask(label="job", context=ctx))` is called (with `allocated_node_id=None`)
- **THEN** a `Task` with the DB-generated `task_id=TaskId(int(row["task_id"]))`, `allocated_node_id=None` is returned

#### Scenario: Insert binds allocated_node_id when provided
- **WHEN** `insert(NewTask(label="job", context=ctx, allocated_node_id=NodeId(5)))` is called
- **THEN** the INSERT binds `:node_id=5` (the pg8000 named param for the `allocated_node_id` column); the returned `Task` carries `allocated_node_id=NodeId(5)`

#### Scenario: Save binds allocated_node_id
- **WHEN** `save(task)` is called with a `task` whose `allocated_node_id=NodeId(7)`
- **THEN** the UPDATE binds `:node_id=7` (the pg8000 named param for the `allocated_node_id` column); the `allocated_ip` is also bound (unchanged)

#### Scenario: Save binds NULL allocated_node_id
- **WHEN** `save(task)` is called with a `task` whose `allocated_node_id=None` (e.g. an unallocated task or a task whose node was deleted)
- **THEN** the UPDATE binds `:node_id=None`

#### Scenario: Update status non-existent task raises
- **WHEN** `update_status(TaskId(999), TaskStatus.RUNNING)` is called and no row with task_id=999 exists
- **THEN** `TaskRowNotFoundError` is raised (carrying `TaskId(999)`)

#### Scenario: List IDs by IP and status returns TaskIds
- **WHEN** `list_ids_by_ip_and_status("10.0.0.1", TaskStatus.RUNNING)` is called
- **THEN** returns a `list[TaskId]` (each `TaskId(int(row["task_id"]))`), NOT a `list[int]`

#### Scenario: _row_to_task wraps TaskId and NodeId
- **WHEN** `_row_to_task(row)` is called with a row whose `task_id` is the int `7` and `allocated_node_id` is the int `5`
- **THEN** the returned `Task` has `task_id=TaskId(7)` and `allocated_node_id=NodeId(5)`

#### Scenario: _row_to_task handles NULL allocated_node_id
- **WHEN** `_row_to_task(row)` is called with a row whose `allocated_node_id` is NULL (or absent)
- **THEN** the returned `Task` has `allocated_node_id=None`

### Requirement: SQL file layout and lazy loading

The system SHALL store all SQL queries in `infra/persistence/sql/` organized as
`sql/<entity>/<operation>.sql`, loaded via `load_query(name: str) -> str` which
reads the file from the package directory and caches the result (each file read
at most once per process).

- `sql/schema.sql` — the full latest snapshot (every `CREATE TABLE` includes
  all current columns; no inline `ALTER`s). The DO block's `last_migration`
  CONSTANT is the single manual edit point when a migration is added.
- `sql/migrations/` — forward-only migration files (`{prefix_id}_{rest}.sql`
  or `.py`), applied by `apply_migrations` in string-sorted `prefix_id` order.
- `sql/task/insert.sql` — `INSERT INTO yascheduler_tasks (label, metadata, ip,
  status, allocated_node_id) VALUES (:label, :metadata, :ip, :status, :node_id)
  RETURNING task_id, label, ip, status, metadata, allocated_node_id`.
- `sql/task/update_by_id.sql` — `UPDATE yascheduler_tasks SET label=:label,
  ip=:ip, status=:status, metadata=:metadata, allocated_node_id=:node_id WHERE
  task_id = :task_id RETURNING task_id` (partial update keyed by `task_id`; NOT
  an upsert).
- `sql/task/get_by_id.sql` — `SELECT task_id, label, ip, status, metadata,
  allocated_node_id FROM yascheduler_tasks WHERE task_id = :task_id`.
- `sql/task/list_by_status.sql` — `SELECT task_id, label, ip, status, metadata,
  allocated_node_id FROM yascheduler_tasks WHERE status IN (...) ORDER BY
  task_id LIMIT :lim`.
- `sql/task/list_by_jobs.sql` — `SELECT task_id, label, ip, status, metadata,
  allocated_node_id FROM yascheduler_tasks WHERE task_id IN (...) ORDER BY
  task_id`.
- `sql/task/update_status.sql` — `UPDATE yascheduler_tasks SET status=...
  WHERE task_id = :task_id RETURNING task_id` (status-only update; does NOT
  touch `allocated_node_id`).
- `sql/task/get_ids_by_ip_and_status.sql` — `SELECT task_id FROM
  yascheduler_tasks WHERE ip = :ip AND status = :status ORDER BY task_id`
  (returns task_ids only; no `allocated_node_id` in the SELECT — this is a
  read-path lookup that stays ip-keyed until Surface A).
- `sql/task/count_by_status.sql` — aggregate; no `allocated_node_id` column.
- `sql/node/insert.sql` — `INSERT ... VALUES (...) RETURNING node_id`.
- `sql/node/get_by_id.sql` — `WHERE node_id = :node_id`.
- `sql/node/list_all.sql` — includes `ORDER BY node_id` (deterministic CLI output).
- `sql/node/enable.sql` — `UPDATE yascheduler_nodes SET enabled=TRUE WHERE node_id = :node_id`.
- `sql/node/disable.sql` — `UPDATE yascheduler_nodes SET enabled=FALSE WHERE node_id = :node_id`.
- `sql/node/remove.sql` — `DELETE FROM yascheduler_nodes WHERE node_id = :node_id`.
- `sql/node/update.sql` — `UPDATE yascheduler_nodes SET ... WHERE node_id = :node_id`.
- Every node SELECT (`get_by_ip`, `list_all`, `get_by_ips`, `list_enabled`, `list_disabled`, `get_by_id`) SHALL include `node_id` in its column list.

SQL files SHALL use `:param_name` syntax for pg8000 named-parameter binding.
The `:node_id` named parameter in task SQL files binds the
`allocated_node_id` column of `yascheduler_tasks` (the column name is
`allocated_node_id`; `:node_id` is the pg8000 param name, chosen for brevity
and parallel with the node SQL files' `:node_id` param).

#### Scenario: load_query reads then caches
- **WHEN** `load_query("task/get_by_id")` is called twice
- **THEN** the file `sql/task/get_by_id.sql` is read from disk once; the second call returns the cached string

#### Scenario: Node list_all is ordered by node_id
- **WHEN** `sql/node/list_all.sql` is inspected
- **THEN** it contains `ORDER BY node_id`

#### Scenario: Node SELECTs include node_id
- **WHEN** any of `get_by_ip.sql`, `list_all.sql`, `get_by_ips.sql`, `list_enabled.sql`, `list_disabled.sql`, `get_by_id.sql` is inspected
- **THEN** the column list includes `node_id`

#### Scenario: Node mutator SQL keys on node_id
- **WHEN** any of `sql/node/enable.sql`, `sql/node/disable.sql`, `sql/node/remove.sql`, `sql/node/update.sql` is inspected
- **THEN** the `WHERE` clause is `WHERE node_id = :node_id` (not `WHERE ip = :ip`)

#### Scenario: Task SELECTs include allocated_node_id
- **WHEN** any task SELECT clause (`get_by_id`, `list_by_status`, `list_by_jobs`) or `insert`'s RETURNING clause is inspected
- **THEN** the column list includes `allocated_node_id` (these are the queries whose rows feed `_row_to_task`; `update_by_id`'s RETURNING returns `task_id` only, used for the 0-row existence check, and does NOT feed `_row_to_task`)

#### Scenario: Task insert binds allocated_node_id
- **WHEN** `sql/task/insert.sql` is inspected
- **THEN** the INSERT column list includes `allocated_node_id` and the RETURNING clause includes `allocated_node_id`; the VALUES binds `:node_id` for that column

#### Scenario: Task update_by_id binds allocated_node_id
- **WHEN** `sql/task/update_by_id.sql` is inspected
- **THEN** the SET clause includes `allocated_node_id = :node_id`

#### Scenario: Task update_status does not touch allocated_node_id
- **WHEN** `sql/task/update_status.sql` is inspected
- **THEN** the SET clause sets only `status`; `allocated_node_id` is NOT in the SET clause (status-only update)