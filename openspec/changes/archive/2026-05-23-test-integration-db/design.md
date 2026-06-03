## Context

The `DB` class wraps pg8000 for async PostgreSQL access. It uses PG-specific SQL: `unnest(CAST(:x AS int[]))` for array parameters, `RANDOM()::TEXT` / `MD5()` / `SUBSTR()` for provisional IPs, `jsonb` columns, and `SERIAL` primary keys. The schema is defined in `yascheduler/data/schema.sql` (2 tables, 16 lines). The `test-foundation` change already declared `testcontainers[postgres]` as a dependency.

The `DB.create()` factory connects, creates an executor, and optionally runs `migrate()`. Tests need a real PG instance with the schema applied.

## Goals / Non-Goals

**Goals:**
- Spin up PostgreSQL via testcontainers-python (session scope)
- Apply schema once per session, TRUNCATE tables before each test
- Test all DB methods against real PostgreSQL: node CRUD, task CRUD, status transitions, PG-specific queries
- Verify migration idempotency (running migrate twice succeeds)

**Non-Goals:**
- Testing concurrent access patterns (future work)
- Testing `Scheduler` or `RemoteMachine` with real DB (follow-up changes)
- SSH or cloud integration (separate test level)

## Decisions

### D1: testcontainers-postgres with session scope

Use `testcontainers.postgres.PostgresContainer` with `postgresql:16-alpine` image. The container starts once per test session and is shared across all integration tests.

```python
@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg
```

### D2: Schema creation in session-scoped `db` fixture

Create the `DB` instance once per session via `DB.create()`, applying schema from `schema.sql` plus `migrate()`. This avoids recreating tables per test.

### D3: Per-test isolation via TRUNCATE

Before each test, TRUNCATE both tables:

```python
@pytest.fixture(autouse=True)
async def clean_tables(db):
    yield
    await db.run("TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE")
```

Pre-test TRUNCATE (not post-test) ensures clean state even if a test fails. Actually, post-test is fine here — each test starts with empty tables from the previous test's cleanup, and the first test gets clean tables from schema creation.

### D4: ConfigDb derived from testcontainer connection params

The testcontainer exposes `get_connection_url()`. Parse it to build a `ConfigDb` for `DB.create()`.

### D5: All tests async via pytest-asyncio

Integration tests use `async def test_*` just like unit tests. The `DB` class is async throughout.

## Risks / Trade-offs

- **Requires Docker** on developer machine → integration tests are opt-in (`pytest tests/integration/`), unit tests always work without Docker
- **Container startup ~2-3s** per session → acceptable; tests themselves should be fast (simple SQL)
- **testcontainers may fail in some CI environments** → skip integration tests if Docker unavailable (using `pytest.mark.integration` + skip logic)
- **pg8000 connection may drop between tests** → unlikely for local Docker, but `DB.run` already has `backoff.on_exception(InterfaceError)` retry
