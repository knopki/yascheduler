## Context

Phase 2 of the Hexagonal + DDD migration. `docs/ARCHITECTURE.md` §6 Phase 2.
`domain-model` proposal created `TaskRepository` and `NodeRepository` Protocol
ports. This design implements them for PostgreSQL and extracts SQL from
`db.py` into version-controlled files.

The current `DB` class (~530 LOC) is used by 4 modules:
`scheduler.py`, `client.py`, `cloud_api_manager.py`, `utils.py`. Cloud
modules use only `NodeRepository`-equivalent methods and must continue to
work unchanged through the `db.py` wrapper until Phase 4.

## Goals / Non-Goals

**Goals:**
- Implement `PostgresTaskRepository` and `PostgresNodeRepository` against
  PostgreSQL via pg8000.
- Implement `PostgresUnitOfWork` with shared connection and transaction
  management.
- Extract all SQL from `db.py` into `adapters/persistence/sql/` files.
- Refactor `db.py` to delegate to the new repositories internally while
  preserving its external API.
- Map between old attrs models (`TaskModel`, `NodeModel`) and new domain
  types (`Task`, `Node`) at the repository boundary.

**Non-Goals:**
- No migration of cloud modules — they continue using `db.py` directly.
- No asyncpg or other DB driver — pg8000 remains.
- No connection pool — `ThreadPoolExecutor(max_workers=1)` unchanged.
- No schema changes or migrations (Phase 2.5).
- No wiring into use cases (Phase 3).

## Decisions

### D1: pg8000 in ThreadPoolExecutor (unchanged)

The persistence adapter wraps pg8000.Connection.run() in
`asyncio.get_running_loop().run_in_executor(self._executor, ...)` — same
pattern as current `DB.run()`. The executor has `max_workers=1` (pg8000
connections are not thread-safe). This is adequate; a connection pool
(Phase 5.5) will replace this later.

### D2: SQL files — one per query, lazy-loaded

```
adapters/persistence/sql/
├── schema.sql
├── task/
│   ├── get_by_id.sql
│   ├── list_by_status.sql
│   ├── insert.sql
│   ├── update_status.sql
│   └── ...
└── node/
    ├── get_by_ip.sql
    ├── list_enabled.sql
    ├── list_disabled.sql
    ├── insert.sql
    ├── enable.sql
    ├── disable.sql
    ├── remove.sql
    └── ...
```

Loaded via `load_query("task/get_by_id")` → `@functools.cache` → str.
Parameters use pg8000 `:param` named-placeholder style.

### D3: Repository methods map directly to SQL files

Each repository method corresponds to one SQL file:

| Repository method                      | SQL file                          |
| -------------------------------------- | --------------------------------- |
| `TaskRepository.get(task_id)`            | `task/get_by_id.sql`                |
| `TaskRepository.list_by_status(...)`     | `task/list_by_status.sql`           |
| `TaskRepository.save(task)`              | `task/upsert.sql` (full UPDATE)     |
| `NodeRepository.list_enabled()`          | `node/list_enabled.sql`             |
| `NodeRepository.enable(ip)`              | `node/enable.sql`                   |

### D4: UoW — shared connection, explicit commit

`PostgresUnitOfWork` creates a single pg8000 Connection on `__aenter__` and
passes it to both repositories. `commit()` calls `conn.commit()`. `rollback()`
is called on `__aexit__` if an exception occurred.

```python
class PostgresUnitOfWork:
    async def __aenter__(self):
        self._conn = await self._create_connection()
        self.tasks = PostgresTaskRepository(self._conn, self._executor)
        self.nodes = PostgresNodeRepository(self._conn, self._executor)
        return self

    async def commit(self):
        await self._run_sync(self._conn.commit)

    async def __aexit__(self, exc_type, *_):
        if exc_type is not None:
            await self._run_sync(self._conn.rollback)
        self._conn.close()
```

### D5: db.py wrapper — bidirectional adaptation

`DB` methods are refactored to:
1. Convert old models to domain types (e.g., `TaskModel` → `Task`)
2. Call repository methods
3. Convert domain types back to old models for return values

This is the **only** place that does old↔new model conversion. All other
callers see unchanged `TaskModel`/`NodeModel` returns.

Example:
```python
# db.py — old external API preserved
async def get_task(self, task_id: int) -> Optional[TaskModel]:
    task = await self._repo.get(task_id)
    if task is None:
        return None
    return self._task_to_model(task)

def _task_to_model(self, task: Task) -> TaskModel:
    return TaskModel(
        task_id=task.task_id,
        label=task.label,
        ip=task.allocated_ip or "",
        status=task.status,
        metadata={**task.context.extra, "engine": task.context.engine, ...},
    )
```

### D6: Old models stay as attrs, new are dataclasses

This creates two type systems in the codebase during the transition. The
boundary is `db.py`'s conversion methods — this is acceptable and
temporary. Old models are removed when all callers migrate to domain types
(Phase 3+).

## Risks / Trade-offs

- **Double type system during transition**: `TaskModel` (attrs) and `Task`
  (dataclass) coexist. Mitigation: conversion lives only in `db.py`; removed
  when callers migrate.
- **Full-row UPDATE on save()**: `TaskRepository.save()` updates all columns,
  not just changed fields. Acceptable given small row width and write
  frequency (tens per minute, not thousands per second).
- **JSONB metadata serialization**: `TaskContext` fields must be serialized
  to JSONB for storage and deserialized on read. `extra` dict preserves
  unknown keys. Mitigation: explicit `to_metadata()`/`from_metadata()`
  methods on `TaskContext` with roundtrip tests.
- **pg8000 connection not thread-safe**: `max_workers=1` prevents concurrent
  DB access within one process. This is a known limitation, addressed by
  the optional connection pool in Phase 5.5.
