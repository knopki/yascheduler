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

The system SHALL keep task SQL in versioned files loaded via a cached query
loader. SQL query files follow the column set defined in the schema DDL.

- The schema DDL — the full latest snapshot (every `CREATE TABLE` includes all
  current columns; no inline `ALTER`s). The DO block's `last_migration`
  CONSTANT is the single manual edit point when a migration is added.
- Migration files — forward-only migration files (`{prefix_id}_{rest}.sql`
  or `.py`), applied by `apply_migrations` in string-sorted `prefix_id` order.
- Task SQL includes: insert (RETURNING), update_by_id, get_by_id,
  list_by_status, list_by_jobs, update_status, get_ids_by_node_id_and_status,
  count_by_status.
- `update_meta` SQL is deleted (dead path removed).

#### Scenario: SQL files loaded via load_query
- **WHEN** a task SQL file is requested
- **THEN** the content is returned; subsequent calls return the cached content

### Requirement: PostgresUnitOfWork transactional boundaries

`PostgresUnitOfWork` SHALL manage a shared pg8000 connection across
`PostgresTaskRepository` and `PostgresNodeRepository` with commit/rollback
semantics, satisfying the `AbstractUnitOfWork` Protocol. It SHALL be
constructed from a `PostgresDbConfig`, creating a fresh connection on each
context entry, and SHALL close the connection on context exit regardless of
success or failure.

Accessing `tasks` / `nodes`, or calling `commit()` / `rollback()` without
entering the `async with` context SHALL raise
`UnitOfWorkNotInitializedError` (a `RuntimeError` subclass).

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
`TaskRowNotFoundError` (a `RuntimeError` subclass taking `task_id: TaskId`).
The row-existence check SHALL happen BEFORE the task is tracked for event
collection, so a raise never leaves an orphan task that `publish_events` would
later dispatch for.

#### Scenario: save raises TaskRowNotFoundError for missing task_id
- **WHEN** `save(task)` is called with a `task_id` that does not exist in the database
- **THEN** `TaskRowNotFoundError` is raised BEFORE the task is tracked for event collection

`save(task)` SHALL bind `node_id=task.allocated_node_id.value` (or `None` when
`task.allocated_node_id is None`) as the pg8000 named parameter for the
`allocated_node_id` column, alongside `title` (the DB column name for the
domain `label` field), `status` (the `task.status.name` string), `engine`,
`remote_folder`, `local_folder`, `webhook_url`, `error`, `webhook_custom_params`,
`extra` in the UPDATE. The SQL SHALL SET all of these columns. The SQL SHALL
NOT set `ip` (dropped) and SHALL NOT set `updated_at` (the `BEFORE UPDATE`
trigger sets it). `webhook_custom_params` and `extra` are bound as the dict
values from `task.webhook_custom_params` / `task.extra` (pg8000 adapts `dict`
to JSONB natively; no `json.dumps` at the call site).

`insert(new_task: NewTask) -> Task` SHALL run INSERT with RETURNING and return
the materialized `Task` (the `NewTask.task_id` is ignored — none exists; the DB
generates it), avoiding a second `get` round-trip. The domain-layer
`materialize_task` function (see the `domain-entities` capability) attaches the
`TaskCreated` event to the returned `Task`'s `events` field. The infrastructure
layer SHALL NOT import `TaskCreated` directly; `materialize_task` owns event
construction in the domain layer. `insert` SHALL bind `node_id=None` as the
pg8000 named parameter for the `allocated_node_id` column (a freshly inserted
TO_DO task is unallocated), alongside `title` (carrying `new_task.label`),
`engine`, `local_folder`, `webhook_url`, `webhook_custom_params`, `extra`,
`status` (`TaskStatus.TO_DO.name`). `NewTask` carries no `allocated_node_id`
and no `status`; `insert` binds `None` and `TaskStatus.TO_DO.name` as
constants. `remote_folder` and `error` are NOT on `NewTask`; they are bound as
`None` (the column is nullable; the DB stores NULL until `run` sets
`remote_folder` and `reject`/`fail`/`abandon` sets `error` on a subsequent
`save`). `created_at`/`updated_at` are NOT bound — the DB `DEFAULT NOW()`
populates them on insert, and they are read back via `RETURNING`.

