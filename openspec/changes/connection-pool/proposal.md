## Why

The persistence adapter uses `ThreadPoolExecutor(max_workers=1)` because
pg8000 connections are not thread-safe. This serializes all database access
within one process. As use cases are decomposed (Phase 3), multiple concurrent
operations queue on the single executor. While not a proven bottleneck, a
connection pool enables true parallelism when needed.

## What Changes

- Create `adapters/persistence/pool.py` — `PgPool` class managing a fixed-size
  pool of pg8000 connections via `asyncio.Queue`.
- Update `PostgresUnitOfWork` to acquire a connection from the pool on
  `__aenter__` and release it on `__aexit__`.
- Remove `ThreadPoolExecutor` from individual repository methods — the pool
  owns a shared executor.
- **Optional**: existing `ThreadPoolExecutor(max_workers=1)` remains as
  fallback if pool size is 1.

## Capabilities

### New Capabilities
- `connection-pool`: Fixed-size async connection pool for pg8000 allowing
  concurrent database operations across multiple UoW instances.

## Impact

- New file: `adapters/persistence/pool.py`.
- Modified: `adapters/persistence/postgres_uow.py` — acquires from pool.
- Modified: `adapters/persistence/postgres.py` — repositories use pool's executor.
- No schema changes. No new dependencies.
