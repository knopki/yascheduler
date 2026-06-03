## Why

The `db.py` module (~530 lines) mixes connection management, SQL queries,
schema migration, and business-level CRUD in one file. There is no
repository abstraction — `scheduler.py`, `client.py`, and `cloud_api_manager.py`
all call `DB` methods directly.

Phase 1 (`domain-model`) defined `TaskRepository` and `NodeRepository` ports.
This change implements them for PostgreSQL, extracts SQL queries into
version-controlled `.sql` files, and wraps the existing `DB` class as a
facade over the new repositories. This preserves backward compatibility
while introducing the new persistence layer.

## What Changes

- Create `adapters/persistence/postgres.py` with `PostgresTaskRepository` and
  `PostgresNodeRepository` implementing the domain ports.
- Create `adapters/persistence/postgres_uow.py` with `PostgresUnitOfWork`
  implementing `AbstractUnitOfWork`.
- Create `adapters/persistence/sql/` with one `.sql` file per query extracted
  from `db.py`. Organize by entity: `sql/task/`, `sql/node/`.
- Create `adapters/persistence/sql/schema.sql` (copied from `data/schema.sql`).
- Add a `load_query(name)` helper with `@functools.cache` for lazy SQL loading.
- Modify `db.py` to delegate to `PostgresTaskRepository` / `PostgresNodeRepository`
  internally. External API of `DB` unchanged — all existing callers continue
  to work.
- Cloud modules (`CloudAPIManager`, `CloudAPI`) continue to use `db.py`
  directly — they are NOT migrated in this phase (see Phase 4).
- Add unit tests for repositories with in-memory doubles and integration
  tests against real PostgreSQL via testcontainers.

## Capabilities

### New Capabilities
- `postgres-repositories`: `PostgresTaskRepository` and `PostgresNodeRepository`
  implementing domain ports against PostgreSQL via pg8000.
- `postgres-uow`: `PostgresUnitOfWork` managing transaction boundaries with
  shared connection across repositories.
- `sql-queries`: SQL query files organized by entity, lazy-loaded via cache,
  with `schema.sql` as the authoritative DDL source.
- `db-wrapper`: `DB` class refactored as a thin facade delegating to
  repositories — preserves backward compatibility with all existing callers.

### Modified Capabilities
<!-- No existing specs — purely additive change. -->

## Impact

- New directory: `adapters/persistence/` (3 files: `postgres.py`,
  `postgres_uow.py`, `__init__.py`).
- New directory: `adapters/persistence/sql/` with `schema.sql`, `task/` and
  `node/` query files.
- Modified file: `yascheduler/db.py` — internal delegation to repositories,
  external API unchanged.
- New dependency on `yascheduler.domain` (ports and model types).
- No new third-party dependencies. No breaking changes.
- `docs/knowledge-graph.xml` updated with M-* entries for new modules.
