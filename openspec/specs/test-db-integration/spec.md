## Purpose

Integration tests for the persistence layer against a real PostgreSQL instance
via testcontainers, validating SQL queries, parameter binding, and result
mapping end-to-end without mocking pg8000. Tests use `PostgresUnitOfWork` +
repository adapters and `yascheduler.domain.TaskStatus`.

## Requirements

### Requirement: PostgreSQL testcontainer fixture
The project SHALL provide a session-scoped pytest fixture that starts a
PostgreSQL container via testcontainers and applies the schema using
`apply_schema` once per session. The project SHALL provide function-scoped
fixtures that yield the persistence primitives tests need: a raw pg8000
connection (`pg_conn`), a single-worker `ThreadPoolExecutor` (`pg_executor`),
and a `uow_factory` callable returning a `PostgresUnitOfWork`.

#### Scenario: Fixture provides working persistence primitives
- **WHEN** an integration test uses the `uow_factory` fixture inside `async with uow_factory() as uow:`
- **THEN** a `PostgresUnitOfWork` is available with schema applied and `await uow.nodes.list_all()` returns an empty list

#### Scenario: Raw connection fixture supports direct repo construction
- **WHEN** an integration test constructs `PostgresTaskRepository(pg_conn, pg_executor)`
- **THEN** the repository operates against the same testcontainer PostgreSQL instance

### Requirement: Per-test table cleanup
Each integration test SHALL start with empty `yascheduler_tasks` and
`yascheduler_nodes` tables. A fixture SHALL TRUNCATE both tables between tests
via the raw `pg_conn` fixture teardown (`TRUNCATE yascheduler_tasks,
yascheduler_nodes CASCADE`).

#### Scenario: Tests are isolated
- **WHEN** test A inserts a node and test B runs after test A
- **THEN** test B sees zero nodes

### Requirement: Node CRUD integration

Tests SHALL verify node operations against real PostgreSQL via
`PostgresNodeRepository` (through `uow.nodes`) and direct construction. The
covered operations are: `insert` (taking a `NewNode`, returning a `Node`),
`get_by_id`, `get_by_ids`, `list_all`, `list_enabled`, `list_disabled`,
`enable`, `disable`, `remove`, `count_by_cloud`, `count_by_status`. Tests
SHALL construct domain `NewNode` entities (`yascheduler.domain.NewNode`) and
assert the round-tripped `Node` fields.

#### Scenario: Insert, retrieve, enable/disable filtering
- **WHEN** two nodes are inserted (one enabled, one disabled) via `uow.nodes.insert(NewNode(hostname="[IP1]", enabled=True))` and `uow.nodes.insert(NewNode(hostname="[IP2]", enabled=False))`
- **THEN** `uow.nodes.get_by_id(node_id)` returns matching fields, `uow.nodes.list_enabled()` returns one, `uow.nodes.list_disabled()` returns one

### Requirement: Task CRUD integration

Tests SHALL verify task operations via `PostgresTaskRepository` (through
`uow.tasks`) using the domain `Task` / `NewTask` entities and
`yascheduler.domain.TaskStatus`: `insert`, `get`,
`update_status`, `save` (for lifecycle transitions),
`list_by_status`, `list_by_jobs`. Lifecycle transitions SHALL be expressed via
the domain `Task` methods operating on the typed fields directly, then
persisted via `uow.tasks.save`.

Tests SHALL construct `Task` / `NewTask` with the typed fields directly (no
`TaskContext(...)` wrapper, no `context=` kwarg). The `extra` JSONB column
(input-file payloads and unknown keys) SHALL be asserted to round-trip
through `insert` + `get` / `list_by_status` / `list_by_jobs`. The seven typed
columns (`engine`, `remote_folder`, `local_folder`, `webhook_url`, `error`,
`webhook_custom_params`, `extra`) SHALL be asserted to round-trip. `error` SHALL be asserted to persist the new format contract values (bare
strings set via `task.fail()` / `task.reject()`, `NULL` on success).

#### Scenario: Full task lifecycle
- **WHEN** a task transitions through the lifecycle (insert → running → done) via domain `Task` methods and is persisted via `uow.tasks.save`
- **THEN** each step reflects the correct status and typed fields (`engine`, `remote_folder`, `local_folder`, `error`, `extra`, `allocated_node_id`) in `uow.tasks.get`

#### Scenario: Task error column embeds error string
- **WHEN** a task is saved with `task.error="crash"` (via `task.fail("crash")` or `task.reject("crash")`) and status DONE
- **THEN** `uow.tasks.get(id)` returns status DONE and the row's `error` column equals `"crash"` (the typed column carries the error string directly; no `metadata` JSONB serialization)

#### Scenario: extra JSONB round-trips
- **WHEN** a task is saved with `extra={"input.in": "ATOMS", "input.xyz": "..."}` and retrieved via `uow.tasks.get(id)`
- **THEN** the retrieved task's `extra` equals `{"input.in": "ATOMS", "input.xyz": "..."}` (the `extra` JSONB column round-trips; pg8000 adapts `dict` ↔ JSONB natively)

#### Scenario: typed columns round-trip
- **WHEN** a task is saved with `engine="cp2k"`, `remote_folder="/r"`, `local_folder="/l"`, `webhook_url="https://..."`, `webhook_custom_params={"k": "v"}`, `error=None`, `extra={}` and retrieved
- **THEN** the retrieved task has the same values for all seven typed columns; `error` is `None` (NULL in the DB)

### Requirement: Yascheduler query path integration against PostgreSQL

The project SHALL provide an integration test that exercises
`Yascheduler.queue_get_tasks` and `queue_get_task` against a real
PostgreSQL instance via testcontainers. The test SHALL submit a real task
via `Yascheduler().queue_submit_task(...)`, then query it back via both
`jobs=[task_id]` and `status=[0]` filters. The test SHALL assert the
public Mapping shape (keys exactly `{task_id, label, status, metadata,
node}`) and the expected values.

The test SHALL assert `status` by int value, by equality with a
`yascheduler.domain.TaskStatus` member, or by `.name`. The canonical
status type is `yascheduler.domain.TaskStatus`.

The test SHALL NOT patch any internal collaborator. It exercises the full
facade path through real Postgres.

#### Scenario: Query by jobs against real Postgres
- **WHEN** a task is submitted via `Yascheduler().queue_submit_task(...)` against the testcontainers Postgres and then `Yascheduler().queue_get_tasks(jobs=[task_id])` is called
- **THEN** the returned list contains one Mapping with exactly the five keys `{task_id, label, status, metadata, node}`, `task_id` matches, and `status` equals the TO_DO int value (0) or `domain.TaskStatus.TO_DO`

#### Scenario: Query by status against real Postgres
- **WHEN** the same task is queried via `Yascheduler().queue_get_tasks(status=[0])`
- **THEN** the task appears in the result with the correct five-key shape and matching `task_id`

#### Scenario: Single-task query returns Optional Mapping
- **WHEN** `Yascheduler().queue_get_task(task_id)` is called for an existing task
- **THEN** a single Mapping (not a list) with the five-key shape is returned; querying a non-existent id returns `None`

