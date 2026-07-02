# PostgreSQL Persistence

## Purpose

PostgreSQL-backed persistence adapter: `PostgresUnitOfWork` (transaction
boundaries, connection lifecycle), `PostgresTaskRepository` /
`PostgresNodeRepository` (satisfying the domain ports), the SQL file layout and
`load_query` caching, and the `TaskRowNotFoundError` /
`UnitOfWorkNotInitializedError` persistence exceptions. Built on pg8000 with all
synchronous calls dispatched through a `ThreadPoolExecutor`.

## Requirements

### Requirement: SQL file layout and lazy loading

The system SHALL store all SQL queries in `infra/persistence/sql/` organized as
`sql/<entity>/<operation>.sql`, loaded via `load_query(name: str) -> str` which
reads the file from the package directory and caches the result (each file read
at most once per process).

- `sql/task/update_by_id.sql` — `UPDATE yascheduler_tasks SET ... WHERE task_id = :task_id ... RETURNING task_id` (partial update keyed by `task_id`; NOT an upsert).
- `sql/task/update_status.sql` — includes `RETURNING task_id` so the repository detects a 0-row outcome.
- `sql/task/insert.sql` — `... RETURNING task_id, label, ip, status, metadata`.
- `sql/node/insert.sql` — `INSERT ... VALUES (...) RETURNING node_id`.
- `sql/node/get_by_id.sql` — `WHERE node_id = :node_id`.
- `sql/node/list_all.sql` — includes `ORDER BY node_id` (deterministic CLI output).
- `sql/node/enable.sql` — `UPDATE yascheduler_nodes SET enabled=TRUE WHERE node_id = :node_id`.
- `sql/node/disable.sql` — `UPDATE yascheduler_nodes SET enabled=FALSE WHERE node_id = :node_id`.
- `sql/node/remove.sql` — `DELETE FROM yascheduler_nodes WHERE node_id = :node_id`.
- `sql/node/update.sql` — `UPDATE yascheduler_nodes SET ... WHERE node_id = :node_id`.
- Every node SELECT (`get_by_ip`, `list_all`, `get_by_ips`, `list_enabled`, `list_disabled`, `get_by_id`) SHALL include `node_id` in its column list.

SQL files SHALL use `:param_name` syntax for pg8000 named-parameter binding.

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

`insert(new_task: NewTask) -> Task` SHALL run `task/insert.sql ... RETURNING
task_id, label, ip, status, metadata` and return `_row_to_task(rows[0])` (the
`NewTask.task_id` is ignored — none exists; the DB generates it), avoiding a
second `get` round-trip. `get`, `_row_to_task`, `list_by_jobs`,
`list_ids_by_ip_and_status` SHALL wrap `TaskId(int(row["task_id"]))` /
`task_id.value` at the boundary.

#### Scenario: Get non-existent task
- **WHEN** `get(TaskId(999))` is called and no such row exists
- **THEN** returns `None`

#### Scenario: Save non-existent task raises
- **WHEN** `save(task)` is called with a `task.task_id` that does not exist
- **THEN** `TaskRowNotFoundError` is raised (carrying the `TaskId`) and the task is NOT appended to `_saved_tasks`

#### Scenario: Insert returns Task with generated TaskId
- **WHEN** `insert(NewTask(label="job", context=ctx))` is called
- **THEN** a `Task` with the DB-generated `task_id=TaskId(int(row["task_id"]))` is returned

#### Scenario: Update status non-existent task raises
- **WHEN** `update_status(TaskId(999), TaskStatus.RUNNING)` is called and no row with task_id=999 exists
- **THEN** `TaskRowNotFoundError` is raised (carrying `TaskId(999)`)

#### Scenario: List IDs by IP and status returns TaskIds
- **WHEN** `list_ids_by_ip_and_status("10.0.0.1", TaskStatus.RUNNING)` is called
- **THEN** returns a `list[TaskId]` (each `TaskId(int(row["task_id"]))`), NOT a `list[int]`

#### Scenario: _row_to_task wraps TaskId
- **WHEN** `_row_to_task(row)` is called with a row whose `task_id` is the int `7`
- **THEN** the returned `Task` has `task_id=TaskId(7)`

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with async
methods `get`, `get_by_id`, `list_enabled`, `list_disabled`, `list_all`,
`insert`, `update`, `enable`, `disable`, `remove`, `get_by_ips`,
`count_by_cloud`, `count_by_status`. `add_tmp` is **removed** — there is no
`add_tmp` method; the tmp-reservation flow uses `insert`.

`insert(new_node: NewNode) -> Node` SHALL run `node/insert.sql` with `RETURNING
node_id` and return a `Node` carrying the generated `NodeId`. When called with
`NewNode(cloud=..., enabled=False)` (the tmp-reservation path, with `ip=""`
and `ncpus=0` defaults from `NewNode`), it SHALL insert a row with
`ip=""`, `enabled=FALSE`, the given `cloud`, and `username`/`port` from the
`NewNode` defaults (`"root"`, `22`). The returned `Node` carries the generated
`node_id`, which is the tmp-node cleanup handle. `get_by_id(node_id: NodeId)`
SHALL run `node/get_by_id.sql` (`WHERE node_id = :node_id`), passing
`node_id.value`. `_row_to_node` SHALL read `node_id` from every node row and
construct `NodeId(int(row["node_id"]))`.

