## ADDED Requirements

### Requirement: PostgreSQL testcontainer fixture
The project SHALL provide a session-scoped pytest fixture that starts a PostgreSQL container via testcontainers, applies the schema from `schema.sql`, and yields a live `DB` instance connected to it.

#### Scenario: Fixture provides working DB
- **WHEN** an integration test uses the `db` fixture
- **THEN** a `DB` instance is available with schema applied, and `db.get_all_nodes()` returns an empty list

### Requirement: Per-test table cleanup
Each integration test SHALL start with empty `yascheduler_tasks` and `yascheduler_nodes` tables. A fixture SHALL TRUNCATE both tables between tests.

#### Scenario: Tests are isolated
- **WHEN** test A inserts a node and test B runs after test A
- **THEN** test B sees zero nodes

### Requirement: Node CRUD integration
Tests SHALL verify all node operations against real PostgreSQL: `add_node`, `get_node`, `get_all_nodes`, `get_enabled_nodes`, `get_disabled_nodes`, `has_node`, `enable_node`, `disable_node`, `remove_node`, `count_nodes_clouds`, `count_nodes_by_status`.

#### Scenario: Add and retrieve node
- **WHEN** `db.add_node("10.0.0.1", "root", ncpus=4, enabled=True)` then `db.get_node("10.0.0.1")`
- **THEN** returned `NodeModel` matches all fields

#### Scenario: Enable/disable filtering
- **WHEN** two nodes are added (one enabled, one disabled)
- **THEN** `get_enabled_nodes()` returns one, `get_disabled_nodes()` returns one

#### Scenario: has_node correctness
- **WHEN** `has_node` is called for existing and non-existing IPs
- **THEN** returns True for existing, False for non-existing

#### Scenario: count_nodes_clouds aggregation
- **WHEN** nodes with cloud="az" and cloud="hetzner" are added
- **THEN** `count_nodes_clouds()` returns `{"az": N, "hetzner": M}`

### Requirement: Task CRUD integration
Tests SHALL verify task operations: `add_task`, `get_task`, `update_task_status`, `set_task_running`, `set_task_done`, `set_task_error`, `get_tasks_by_status`, `get_tasks_by_jobs`.

#### Scenario: Full task lifecycle
- **WHEN** `add_task` → `set_task_running` → `set_task_done` is executed
- **THEN** each step reflects the correct status and IP/metadata in `get_task`

#### Scenario: set_task_error embeds error
- **WHEN** `set_task_error(task_id, {"key": "val"}, "crash")`
- **THEN** `get_task` returns status DONE and metadata contains `{"key": "val", "error": "crash"}`

#### Scenario: get_tasks_by_status filtering
- **WHEN** tasks in TO_DO, RUNNING, and DONE states exist
- **THEN** `get_tasks_by_status([TaskStatus.RUNNING])` returns only RUNNING tasks

#### Scenario: get_tasks_by_jobs with array parameter
- **WHEN** tasks with IDs 1, 2, 3 exist and `get_tasks_by_jobs([1, 3])` is called
- **THEN** only tasks 1 and 3 are returned

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
