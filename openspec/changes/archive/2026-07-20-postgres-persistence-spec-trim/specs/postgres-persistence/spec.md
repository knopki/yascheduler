# Delta: postgres-persistence

## MODIFIED Requirements

### Requirement: SQL file layout

The system SHALL keep task SQL in versioned `.sql` files under
`infra/persistence/sql/task/` loaded by `load_query(name)` with `@cache`
caching. The task SQL files SHALL be exactly: `insert` (RETURNING),
`update_by_id`, `get_by_id`, `list_by_status`, `list_by_jobs`,
`update_status`, `get_ids_by_node_id_and_status`, `count_by_status`.

The system SHALL keep node SQL in versioned `.sql` files under
`infra/persistence/sql/node/` loaded by the same `load_query(name)` cache.
The node SQL files SHALL be exactly: `insert`, `update`, `get_by_id`,
`get_by_ids`, `list_all`, `list_enabled`, `list_disabled`, `enable`,
`disable`, `remove`, `count_by_cloud`, `count_by_status`.

The schema DDL snapshot and migration file format are owned by the
`postgres-schema-apply` and `db-migrations` capabilities respectively and
are not restated here.

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

- **WHEN** `uow.tasks` / `uow.nodes` / `uow.commit()` / `uow.rollback()` is accessed without entering the context (or after exit)
- **THEN** `UnitOfWorkNotInitializedError` is raised; `isinstance(exc, RuntimeError)` is `True`

#### Scenario: Connection closed after use

- **WHEN** `async with uow: ...` completes (success or failure)
- **THEN** the underlying pg8000 connection is closed

### Requirement: Task repository write semantics

`save(task: Task)` and `update_status(task_id: TaskId, status: TaskStatus)` SHALL
execute `UPDATE ... WHERE task_id = :task_id ... RETURNING task_id`. When the
UPDATE affects 0 rows (the `task_id` does not exist), they SHALL raise
`TaskRowNotFoundError` (a `RuntimeError` subclass taking `task_id: TaskId`).
`save` SHALL raise BEFORE the task is tracked for event collection, so a
raise never leaves an orphan task that `publish_events` would later dispatch
for.

`insert(new_task: NewTask) -> Task` SHALL run INSERT with RETURNING and
return the materialized `Task` produced by the domain-layer
`materialize_task` function (see the `domain-entities` capability), which
attaches the `TaskCreated` event to the returned `Task`'s `events` field.

Row mapping in `get`, `list_by_jobs`, `list_by_status`, and `insert`'s
RETURNING SHALL construct `TaskId` / `NodeId` / `TaskStatus` / `datetime`
values from the row at the boundary.

#### Scenario: save raises TaskRowNotFoundError for missing task_id

- **WHEN** `save(task)` is called with a `task_id` that does not exist in the database
- **THEN** `TaskRowNotFoundError` is raised BEFORE the task is tracked for event collection

#### Scenario: insert returns Task with TaskCreated via materialize_task

- **WHEN** `insert(new_task)` is called with a valid `NewTask`
- **THEN** the returned `Task` has the DB-generated `task_id`, `status=TO_DO`, `allocated_node_id=None`, `remote_folder=None`, `error=None`, and `events` containing one `TaskCreated` event (attached by `materialize_task`)

#### Scenario: Task rows always materialize with empty events

- **WHEN** any DB row is mapped to a `Task`
- **THEN** the returned `Task` has `events=()` (events are transient; only `insert` via `materialize_task` attaches `TaskCreated`)

### Requirement: PostgresNodeRepository implements NodeRepository

`PostgresNodeRepository` SHALL satisfy the `NodeRepository` Protocol with
async methods `get_by_id`, `get_by_ids`, `list_enabled`, `list_disabled`,
`list_all`, `insert`, `update`, `enable`, `disable`, `remove`,
`count_by_cloud`, `count_by_status`.

`insert(new_node: NewNode) -> Node` SHALL run INSERT with RETURNING
`node_id` and return a `Node` carrying the generated `NodeId`. The tmp-node
reservation flow SHALL use `insert` with a `NewNode` whose `enabled=False`.

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
