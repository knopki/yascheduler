## Context

Phase 5.5. Persistence adapter currently serializes all DB access through
`ThreadPoolExecutor(max_workers=1)`. Pool enables concurrent operations.

## Goals

- Fixed-size pool of pg8000 connections.
- UoW acquires/releases from pool.
- Shared ThreadPoolExecutor for synchronous pg8000 calls.

## Decisions

### D1: asyncio.Queue-based pool

```python
class PgPool:
    def __init__(self, config: ConfigDb, size: int = 3):
        self._queue = asyncio.Queue(maxsize=size)
        self._executor = ThreadPoolExecutor(max_workers=size)
        for _ in range(size):
            self._queue.put_nowait(DB.create_connection(config))

    async def acquire(self) -> Connection:
        return await self._queue.get()

    async def release(self, conn: Connection):
        await self._queue.put(conn)
```

UoW acquires on `__aenter__`, releases on `__aexit__`. Pool size configurable
via `config.local.db_pool_size` (default 3).

### D2: Backward compatible

If pool_size=1, behavior is identical to current `ThreadPoolExecutor(1)`.
Default is 1 (no regression risk). Increase to 3+ when concurrency is needed.

## Risks

- **pg8000 connections not thread-safe**: Each connection is used by at most
  one UoW at a time (acquired from pool, released after commit). No concurrent
  access to a single connection.
