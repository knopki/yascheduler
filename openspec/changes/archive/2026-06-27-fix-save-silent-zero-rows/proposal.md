## Why

`PostgresTaskRepository.save()` and `.update_status()` run bare `UPDATE ...
WHERE task_id = :task_id` SQL with no `RETURNING` and no row-count check.
When no row matches `task_id`, the UPDATE affects 0 rows **silently** — no
error, no log, no signal — yet `save()`'s contract and docstring call this
an "upsert", and `save()` unconditionally appends the task to the UoW's
`_saved_tasks` list as if it were persisted. The misleading name plus the
silent 0-row path are an active footgun: a future caller that reasonably
invokes `save()` on a fresh task expecting an INSERT would lose data
without any error. There is also one live (narrow) instance today — the
orchestrator's task-abandon path races the row's lifetime and currently
silently no-ops.

## What Changes

- Rename `sql/task/upsert.sql` → `sql/task/update_by_id.sql` and add
  `RETURNING task_id` so the repository can detect a 0-row outcome.
- Add `RETURNING task_id` to `sql/task/update_status.sql` for the same
  reason.
- `PostgresTaskRepository.save()` checks the returned rows; if empty,
  raises `TaskRowNotFoundError` **before** appending to `_saved_tasks`.
- `PostgresTaskRepository.update_status()` checks the returned rows; if
  empty, raises `TaskRowNotFoundError`.
- Add `TaskRowNotFoundError(RuntimeError)` in
  `yascheduler/infra/persistence/exceptions.py` as a sibling of
  `UnitOfWorkNotInitializedError` — a programming-error / contract
  precondition violation, NOT a domain exception. Callers SHALL NOT catch
  it.
- Wrap the orchestrator consumer worker in
  `_create_producer_consumers` (`orchestrator.py`) in `try/except
  Exception` symmetric to the existing allocator-consumer wrap, so a
  `TaskRowNotFoundError` raised by the abandon-path race (or any other
  consumer exception) is logged and the worker continues instead of
  silently dying. The `finally: queue.item_done(msg)` is preserved.

## Capabilities

### New Capabilities

- `task-row-not-found-error`: Exception class raised by
  `PostgresTaskRepository.save()` and `.update_status()` when an UPDATE
  targets a non-existent `task_id`. Sibling to
  `uow-not-initialized-error`; programming-error, not domain error.

### Modified Capabilities

- `postgres-repositories`: `save()` and `update_status()` gain a
  precondition — the target row MUST exist — and raise
  `TaskRowNotFoundError` on 0-row outcomes instead of silently succeeding.
  The "Save task updates all columns" and "Update status atomically"
  scenarios are tightened.
- `orchestrator`: the consumer worker in
  `_create_producer_consumers` catches non-`CancelledError` exceptions
  from `consumer(msg)`, logs them, and continues the loop — symmetric to
  the existing producer-error resilience requirement and the
  allocator-consumer wrap. Today the worker has bare `try/finally` with no
  `except`, so any consumer exception silently kills the worker task.
- `sql-queries`: `sql/task/upsert.sql` is renamed to
  `sql/task/update_by_id.sql` and gains `RETURNING task_id`;
  `sql/task/update_status.sql` gains `RETURNING task_id`.

## Impact

- **Code**: `yascheduler/infra/persistence/postgres.py` (`save`,
  `update_status`), `yascheduler/infra/persistence/exceptions.py` (new
  class), `yascheduler/infra/persistence/sql/task/update_by_id.sql`
  (renamed + RETURNING), `yascheduler/infra/persistence/sql/task/update_status.sql`
  (RETURNING), `yascheduler/application/orchestrator.py` (worker wrap).
- **Public port**: `TaskRepository.save` / `.update_status` signatures
  unchanged (still `async def ... -> None`); the new raise is a new
  failure mode on a path that was previously silently broken. Not a
  breaking change for correct callers (all current callers operate on rows
  they just loaded or inserted).
- **Knowledge graph**: add `class-TaskRowNotFoundError` annotation under
  `M-PERSISTENCE-EXCEPTIONS`; add `CrossLink` from `M-PERSISTENCE-POSTGRES`
  to `M-PERSISTENCE-EXCEPTIONS` (repositories raise persistence exceptions,
  not only the UoW).
- **Tests**: integration tests for the 0-row raise path (per
  `test-db-integration` spec); orchestrator unit test for consumer-exception
  resilience.
- **Out of scope**: `submit_task` two-round-trip consolidation (architectural,
  blocked by SERIAL task_id); `tz-aware datetime.now()` in `submit_task`
  (separate proposal); removal of dead `update_meta.sql` (separate
  cleanup).