`list_all()` SHALL return nodes ordered by `node_id` ascending (the SQL
includes `ORDER BY node_id`); it returns ALL rows regardless of `enabled` or
`ip` (including tmp rows with `ip=""`), because `_count_nodes_by_cloud` in
`allocate_task` counts tmp rows toward `max_nodes` capacity.

`list_enabled()` SHALL run `node/list_enabled.sql` (`WHERE enabled = TRUE`)
with **no python post-filter**. By the invariant (after this change,
`ip == ''` IFF `enabled = FALSE` AND the node is tmp/pending), no enabled row
has `ip=""`, so the prior `"." in r["ip"]` post-filter was dead code and is
removed.

`list_disabled()` SHALL run `node/list_disabled.sql`
(`WHERE enabled = FALSE AND ip <> ''`). The `ip <> ''` predicate is a
**presence check** (this disabled row has a real address → it is a
real-disabled VM with a VM to delete, not a tmp/pending row), not a format
check. The prior python `"." in r["ip"]` post-filter is removed. Callers
outside `allocate_task` (e.g. `deallocate_nodes.py`) retain their own
caller-side `"." in node.ip` post-filters; those are out of scope and remain
correct (redundant for `ip=""` rows now excluded by SQL, still filtering
non-ipv4 hostnames).

`enable(node_id: NodeId)`, `disable(node_id: NodeId)`, and
`remove(node_id: NodeId)` SHALL run `node/{enable,disable,remove}.sql` with
`WHERE node_id = :node_id`, binding `node_id.value` as the SQL parameter
(pg8000 cannot adapt a `NodeId` dataclass — same pattern as `get_by_id`).

`update(node: Node)` SHALL run `node/update.sql` with `WHERE node_id = :node_id`,
binding `node.node_id.value` as the key parameter alongside the field params
(`ncpus`, `enabled`, `cloud`, `username`, `port`).

`_row_to_node` SHALL map `ip=row["ip"]` unchanged; `""` is a valid `str` and
the mapping works without changes.

#### Scenario: Insert returns Node with generated id
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned with `node_id == NodeId(<generated>)` and matching non-id fields

#### Scenario: Get by id returns None when missing
- **WHEN** `get_by_id(NodeId(999))` is called and no row matches
- **THEN** returns `None`; the SQL parameter is bound as `node_id.value` (the bare int)

#### Scenario: Row mapping wraps NodeId
- **WHEN** any node SELECT returns a row `{"node_id": 7, "ip": "10.0.0.1", ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(7)`

#### Scenario: List all is ordered by node_id and includes tmp rows
- **WHEN** `list_all()` is called on a DB with a mix of enabled, disabled, and tmp (`ip=""`) rows
- **THEN** returns all rows (including `ip=""` tmp rows) ordered by `node_id` ascending

#### Scenario: List enabled has no python post-filter
- **WHEN** `list_enabled()` is called on a DB with enabled real nodes and disabled tmp rows (`ip=""`)
- **THEN** returns only `enabled=TRUE` rows (the SQL `WHERE enabled = TRUE` is the only filter); no python post-filter runs (the prior `"." in r["ip"]` is removed); by the invariant no enabled row has `ip=""`

#### Scenario: List disabled filters empty-ip rows in SQL
- **WHEN** `list_disabled()` is called on a DB with real-disabled VMs (`ip<>""`) and tmp rows (`ip=""`)
- **THEN** returns only disabled rows with `ip <> ""` (the SQL `WHERE enabled = FALSE AND ip <> ''` is the filter); no python post-filter runs (the prior `"." in r["ip"]` is removed); the `ip <> ''` is a presence check, not a format check

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
- **THEN** a row is inserted with `ip=""`, `enabled=FALSE`, `cloud="aws"`, `username="root"`, `port=22`; a `Node` is returned carrying the generated `node_id` (the tmp-node cleanup handle)

#### Scenario: Row mapping handles empty-string ip
- **WHEN** a node SELECT returns a row `{"node_id": 12, "ip": "", "enabled": false, ...}`
- **THEN** `_row_to_node` returns a `Node` with `node_id == NodeId(12)`, `ip == ""`, `enabled == False` (the `""` is a valid `str`, no mapping change)

#### Scenario: No add_tmp method
- **WHEN** `PostgresNodeRepository` is inspected for `add_tmp`
- **THEN** no `add_tmp` method is defined; the tmp path uses `insert`; `node/insert_tmp.sql` is removed from the SQL file layout

### Requirement: JSONB metadata roundtrip

The system SHALL serialize `TaskContext` to/from JSONB correctly for all known
fields (`engine`, `remote_folder`, `local_folder`, `webhook_url`,
`webhook_custom_params`, `error`) and preserve unknown keys in `extra`. Known
`None` values are omitted on serialization; on deserialization keys not matching
known fields populate `extra`.

#### Scenario: Roundtrip preserves extra
- **WHEN** a `TaskContext` with `extra={"fort.9": "data"}` is saved and retrieved
- **THEN** `extra["fort.9"]` is preserved

### Requirement: All repository methods avoid blocking the event loop

All repository methods SHALL be async and dispatch synchronous pg8000 calls
through a `ThreadPoolExecutor` to avoid blocking the event loop.

#### Scenario: Async method does not block
- **WHEN** `get(task_id)` is called from an async context
- **THEN** the event loop is not blocked during the database call