Row mapping in `get`, `list_by_jobs`, `list_ids_by_node_id_and_status` SHALL
wrap `TaskId(int(row["task_id"]))` / `task_id.value` at the boundary.
`allocated_node_id` SHALL be read from the row and construct
`NodeId(int(row["allocated_node_id"]))` when `row["allocated_node_id"]` is not
None, else `allocated_node_id=None`. `created_at` and `updated_at` SHALL be
read from the row (pg8000 returns `datetime` for `TIMESTAMPTZ` columns).
`status` SHALL be read as a Python `str` (the enum label) and construct the
domain enum via `TaskStatus[row["status"]]` (name lookup). `title` SHALL be
read and mapped to the `label` field of `Task`. The seven typed columns
(`engine`, `remote_folder`, `local_folder`, `webhook_url`, `error`,
`webhook_custom_params`, `extra`) SHALL be read directly from the row and
assigned to the corresponding `Task` fields. `webhook_custom_params` and `extra`
arrive as Python `dict` (pg8000 adapts JSONB to `dict` natively); if pg8000
returns them as a `str`, the row mapping SHALL `json.loads` them (defensive —
pg8000's JSONB adaptation normally returns `dict`, but a str fallback path is
preserved). The row mapping SHALL NOT read a `metadata` column (the column is
dropped). The row mapping SHALL NOT construct a `TaskContext` (the value object
is removed). The row mapping SHALL always set `events=()` (events are transient;
the DB has no events column). The 4 SQL files that return task rows
(`get_by_id`, `list_by_status`, `list_by_jobs`, `insert`'s RETURNING) SHALL
include the full column set from the schema. `update_by_id`'s RETURNING SHALL
include only `task_id` (the current `save` does not refresh the in-memory
`Task`; `updated_at` is observable via the trigger on the next read).

#### Scenario: insert returns Task with TaskCreated via materialize_task
- **WHEN** `insert(new_task)` is called with a valid `NewTask`
- **THEN** the returned `Task` has the DB-generated `task_id`, `status=TO_DO`, `allocated_node_id=None`, `remote_folder=None`, `error=None`, and `events` containing one `TaskCreated` event (attached by `materialize_task`)

#### Scenario: Task rows always materialize with empty events
- **WHEN** any DB row is mapped to a `Task`
- **THEN** the returned `Task` has `events=()` (events are transient; only `insert` via `materialize_task` attaches `TaskCreated`)

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with async
methods `get_by_id`, `get_by_ids`, `list_enabled`, `list_disabled`, `list_all`,
`insert`, `update`, `enable`, `disable`, `remove`, `count_by_cloud`,
`count_by_status`. The hostname-keyed methods `get(ip: str)` and `get_by_ips(ips:
list[str])` are REMOVED. `add_tmp` is **removed** — there is no `add_tmp`
method; the tmp-reservation flow uses `insert`.

`insert(new_node: NewNode) -> Node` SHALL run INSERT with RETURNING
`node_id` and return a `Node` carrying the generated `NodeId`. When called with
`NewNode(cloud=..., enabled=False)` (the tmp-reservation path, with `hostname=""`
and `ncpus=0` defaults from `NewNode`), it SHALL insert a row with
`hostname=""`, `enabled=FALSE`, the given `cloud`, and `username`/`port` from the
`NewNode` defaults (`"root"`, `22`). The returned `Node` carries the generated
`node_id`, which is the tmp-node cleanup handle AND the real-node identity
reused by `clouds.allocate`. `get_by_id(node_id: NodeId)` SHALL run
`WHERE node_id = :node_id`, passing `node_id.value`.
`get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]` SHALL run
`WHERE node_id = ANY(:node_ids)`, passing
`[n.value for n in node_ids]` as the SQL param, and return a dict keyed by
`NodeId` (constructed from each row's `node_id`). Node row mapping SHALL read
`node_id` from every node row and construct `NodeId(int(row["node_id"]))`.

`list_all()` SHALL return nodes ordered by `node_id` ascending (the SQL
includes `ORDER BY node_id`); it returns ALL rows regardless of `enabled` or
`hostname` (including tmp rows with `hostname=""`), because the allocator counts
tmp rows toward `max_nodes` capacity.

`list_enabled()` SHALL filter `WHERE enabled = TRUE` with **no python
post-filter**.

`list_disabled()` SHALL filter `WHERE enabled = FALSE AND hostname <> ''`.

`enable(node_id: NodeId)`, `disable(node_id: NodeId)`, and
`remove(node_id: NodeId)` SHALL run with `WHERE node_id = :node_id`, binding
`node_id.value` as the SQL parameter.

`update(node: Node)` SHALL run with `WHERE node_id = :node_id`, binding
`node.node_id.value` as the key parameter alongside the field params
(`hostname`, `ncpus`, `enabled`, `cloud`, `username`, `port`, `jump_host`,
`jump_port`, `jump_username`, `external_id`, `status`). The `hostname` field
MUST be in the `SET` clause — the V1 cloud-allocation lifecycle relies on
`update` to flip the tmp row's `hostname` from `""` (the NewNode default) to
the real VM hostname in a single `UPDATE`; an `update` without `hostname` in
`SET` would leave cloud nodes unreachable after daemon restart and excluded
from `list_disabled`'s `WHERE hostname <> ''` filter (VM leak).

Node row mapping SHALL map `hostname=row["hostname"]` unchanged; `""` is a
valid `str` and the mapping works without changes. Row mapping SHALL also read
`created_at`, `updated_at`, `jump_host`, `jump_port`, `jump_username`,
`external_id`, and `status` (converting the `NODE_STATUS` label string to
`NodeStatus[row["status"]]`).

`count_by_status.sql` SHALL use `COUNT(node_id)` (not `COUNT(hostname)` or
`COUNT(*)`).

The `get(ip)`, `get_by_ips`, and `add_tmp` methods are removed — node lookups
use `get_by_id` / `get_by_ids` only, and the tmp path uses `insert`.

#### Scenario: Row mapping wraps NodeId
- **WHEN** any node SELECT returns a row `{"node_id": 7, "hostname": "[IP]", ...}`
- **THEN** the mapped `Node` has `node_id == NodeId(7)`

#### Scenario: Row mapping reads created_at and updated_at
- **WHEN** a node SELECT returns a row with `created_at` and `updated_at` columns
- **THEN** the mapped `Node` carries `created_at` and `updated_at` as `datetime` values

#### Scenario: Row mapping reads status as NodeStatus
- **WHEN** a node SELECT returns a row with `status = "OTHER"`
- **THEN** the mapped `Node` has `status == NodeStatus.OTHER`

### Requirement: All repository methods avoid blocking the event loop

All repository methods SHALL be async and dispatch synchronous pg8000 calls
through a `ThreadPoolExecutor` to avoid blocking the event loop.

#### Scenario: Async method does not block
- **WHEN** `get(task_id)` is called from an async context
- **THEN** the event loop is not blocked during the database call
