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
`M-PERSISTENCE-SQLLOADER`). SQL query files follow the column set defined in
`yascheduler/infra/persistence/sql/schema.sql`; see that file for exact DDL.

- `sql/schema.sql` — the full latest snapshot (every `CREATE TABLE` includes
  all current columns; no inline `ALTER`s). The DO block's `last_migration`
  CONSTANT is the single manual edit point when a migration is added.
- `sql/migrations/` — forward-only migration files (`{prefix_id}_{rest}.sql`
  or `.py`), applied by `apply_migrations` in string-sorted `prefix_id` order.
- `sql/task/insert.sql` — INSERT with RETURNING.
- `sql/task/update_by_id.sql` — UPDATE keyed by `task_id`; NOT an upsert.
- `sql/task/get_by_id.sql` — SELECT by task_id.
- `sql/task/list_by_status.sql` — SELECT filtered by status.
- `sql/task/list_by_jobs.sql` — SELECT filtered by task_id list.
- `sql/task/update_status.sql` — status-only update.
- `sql/task/get_ids_by_node_id_and_status.sql` — returns task_id only.
- `sql/task/count_by_status.sql` — aggregate.
- `sql/task/update_meta.sql` — DELETED (dead; zero callers). The
  `load_query("task/update_meta")` call path is removed.

#### Scenario: SQL files loaded via load_query
- **WHEN** `load_query("task/insert")` is called
- **THEN** the content of `sql/task/insert.sql` is returned; subsequent calls return the cached content

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

#### Scenario: save raises TaskRowNotFoundError for missing task_id
- **WHEN** `save(task)` is called with a `task_id` that does not exist in the database
- **THEN** `TaskRowNotFoundError` is raised BEFORE the task is appended to `_saved_tasks`

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

`insert(new_task: NewTask) -> Task` SHALL run `task/insert.sql ... RETURNING`
and return `_row_to_task(rows[0])` (the `NewTask.task_id` is
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
RETURNING) SHALL include the column set from `schema.sql`.
`update_by_id.sql`'s RETURNING SHALL include only `task_id` (the current
`save` does not refresh the in-memory `Task`; `updated_at` is observable via
the trigger on the next read).

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

The `get(ip)`, `get_by_ips`, and `add_tmp` methods are removed — node lookups
use `get_by_id` / `get_by_ids` only, and the tmp path uses `insert`.

#### Scenario: Row mapping wraps NodeId
- **WHEN** any node SELECT returns a row `{"node_id": 7, "ip": "[IP]", ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(7)`

### Requirement: All repository methods avoid blocking the event loop

All repository methods SHALL be async and dispatch synchronous pg8000 calls
through a `ThreadPoolExecutor` to avoid blocking the event loop.

#### Scenario: Async method does not block
- **WHEN** `get(task_id)` is called from an async context
- **THEN** the event loop is not blocked during the database call
