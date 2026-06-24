## Purpose

Integration tests for the persistence layer against a real PostgreSQL instance via testcontainers, validating SQL queries, parameter binding, and result mapping end-to-end without mocking pg8000. Tests use `PostgresUnitOfWork` + repository adapters and `yascheduler.domain.TaskStatus` (not the removed `yascheduler.db`).

## Requirements

### Requirement: PostgreSQL testcontainer fixture
The project SHALL provide a session-scoped pytest fixture that starts a
PostgreSQL container via testcontainers and applies the schema using
`apply_schema()` from `infra/persistence/postgres_schema.py` once per
session. The project SHALL provide function-scoped fixtures that yield the
persistence primitives tests need: a raw `pg8000.native.Connection`
(`pg_conn`), a single-worker `ThreadPoolExecutor` (`pg_executor`), and a
`uow_factory` callable returning a `PostgresUnitOfWork` constructed with
`_db_config` and a bare `MessageBus()`. Tests SHALL NOT receive a `DB`
instance (the class is removed).

#### Scenario: Fixture provides working persistence primitives
- **WHEN** an integration test uses the `uow_factory` fixture inside `async with uow_factory() as uow:`
- **THEN** a `PostgresUnitOfWork` is available with schema applied via `apply_schema()` and `await uow.nodes.list_all()` returns an empty list

#### Scenario: Raw connection fixture supports direct repo construction
- **WHEN** an integration test constructs `PostgresTaskRepository(pg_conn, pg_executor)`
- **THEN** the repository operates against the same testcontainer PostgreSQL instance

### Requirement: Per-test table cleanup
Each integration test SHALL start with empty `yascheduler_tasks` and
`yascheduler_nodes` tables. A fixture SHALL TRUNCATE both tables between tests
via the raw `pg_conn` fixture teardown (`TRUNCATE yascheduler_tasks,
yascheduler_nodes CASCADE`), independent of any `DB.run` method.

#### Scenario: Tests are isolated
- **WHEN** test A inserts a node and test B runs after test A
- **THEN** test B sees zero nodes

### Requirement: Node CRUD integration
Tests SHALL verify node operations against real PostgreSQL via
`PostgresNodeRepository` (through `uow.nodes`) and direct construction:
`add` (`Node`), `get`, `list_all`, `list_enabled`, `list_disabled`, `get`
(for `has_node` semantics), `enable`, `disable`, `remove`, `count_by_cloud`,
`count_by_status`, `get_by_ips`. Tests SHALL construct domain `Node`
entities (`yascheduler.domain.Node`) with the appropriate fields rather than
the deleted `NodeModel`.

#### Scenario: Add, retrieve, enable/disable filtering
- **WHEN** two nodes are added (one enabled, one disabled) via `uow.nodes.add(Node(...))`
- **THEN** `uow.nodes.get(ip)` returns matching fields, `uow.nodes.list_enabled()` returns one, `uow.nodes.list_disabled()` returns one

### Requirement: Task CRUD integration
Tests SHALL verify task operations via `PostgresTaskRepository` (through
`uow.tasks`) using domain `Task` and `TaskContext` entities and
`yascheduler.domain.TaskStatus`: `insert`, `get`, `update_status`,
`save` (for set_running / set_done / set_error transitions),
`list_by_status`, `list_by_jobs`. Lifecycle transitions SHALL be expressed via
the domain `Task` methods (`allocate_to`, `mark_running`, `complete`, `fail`)
and `TaskContext` reconstruction, then persisted via `uow.tasks.save`.

#### Scenario: Full task lifecycle
- **WHEN** `insert` → `save(task.allocate_to(ip).mark_running())` → `save` with DONE status and updated context is executed
- **THEN** each step reflects the correct status and `allocated_ip`/context in `uow.tasks.get`

#### Scenario: set_task_error embeds error
- **WHEN** a task is saved with a `TaskContext` whose `error="crash"` field is set and status DONE
- **THEN** `uow.tasks.get(id)` returns status DONE and the context serializes `error` into metadata
### Requirement: add_tmp_node integration

Tests SHALL verify `PostgresNodeRepository.add_tmp(cloud)` generates a
provisional IP starting with "prov" and inserts a disabled node. The
`username` column falls back to its DB default (`'root'`); the test SHALL
NOT pass a `username` argument and SHALL NOT assert a caller-supplied
username on the retrieved row.

#### Scenario: Temporary node creation
- **WHEN** `uow.nodes.add_tmp("az")` is called
- **THEN** the returned IP starts with "prov" and `uow.nodes.get(ip)` shows `enabled=False, cloud="az", username="root"` (the DB default)

### Requirement: Yascheduler query path integration against PostgreSQL

The project SHALL provide an integration test that exercises
`Yascheduler.queue_get_tasks` and `queue_get_task` against a real
PostgreSQL instance via testcontainers. The test SHALL submit a real task
via `Yascheduler().queue_submit_task(...)`, then query it back via both
`jobs=[task_id]` and `status=[0]` filters. The test SHALL assert the
public Mapping shape (keys exactly `{task_id, label, ip, status, metadata,
cloud}`) and the expected values.

The test SHALL assert `status` by int value, by equality with a
`yascheduler.domain.TaskStatus` member, or by `.name` — NEVER via
`isinstance(result["status"], yascheduler.db.TaskStatus)` (the legacy enum
class is removed). The canonical status type is
`yascheduler.domain.TaskStatus`.

The test SHALL NOT patch any internal collaborator (`yascheduler.di.make_cli_deps`
or otherwise). It exercises the full facade path through real Postgres
(characterization-first golden master).

#### Scenario: Query by jobs against real Postgres
- **WHEN** a task is submitted via `Yascheduler().queue_submit_task(...)` against the testcontainers Postgres and then `Yascheduler().queue_get_tasks(jobs=[task_id])` is called
- **THEN** the returned list contains one Mapping with exactly the six keys `{task_id, label, ip, status, metadata, cloud}`, `task_id` matches, and `status` equals the TO_DO int value (0) or `domain.TaskStatus.TO_DO`

#### Scenario: Query by status against real Postgres
- **WHEN** the same task is queried via `Yascheduler().queue_get_tasks(status=[0])`
- **THEN** the task appears in the result with the correct six-key shape and matching `task_id`

#### Scenario: Single-task query returns Optional Mapping
- **WHEN** `Yascheduler().queue_get_task(task_id)` is called for an existing task
- **THEN** a single Mapping (not a list) with the six-key shape is returned; querying a non-existent id returns `None`

#### Scenario: Test asserts status against domain.TaskStatus
- **WHEN** the integration test's `status` assertion is inspected
- **THEN** it uses one of `int(result["status"])`, `result["status"] == 0`, `result["status"] == domain.TaskStatus.TO_DO`, or `result["status"].name == "TO_DO"` — never `isinstance(result["status"], yascheduler.db.TaskStatus)`
