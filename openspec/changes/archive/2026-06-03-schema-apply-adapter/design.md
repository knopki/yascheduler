## Context

`_init_db` in `adapters/cli/init.py` and the `_init_schema` fixtures in both
`tests/integration/conftest.py` and `tests/e2e/conftest.py` apply `schema.sql`
through the legacy async `DB` class. This pulls in `@to_sync`, `ThreadPoolExecutor`,
and autocommit execution — no transaction wrapping the DDL.

The new persistence adapter layer (`adapters/persistence/`) already has
`sql_loader.py` for cached SQL file reads and pg8000-based infrastructure.
This change adds a small, synchronous schema application function alongside it.

## Goals / Non-Goals

**Goals:**
- Synchronous `apply_schema(config)` that applies `schema.sql` in a single
  `BEGIN/COMMIT` transaction using pg8000 directly.
- Eliminate `@to_sync` / async from `yainit` CLI command.
- Unify schema initialization in test fixtures to use the same function.
- Integration test proving schema applies cleanly against real PostgreSQL.

**Non-Goals:**
- Idempotency (running on an existing database is out of scope).
- Migration system (forward-only migrations are a separate change).
- Replacing `DB.migrate()` (deferred to future cleanup).

## Decisions

### D1: Synchronous pg8000 native function

`apply_schema()` is a plain synchronous function using `pg8000.native.Connection`
directly. No async, no `ThreadPoolExecutor`, no `run_in_executor`.

Rationale: Schema application is a one-shot CLI operation (or test setup). There
is no concurrency requirement. Sync code is simpler and eliminates the `@to_sync`
wrapper from `init()`.

### D2: Transactional DDL

The function wraps `schema.sql` execution in `BEGIN/COMMIT`. On failure, it
executes `ROLLBACK` and re-raises the exception.

Rationale: PostgreSQL supports transactional DDL. If any `CREATE TABLE` fails,
none are partially applied. This is the core improvement over the current
autocommit approach.

### D3: Uses `load_query("schema")`

Instead of manually constructing a `Path` to `schema.sql`, the function uses the
existing `sql_loader.load_query("schema")` — the same loader used by repositories.

Rationale: Single source of truth for SQL file loading. Removes path duplication
across `init.py` and test fixtures.

### D4: Error handling — re-raise after rollback

`DatabaseError` with "already exists" is caught to print a message, then
re-raised. pg8000 raises `DatabaseError` (not `ProgrammingError`) for the
`42P07` duplicate table SQL state. The original `_init_db` caught
`ProgrammingError`, which was incorrect — this change fixes the catch to
match actual pg8000 behavior.

### D5: File naming — `postgres_schema.py`

Named `postgres_schema.py` (not `schema.py`) to match the `postgres_*.py`
convention in the persistence adapter directory and make the pg8000 dependency
explicit.

## Risks / Trade-offs

- **Not idempotent**: Running `apply_schema()` on a database with existing tables
  raises `DatabaseError`. Accepted — idempotency is explicitly out of scope.
- **pg8000 native, no pooling**: Opens and closes a connection per call. Acceptable
  for a one-shot CLI operation and test fixtures.
- **sync fixture in async conftest**: pytest handles mixed sync/async fixtures
  correctly — no issue expected.
