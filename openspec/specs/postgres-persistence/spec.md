# PostgreSQL Persistence

## Purpose

PostgreSQL-backed persistence adapter: `PostgresUnitOfWork` (transaction
boundaries, connection lifecycle), `PostgresTaskRepository` /
`PostgresNodeRepository` (satisfying the domain ports), the SQL file layout and
`load_query` caching, and the `TaskRowNotFoundError` /
`UnitOfWorkNotInitializedError` persistence exceptions. Built on pg8000 with all
synchronous calls dispatched through a `ThreadPoolExecutor`.

## Requirements

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
### Requirement: PostgresUnitOfWork transactional boundaries

`PostgresUnitOfWork` (`infra/persistence/postgres_uow.py`) SHALL manage a shared
pg8000 connection across `PostgresTaskRepository` and `PostgresNodeRepository`
with commit/rollback semantics, satisfying the `AbstractUnitOfWork` Protocol. It
SHALL be constructed from a `PostgresDbConfig`, creating a fresh connection on
each context entry, and SHALL close the connection on context exit regardless of
success or failure.

Accessing `tasks` / `nodes`, or calling `commit()` / `rollback()` without
entering the `async with` context SHALL raise
`UnitOfWorkNotInitializedError` (`infra/persistence/exceptions.py`, a
`RuntimeError` subclass).

#### Scenario: Enter context creates connection and repositories
- **WHEN** `async with PostgresUnitOfWork(config) as uow`
- **THEN** `uow.tasks` is a `PostgresTaskRepository` and `uow.nodes` is a `PostgresNodeRepository`, both sharing the same connection

#### Scenario: Exception triggers rollback
- **WHEN** an exception occurs inside the `async with` block
- **THEN** the transaction is rolled back before the connection is closed

#### Scenario: Normal exit without explicit commit loses changes
- **WHEN** the `async with` block completes without exception and without calling `commit()`
- **THEN** the transaction is not committed; the connection is still closed

#### Scenario: Accessing repositories outside context raises UnitOfWorkNotInitializedError
- **WHEN** `uow.tasks`/`uow.nodes`/`uow.commit()`/`uow.rollback()` is accessed without entering the context (or after exit)
- **THEN** `UnitOfWorkNotInitializedError` is raised (NOT `RuntimeError`); `isinstance(exc, RuntimeError)` is `True`

#### Scenario: Connection closed after use
- **WHEN** `async with uow: ...` completes (success or failure)
- **THEN** the underlying pg8000 connection is closed

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

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with async
methods `get_by_id`, `get_by_ids`, `list_enabled`, `list_disabled`, `list_all`,
`insert`, `update`, `enable`, `disable`, `remove`, `count_by_cloud`,
`count_by_status`. The ip-keyed methods `get(ip: str)` and `get_by_ips(ips:
list[str])` are REMOVED. `add_tmp` is **removed** — there is no `add_tmp`
method; the tmp-reservation flow uses `insert`.

