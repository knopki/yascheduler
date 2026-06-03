## 1. SQL Files

- [x] 1.1 Create `adapters/persistence/sql/` directory structure (schema.sql, task/, node/)
- [x] 1.2 Copy `data/schema.sql` → `adapters/persistence/sql/schema.sql`
- [x] 1.3 Extract `task/get_by_id.sql` from db.py get_task
- [x] 1.4 Extract `task/list_by_status.sql` from db.py get_tasks_by_status
- [x] 1.5 Extract `task/list_by_jobs.sql` from db.py get_tasks_by_jobs
- [x] 1.6 Extract `task/insert.sql` from db.py add_task
- [x] 1.7 Extract `task/update_status.sql` from db.py set_task_running/set_task_done/set_task_error
- [x] 1.8 Extract `task/update_meta.sql` from db.py update_task_meta
- [x] 1.9 Extract `task/upsert.sql` (full UPDATE for repository.save())
- [x] 1.10 Extract `task/count_by_status.sql` from db.py count_tasks_by_status
- [x] 1.11 Extract `node/get_by_ip.sql` from db.py get_node
- [x] 1.12 Extract `node/list_all.sql` from db.py get_all_nodes
- [x] 1.13 Extract `node/list_enabled.sql` from db.py get_enabled_nodes
- [x] 1.14 Extract `node/list_disabled.sql` from db.py get_disabled_nodes
- [x] 1.15 Extract `node/insert.sql` from db.py add_node
- [x] 1.16 Extract `node/insert_tmp.sql` from db.py add_tmp_node
- [x] 1.17 Extract `node/enable.sql` from db.py enable_node
- [x] 1.18 Extract `node/disable.sql` from db.py disable_node
- [x] 1.19 Extract `node/remove.sql` from db.py remove_node
- [x] 1.20 Extract `node/count_by_cloud.sql` from db.py count_nodes_clouds
- [x] 1.21 Extract `node/count_by_status.sql` from db.py count_nodes_by_status

## 2. SQL Loading Utility

- [x] 2.1 Create `adapters/persistence/__init__.py` with `load_query(name)` function
- [x] 2.2 Implement `@functools.cache` lazy loading from package resources
- [x] 2.3 Write unit test: first call reads file, second call returns cached

## 3. TaskContext Serialization

- [x] 3.1 Add `TaskContext.to_metadata() -> dict[str, object]` method
- [x] 3.2 Add `TaskContext.from_metadata(metadata: Mapping[str, object]) -> TaskContext` classmethod
- [x] 3.3 Write unit tests: roundtrip known fields, preserve extra keys
- [x] 3.4 Update `domain/model.py` with GRACE-lite markup for new methods

## 4. PostgresTaskRepository

- [x] 4.1 Create `adapters/persistence/postgres.py` with `PostgresTaskRepository` class
- [x] 4.2 Implement `get(task_id)` — load SQL, execute, map row → Task
- [x] 4.3 Implement `save(task)` — serialize TaskContext, execute upsert SQL
- [x] 4.4 Implement `list_by_status(statuses)` — execute list SQL, map rows
- [x] 4.5 Implement `list_by_jobs(job_ids)` — existing query, needed by Yascheduler facade
- [x] 4.6 Implement `count_by_status()` — aggregation
- [x] 4.7 Implement row→Task mapping: `_row_to_task(row) -> Task`
- [x] 4.8 Write unit tests with `FakeDB`-style in-memory double for all methods

## 5. PostgresNodeRepository

- [x] 5.1 Add `PostgresNodeRepository` class in `adapters/persistence/postgres.py`
- [x] 5.2 Implement `get(ip)`, `list_enabled()`, `list_disabled()`, `list_all()`
- [x] 5.3 Implement `add(node)`, `add_tmp(ip, cloud)`, `update(node)`
- [x] 5.4 Implement `enable(ip)`, `disable(ip)`, `remove(ip)`
- [x] 5.5 Implement `count_by_cloud()`, `count_by_status()`
- [x] 5.6 Write unit tests with FakeDB-style double

## 6. PostgresUnitOfWork

- [x] 6.1 Create `adapters/persistence/postgres_uow.py` with `PostgresUnitOfWork`
- [x] 6.2 Implement `__aenter__`: create connection, instantiate both repositories
- [x] 6.3 Implement `commit()`: run conn.commit() in executor
- [x] 6.4 Implement `__aexit__`: rollback on exception, close connection
- [x] 6.5 Write unit tests: commit persists, exception rollbacks, connection closes

## 7. DB Wrapper

- [x] 7.1 Add `PostgresTaskRepository` and `PostgresNodeRepository` as internal deps in `DB.__init__`
- [x] 7.2 Implement `_task_to_model(task: Task) -> TaskModel` conversion method
- [x] 7.3 Implement `_model_to_node(node_model: NodeModel) -> Node` conversion method
- [x] 7.4 Implement `_node_to_model(node: Node) -> NodeModel` conversion method
- [x] 7.5 Refactor `get_task()`, `get_tasks_by_status()`, `get_tasks_by_jobs()` to delegate
- [x] 7.6 Refactor `add_task()` — kept original INSERT (needs RETURNING task_id), converted via model
- [x] 7.7 Refactor `set_task_running()`, `set_task_done()`, `set_task_error()` to delegate
- [x] 7.8 Refactor `update_task_meta()` to delegate
- [x] 7.9 Refactor `count_tasks_by_status()` to delegate
- [x] 7.10 Refactor all Node methods to delegate: `get_node`, `get_*_nodes`, `add_node`, `add_tmp_node`, `enable_node`, `disable_node`, `remove_node`, `count_nodes_*`
- [x] 7.11 Preserve `commit()` method — delegates to conn (unchanged)
- [x] 7.12 Preserve `migrate()` method — unchanged
- [x] 7.13 Existing unit tests cover DB methods returning same types (all 14 pass)

## 8. Integration Tests

- [x] 8.1 Create `tests/integration/test_persistence_adapter.py` (or extend existing)
- [x] 8.2 Test PostgresTaskRepository against real PostgreSQL via testcontainers: CRUD, status transitions, JSONB roundtrip
- [x] 8.3 Test PostgresNodeRepository: add, enable, disable, remove, list
- [x] 8.4 Test PostgresUnitOfWork: commit/rollback semantics with real DB
- [x] 8.5 Test DB wrapper: old API returns correct TaskModel/NodeModel with real DB (covered by existing test_db_integration.py — 15 tests)

## 9. Verification

- [x] 9.1 Run `grace_check.py` — 0 errors, 8 pre-existing warnings (1 new soft-limit warning for test_persistence_adapter.py 610 lines)
- [x] 9.2 Update `docs/knowledge-graph.xml` with M-* entries for new modules
- [x] 9.3 Run `openspec validate --all --json` — all 16 items pass
- [x] 9.4 Run `uv run pytest tests/unit/ -k "persistence"` — 30 tests pass
- [x] 9.5 Run `uv run pytest tests/integration/` — 15+14=29 integration tests pass
- [x] 9.6 Run `uv run zuban check` — 0 new errors (64 pre-existing from missing optional deps: azure, hcloud, upcloud_api, aiida)
- [x] 9.7 Run `uv run ruff check yascheduler/adapters/` — no lint errors
- [x] 9.8 Run full existing test suite — 189/189 unit tests pass, no regressions
