## Purpose

Integration tests for the DB persistence layer against a real PostgreSQL instance via testcontainers, validating SQL queries, parameter binding, and result mapping end-to-end without mocking pg8000.

## Requirements

### Requirement: PostgreSQL testcontainer fixture
The project SHALL provide a session-scoped pytest fixture that starts a PostgreSQL container via testcontainers, applies the schema using `apply_schema()` from `adapters/persistence/postgres_schema.py`, and yields a live `DB` instance.

#### Scenario: Fixture provides working DB
- **WHEN** an integration test uses the `db` fixture
- **THEN** a `DB` instance is available with schema applied via `apply_schema()` and `db.get_all_nodes()` returns an empty list

### Requirement: Per-test table cleanup
Each integration test SHALL start with empty `yascheduler_tasks` and `yascheduler_nodes` tables. A fixture SHALL TRUNCATE both tables between tests.

#### Scenario: Tests are isolated
- **WHEN** test A inserts a node and test B runs after test A
- **THEN** test B sees zero nodes

### Requirement: Node CRUD integration
Tests SHALL verify all node operations against real PostgreSQL: `add_node`, `get_node`, `get_all_nodes`, `get_enabled_nodes`, `get_disabled_nodes`, `has_node`, `enable_node`, `disable_node`, `remove_node`, `count_nodes_clouds`, `count_nodes_by_status`.

#### Scenario: Add, retrieve, enable/disable filtering
- **WHEN** two nodes are added (one enabled, one disabled)
- **THEN** `get_node` returns matching fields, `get_enabled_nodes()` returns one, `get_disabled_nodes()` returns one

### Requirement: Task CRUD integration
Tests SHALL verify task operations: `add_task`, `get_task`, `update_task_status`, `set_task_running`, `set_task_done`, `set_task_error`, `get_tasks_by_status`, `get_tasks_by_jobs`.

#### Scenario: Full task lifecycle
- **WHEN** `add_task` → `set_task_running` → `set_task_done` is executed
- **THEN** each step reflects the correct status and IP/metadata in `get_task`

#### Scenario: set_task_error embeds error
- **WHEN** `set_task_error(task_id, {"key": "val"}, "crash")`
- **THEN** `get_task` returns status DONE and metadata contains `{"key": "val", "error": "crash"}`

### Requirement: add_tmp_node integration
Tests SHALL verify `add_tmp_node` generates a provisional IP starting with "prov" and inserts a disabled node.

#### Scenario: Temporary node creation
- **WHEN** `db.add_tmp_node("az", "root")`
- **THEN** returned IP starts with "prov" and `get_node(ip)` shows `enabled=False, cloud="az"`

### Requirement: Migration idempotency
Tests SHALL verify that running `db.migrate()` twice does not raise an error.

#### Scenario: Double migration
- **WHEN** `migrate()` is called after `DB.create(automigrate=True)` already ran migration
- **THEN** no error is raised and tables remain functional

### Requirement: Yascheduler query path integration against PostgreSQL

The project SHALL provide an integration test that exercises
`Yascheduler.queue_get_tasks` and `queue_get_task` against a real
PostgreSQL instance via testcontainers. The test SHALL submit a real task
via `Yascheduler().queue_submit_task(...)`, then query it back via both
`jobs=[task_id]` and `status=[0]` filters. The test SHALL assert the
public Mapping shape (keys exactly `{task_id, label, ip, status, metadata,
cloud}`) and the expected values.

The test SHALL assert `status` by int value, by equality with a
`TaskStatus` member, or by `.name` — NEVER via
`isinstance(result["status"], db.TaskStatus)`, so that the test remains
valid across the legacy-DB / UoW implementation swap (the enum class
changes from `db.TaskStatus` to `domain.TaskStatus`).

The test SHALL NOT patch any internal collaborator (`yascheduler.db.DB`,
`yascheduler.di.make_cli_deps`, or otherwise). It exercises the full
facade path through real Postgres (characterization-first golden master).

#### Scenario: Query by jobs against real Postgres
- **WHEN** a task is submitted via `Yascheduler().queue_submit_task(...)` against the testcontainers Postgres and then `Yascheduler().queue_get_tasks(jobs=[task_id])` is called
- **THEN** the returned list contains one Mapping with exactly the six keys `{task_id, label, ip, status, metadata, cloud}`, `task_id` matches, and `status` equals the TO_DO int value (0) or `TaskStatus.TO_DO`

#### Scenario: Query by status against real Postgres
- **WHEN** the same task is queried via `Yascheduler().queue_get_tasks(status=[0])`
- **THEN** the task appears in the result with the correct six-key shape and matching `task_id`

#### Scenario: Single-task query returns Optional Mapping
- **WHEN** `Yascheduler().queue_get_task(task_id)` is called for an existing task
- **THEN** a single Mapping (not a list) with the six-key shape is returned; querying a non-existent id returns `None`

#### Scenario: Test asserts status without coupling to enum class
- **WHEN** the integration test's `status` assertion is inspected
- **THEN** it uses one of `int(result["status"])`, `result["status"] == 0`, `result["status"] == TaskStatus.TO_DO`, or `result["status"].name == "TO_DO"` — never `isinstance(result["status"], yascheduler.db.TaskStatus)`
