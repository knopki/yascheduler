## Why

Unit tests with mocked pg8000 verify SQL strings but cannot catch real PostgreSQL compatibility issues. The DB layer uses PG-specific features (`unnest`, `RANDOM()::TEXT`, `MD5`, `jsonb`, `SERIAL`). Integration tests against a real PostgreSQL instance validate that SQL queries, parameter binding, and result mapping actually work end-to-end.

## What Changes

- Create `tests/integration/conftest.py` with testcontainers-postgres fixtures (session-scoped container, schema creation, per-test TRUNCATE)
- Create `tests/integration/test_db_integration.py` covering node CRUD, task CRUD, status transitions, migration idempotency, and PostgreSQL-specific queries (`add_tmp_node`, `get_tasks_by_jobs`, `count_nodes_clouds`)
- Define the integration test execution contract: requires Docker, runs via `pytest tests/integration/`

## Capabilities

### New Capabilities
- `test-db-integration`: Integration tests for `DB` class against real PostgreSQL via testcontainers

### Modified Capabilities
_(none)_

## Impact

- New `tests/integration/conftest.py` with postgres fixtures
- New `tests/integration/test_db_integration.py`
- No changes to production code
