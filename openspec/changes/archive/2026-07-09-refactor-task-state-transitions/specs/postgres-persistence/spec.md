## MODIFIED Requirements

### Requirement: Task repository write semantics

`save(task)` and `update_status(task_id, status)` SHALL execute
`UPDATE ... WHERE task_id = :task_id ... RETURNING task_id`, passing
`task_id.value` as the SQL param (pg8000 cannot adapt a `TaskId` dataclass).
When the UPDATE affects 0 rows (the `task_id` does not exist), they SHALL raise
`TaskRowNotFoundError` (`infra/persistence/exceptions.py`, a `RuntimeError`
subclass taking `task_id: TaskId`). The row-existence check SHALL happen BEFORE
`save()` appends the task to the UoW's `_saved_tasks` list, so a raise never
leaves an orphan task that `publish_events` would later dispatch for.

#### Scenario: save raises TaskRowNotFoundError for missing task_id
- **WHEN** `save(task)` is called with a `task_id` that does not exist in the database
- **THEN** `TaskRowNotFoundError` is raised BEFORE the task is appended to `_saved_tasks`

`save(task)` SHALL bind `node_id=task.allocated_node_id.value` (or `None` when
`task.allocated_node_id is None`) as the pg8000 named parameter for the
`allocated_node_id` column, alongside `title` (the DB column name for the domain
`label` field), `status` (the `task.status.name` string), `engine`,
`remote_folder`, `local_folder`, `webhook_url`, `error`, `webhook_custom_params`,
`extra` in the `task/update_by_id.sql` UPDATE. The SQL SHALL SET all of these
columns. The SQL SHALL NOT set `ip` (dropped) and SHALL NOT set `updated_at`
(the `BEFORE UPDATE` trigger sets it). `webhook_custom_params` and `extra` are
bound as the dict values from `task.webhook_custom_params` / `task.extra`
(pg8000 adapts `dict` to JSONB natively; no `json.dumps` at the call site).

`insert(new_task: NewTask) -> Task` SHALL run `task/insert.sql ... RETURNING`
and return `materialize_task(self._row_to_task(rows[0]))` (the `NewTask.task_id`
is ignored — none exists; the DB generates it), avoiding a second `get`
round-trip. `materialize_task` (see the `domain-entities` capability) attaches
the `TaskCreated` event to the returned `Task`'s `events` field. The
infrastructure layer SHALL NOT import `TaskCreated` directly; `materialize_task`
owns event construction in the domain layer. `insert` SHALL bind `node_id=None`
as the pg8000 named parameter for the `allocated_node_id` column (a freshly
inserted TO_DO task is unallocated), alongside `title` (carrying
`new_task.label`), `engine`, `local_folder`, `webhook_url`,
`webhook_custom_params`, `extra`, `status` (`TaskStatus.TO_DO.name`). The
prior paragraph's reference to `new_task.allocated_node_id` /
`new_task.status.name` is REMOVED — `NewTask` carries no `allocated_node_id`
and no `status`; `insert` binds `None` and `TaskStatus.TO_DO.name` as
constants. `remote_folder` and `error` are NOT on `NewTask`; they are bound
as `None` (the column is nullable; the DB stores NULL until `run` sets
`remote_folder` and `reject`/`fail`/`abandon` sets `error` on a subsequent
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
is removed — see the `domain-entities` delta). `_row_to_task` SHALL always set
`events=()` (events are transient; the DB has no events column). The 4 task
SQL files that return task rows (`get_by_id`, `list_by_status`, `list_by_jobs`,
`insert`'s RETURNING) SHALL include the column set from `schema.sql`.
`update_by_id.sql`'s RETURNING SHALL include only `task_id` (the current
`save` does not refresh the in-memory `Task`; `updated_at` is observable via
the trigger on the next read).

#### Scenario: insert returns Task with TaskCreated via materialize_task
- **WHEN** `insert(new_task)` is called with a valid `NewTask`
- **THEN** the returned `Task` has the DB-generated `task_id`, `status=TO_DO`, `allocated_node_id=None`, `remote_folder=None`, `error=None`, and `events` containing one `TaskCreated` event (attached by `materialize_task`)

#### Scenario: _row_to_task always sets events to empty tuple
- **WHEN** `_row_to_task(row)` is called for any DB row
- **THEN** the returned `Task` has `events=()` (events are transient; only `insert` via `materialize_task` attaches `TaskCreated`)