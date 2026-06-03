## Why

`_init_db` in `adapters/cli/init.py` applies `schema.sql` through the legacy `DB`
class using autocommit — no transaction, no rollback on partial failure. The same
ad-hoc pattern is duplicated in `tests/integration/conftest.py` and
`tests/e2e/conftest.py` (`_init_schema` fixtures), each manually constructing
paths to `schema.sql` and calling `DB.run()` + `migrate()`.

A small, synchronous adapter that applies the full schema in a single transaction
eliminates the legacy dependency, removes duplication, and makes `yainit` a plain
sync function.

## What Changes

- Add `adapters/persistence/postgres_schema.py` with a sync `apply_schema()`
  function that reads `schema.sql` via `load_query` and applies it in a
  `BEGIN/COMMIT` transaction using pg8000 directly.
- Rewrite `adapters/cli/init.py`: `init()` becomes sync (remove `@to_sync`,
  remove async), `_init_db()` calls `apply_schema()`.
- Rewrite `_init_schema` fixtures in `tests/integration/conftest.py` and
  `tests/e2e/conftest.py` to call `apply_schema()` (sync fixtures).
- Add an integration test for `apply_schema()` against testcontainers PostgreSQL.

## Capabilities

### New Capabilities
- `postgres-schema-apply`: Synchronous, transactional application of `schema.sql`
  via pg8000 for fresh database initialization.

### Modified Capabilities
- `cli-commands`: `yainit` command becomes fully synchronous; `_init_db` uses the
  new adapter instead of the legacy `DB` class.
- `test-db-integration`: `_init_schema` fixtures simplified to call
  `apply_schema()`.
- `e2e-testing`: `_init_schema` fixture simplified to call `apply_schema()`.

## Impact

- New file: `yascheduler/adapters/persistence/postgres_schema.py`
- New file: `tests/integration/test_postgres_schema.py`
- Modified: `yascheduler/adapters/cli/init.py` — remove async, `@to_sync`, legacy
  `DB` import; call `apply_schema()`
- Modified: `tests/integration/conftest.py` — sync `_init_schema` fixture
- Modified: `tests/e2e/conftest.py` — sync `_init_schema` fixture
- No breaking changes to public API (`yainit` CLI behavior unchanged)