`insert(new_node: NewNode) -> Node` SHALL run `node/insert.sql` with `RETURNING
node_id` and return a `Node` carrying the generated `NodeId`. When called with
`NewNode(cloud=..., enabled=False)` (the tmp-reservation path, with `ip=""`
and `ncpus=0` defaults from `NewNode`), it SHALL insert a row with
`ip=""`, `enabled=FALSE`, the given `cloud`, and `username`/`port` from the
`NewNode` defaults (`"root"`, `22`). The returned `Node` carries the generated
`node_id`, which is the tmp-node cleanup handle AND the real-node identity
reused by `clouds.allocate`. `get_by_id(node_id: NodeId)` SHALL run
`node/get_by_id.sql` (`WHERE node_id = :node_id`), passing `node_id.value`.
`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]` SHALL run
`node/get_by_ids.sql` (`WHERE node_id = ANY(:node_ids)`), passing
`[n.value for n in node_ids]` as the SQL param, and return a dict keyed by
`NodeId` (constructed from each row's `node_id`). `_row_to_node` SHALL read
`node_id` from every node row and construct `NodeId(int(row["node_id"]))`.

`list_all()` SHALL return nodes ordered by `node_id` ascending (the SQL
includes `ORDER BY node_id`); it returns ALL rows regardless of `enabled` or
`ip` (including tmp rows with `ip=""`), because `_count_nodes_by_cloud` in
`allocate_task` counts tmp rows toward `max_nodes` capacity.

`list_enabled()` SHALL run `node/list_enabled.sql` (`WHERE enabled = TRUE`)
with **no python post-filter**.

`list_disabled()` SHALL run `node/list_disabled.sql`
(`WHERE enabled = FALSE AND ip <> ''`).

`enable(node_id: NodeId)`, `disable(node_id: NodeId)`, and
`remove(node_id: NodeId)` SHALL run `node/{enable,disable,remove}.sql` with
`WHERE node_id = :node_id`, binding `node_id.value` as the SQL parameter.

`update(node: Node)` SHALL run `node/update.sql` with `WHERE node_id = :node_id`,
binding `node.node_id.value` as the key parameter alongside the field params
(`ip`, `ncpus`, `enabled`, `cloud`, `username`, `port`). The `ip` field MUST be
in the `SET` clause — the V1 cloud-allocation lifecycle relies on `update` to
flip the tmp row's `ip` from `""` (the NewNode default) to the real VM ip in a
single `UPDATE`; an `update.sql` without `ip` in `SET` would leave cloud nodes
unreachable after daemon restart and excluded from `list_disabled.sql`'s
`WHERE ip <> ''` filter (VM leak).

`_row_to_node` SHALL map `ip=row["ip"]` unchanged; `""` is a valid `str` and
the mapping works without changes.

#### Scenario: Insert returns Node with generated id

- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned with `node_id == NodeId(<generated>)` and matching non-id fields

#### Scenario: Get by id returns None when missing

- **WHEN** `get_by_id(NodeId(999))` is called and no row matches
- **THEN** returns `None`; the SQL parameter is bound as `node_id.value` (the bare int)

#### Scenario: Get by ids returns dict keyed by NodeId

- **WHEN** `get_by_ids([NodeId(5), NodeId(7)])` is called and rows with node_id=5 and node_id=7 exist
- **THEN** a `dict[NodeId, Node]` is returned with keys `NodeId(5)` and `NodeId(7)`; missing node_ids are absent from the dict; the SQL parameter is `[5, 7]` (the bare ints from `NodeId.value`)

#### Scenario: Get by ids with empty list returns empty dict

- **WHEN** `get_by_ids([])` is called
- **THEN** `node/get_by_ids.sql` runs with `:node_ids = []` (empty array); the result is empty; an empty `dict[NodeId, Node]` is returned

#### Scenario: Row mapping wraps NodeId

- **WHEN** any node SELECT returns a row `{"node_id": 7, "ip": "10.0.0.1", ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(7)`

#### Scenario: List all is ordered by node_id and includes tmp rows

- **WHEN** `list_all()` is called on a DB with a mix of enabled, disabled, and tmp (`ip=""`) rows
- **THEN** returns all rows (including `ip=""` tmp rows) ordered by `node_id` ascending

#### Scenario: List enabled has no python post-filter

- **WHEN** `list_enabled()` is called on a DB with enabled real nodes and disabled tmp rows (`ip=""`)
- **THEN** returns only `enabled=TRUE` rows (the SQL `WHERE enabled = TRUE` is the only filter); no python post-filter runs

#### Scenario: List disabled filters empty-ip rows in SQL

- **WHEN** `list_disabled()` is called on a DB with real-disabled VMs (`ip<>""`) and tmp rows (`ip=""`)
- **THEN** returns only disabled rows with `ip <> ""` (the SQL `WHERE enabled = FALSE AND ip <> ''` is the filter)

#### Scenario: Enable binds node_id.value

- **WHEN** `enable(NodeId(7))` is called
- **THEN** `node/enable.sql` runs with `:node_id` bound to `7` (the bare int from `NodeId.value`)

#### Scenario: Disable binds node_id.value

- **WHEN** `disable(NodeId(7))` is called
- **THEN** `node/disable.sql` runs with `:node_id` bound to `7` (the bare int from `NodeId.value`)

#### Scenario: Remove binds node_id.value

- **WHEN** `remove(NodeId(7))` is called
- **THEN** `node/remove.sql` runs with `:node_id` bound to `7` (the bare int from `NodeId.value`)

#### Scenario: Update binds node.node_id.value as key

- **WHEN** `update(node)` is called with a `Node` whose `node_id == NodeId(7)`
- **THEN** `node/update.sql` runs with `:node_id` bound to `7` (from `node.node_id.value`) as the `WHERE` key, alongside the field params

#### Scenario: Insert serves the tmp-reservation path

- **WHEN** `insert(NewNode(cloud="aws", enabled=False))` is called (relying on `NewNode.ip=""` and `NewNode.ncpus=0` defaults)
- **THEN** a row is inserted with `ip=""`, `enabled=FALSE`, `cloud="aws"`, `username="root"`, `port=22`; a `Node` is returned carrying the generated `node_id` (the tmp-node cleanup handle AND the real-node identity reused by `clouds.allocate`)

#### Scenario: Row mapping handles empty-string ip

- **WHEN** a node SELECT returns a row `{"node_id": 12, "ip": "", "enabled": false, ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(12)`, `ip == ""`, `enabled == False` (the `""` is a valid `str`, no mapping change)

#### Scenario: No get(ip) method

- **WHEN** `PostgresNodeRepository` is inspected for `get`
- **THEN** no `get(ip: str)` method is defined; node lookups are `get_by_id` / `get_by_ids` only

#### Scenario: No get_by_ips method

- **WHEN** `PostgresNodeRepository` is inspected for `get_by_ips`
- **THEN** no `get_by_ips(ips: list[str])` method is defined; batch lookups are `get_by_ids` only

#### Scenario: No add_tmp method

- **WHEN** `PostgresNodeRepository` is inspected for `add_tmp`
- **THEN** no `add_tmp` method is defined; the tmp path uses `insert`; `node/insert_tmp.sql` is removed from the SQL file layout

### Requirement: All repository methods avoid blocking the event loop

All repository methods SHALL be async and dispatch synchronous pg8000 calls
through a `ThreadPoolExecutor` to avoid blocking the event loop.

#### Scenario: Async method does not block
- **WHEN** `get(task_id)` is called from an async context
- **THEN** the event loop is not blocked during the database call
