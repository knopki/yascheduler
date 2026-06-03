## 1. Integration Test Infrastructure

- [x] 1.1 Create `tests/integration/conftest.py` with a session-scoped `postgres_container` fixture using `testcontainers.postgres.PostgresContainer("postgres:16-alpine")`
- [x] 1.2 Add a session-scoped `db` fixture that parses the container connection URL into `ConfigDb`, calls `DB.create()`, applies `schema.sql`, and runs `migrate()`
- [x] 1.3 Add an autouse `clean_tables` fixture that TRUNCATES both tables after each test
## 2. Node CRUD Integration Tests

- [x] 2.1 Create `tests/integration/test_db_integration.py` with tests for `add_node` + `get_node` (verify all fields round-trip)
- [x] 2.2 Add tests for `get_all_nodes`, `get_enabled_nodes`, `get_disabled_nodes` (enabled/disabled filtering)
- [x] 2.3 Add tests for `has_node` (existing and non-existing IP)
- [x] 2.4 Add tests for `enable_node` / `disable_node` (status toggling)
- [x] 2.5 Add tests for `remove_node` (node is gone after removal)
- [x] 2.6 Add tests for `count_nodes_clouds` and `count_nodes_by_status` (aggregation)

## 3. Task CRUD Integration Tests

- [x] 3.1 Add tests for `add_task` + `get_task` (verify all fields including metadata)
- [x] 3.2 Add tests for full task lifecycle: `add_task` → `set_task_running` → `set_task_done` (status and IP transitions)
- [x] 3.3 Add tests for `set_task_error` (with and without error message)
- [x] 3.4 Add tests for `get_tasks_by_status` (filtering across multiple statuses)
- [x] 3.5 Add tests for `get_tasks_by_jobs` (array parameter with `unnest`)
- [x] 3.6 Add tests for `get_task_ids_by_ip_and_status` and `get_tasks_with_cloud_by_id_status`

## 4. PostgreSQL-Specific Feature Tests

- [x] 4.1 Add test for `add_tmp_node` (provisional IP starts with "prov", disabled, correct cloud/username)
- [x] 4.2 Add test for migration idempotency (call `migrate()` twice, verify no error and tables still work)
