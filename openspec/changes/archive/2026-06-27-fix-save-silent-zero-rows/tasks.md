## 1. SQL query files

- [x] 1.1 Rename `yascheduler/infra/persistence/sql/task/upsert.sql` → `yascheduler/infra/persistence/sql/task/update_by_id.sql` (git mv)
- [x] 1.2 Add `RETURNING task_id` to `sql/task/update_by_id.sql` so the statement becomes `UPDATE yascheduler_tasks SET label = :label, status = :status, ip = :ip, metadata = :metadata WHERE task_id = :task_id RETURNING task_id;`
- [x] 1.3 Add `RETURNING task_id` to `yascheduler/infra/persistence/sql/task/update_status.sql` so the statement becomes `UPDATE yascheduler_tasks SET status = :status WHERE task_id = :task_id RETURNING task_id;`

## 2. Exception class

- [x] 2.1 Add `TaskRowNotFoundError(RuntimeError)` to `yascheduler/infra/persistence/exceptions.py` as a sibling of `UnitOfWorkNotInitializedError`. Constructor `__init__(self, task_id: int)` stores `self.task_id` and calls `super().__init__(f"task row not found for task_id={task_id}")`. Add MODULE_MAP entry and CHANGE_SUMMARY entry; bump VERSION.
- [x] 2.2 Re-export `TaskRowNotFoundError` from `yascheduler/infra/persistence/__init__.py` alongside `UnitOfWorkNotInitializedError` (so application/adapter consumers import it from the package facade, matching the existing `UnitOfWorkNotInitializedError` re-export pattern).

## 3. Repository methods

- [x] 3.1 In `yascheduler/infra/persistence/postgres.py` `PostgresTaskRepository.save()`: change `load_query("task/upsert")` → `load_query("task/update_by_id")`; capture the rows returned by `_run`; if empty, raise `TaskRowNotFoundError(task.task_id)` BEFORE the `if self._saved_tasks is not None: self._saved_tasks.append(task)` line; otherwise proceed to append. Update the `save` START_CONTRACT block PURPOSE (drop "Upsert", say "Update mutable fields of an existing task row by task_id; raise TaskRowNotFoundError if the row does not exist"), SIDE_EFFECTS (note the raise), and LINKS (task/update_by_id.sql, TaskRowNotFoundError). Fix the docstring (drop "upsert by task_id").
- [x] 3.2 In `PostgresTaskRepository.update_status()`: capture the rows returned by `_run`; if empty, raise `TaskRowNotFoundError(task_id)`. Update the `update_status` START_CONTRACT block PURPOSE (add "raise TaskRowNotFoundError if the row does not exist") and LINKS (add TaskRowNotFoundError). Fix the docstring.

## 4. Orchestrator consumer worker wrap

- [x] 4.1 In `yascheduler/application/orchestrator.py` `_create_producer_consumers` inner `worker()`: wrap the `try: await consumer(msg)` / `finally: queue.item_done(msg)` in `try/except Exception` that logs the error (mirror the producer-error log shape at lines 611-617: `self._log.error("[Orchestrator][_create_producer_consumers][CONSUMER_ERROR] queue=%s err=%s", queue.name, err)`). Preserve `finally: queue.item_done(msg)`. Ensure `asyncio.CancelledError` (BaseException, not Exception) still propagates past the new `except Exception` to the existing `except asyncio.CancelledError` drain path.
- [x] 4.2 Update the `_create_producer_consumers` START_CONTRACT PURPOSE and SIDE_EFFECTS to note that both producer and consumer exceptions are caught and logged (currently only producer is mentioned). Add a CHANGE_SUMMARY entry for `orchestrator.py` noting the consumer-worker exception wrap.

## 5. Knowledge graph

- [x] 5.1 In `docs/knowledge-graph.xml` under `M-PERSISTENCE-EXCEPTIONS`: add `<class-TaskRowNotFoundError PURPOSE="Raised by PostgresTaskRepository.save/update_status when an UPDATE targets a non-existent task_id" />` alongside the existing `class-UnitOfWorkNotInitializedError` annotation.
- [x] 5.2 In `docs/knowledge-graph.xml`: add `<CrossLink from="M-PERSISTENCE-POSTGRES" to="M-PERSISTENCE-EXCEPTIONS" relation="raises TaskRowNotFoundError on 0-row UPDATE outcome" />` (mirrors the existing `CrossLink from="M-PERSISTENCE-UOW" to="M-PERSISTENCE-EXCEPTIONS"`).
- [x] 5.3 Update the `M-PERSISTENCE-EXCEPTIONS` and `M-PERSISTENCE-POSTGRES` module VERSION/CHANGE_SUMMARY markers if the governed files' VERSION comments change (consistency per GRACE-lite).

## 6. Tests — integration (per test-db-integration spec)

- [x] 6.1 In `tests/integration/test_db_integration.py` (or a new `tests/integration/test_task_row_not_found.py`): add a test that `save(task)` with a non-existent `task_id` raises `TaskRowNotFoundError` and the UoW's `_saved_tasks` list does NOT contain the task afterward (verify via `uow._saved_tasks` after the raise, or via `collect_events()` returning no events for that task_id). Use a real PostgreSQL via testcontainers per the test-db-integration spec.
- [x] 6.2 Add an integration test that `update_status(999, TaskStatus.RUNNING)` (non-existent task_id) raises `TaskRowNotFoundError`.
- [x] 6.3 Verify the existing 4 `save()` integration tests in `tests/integration/test_persistence_adapter.py` (lines 277, 298, 343, 374) still pass unchanged (rows exist for those calls).

## 7. Tests — orchestrator unit (consumer resilience)

- [x] 7.1 In `tests/unit/test_application_orchestrator.py` (or a new `tests/unit/test_orchestrator_consumer_resilience.py` mirroring `test_orchestrator_producer_resilience.py`): add a test that when the consumer callable raises a non-`CancelledError` `Exception` (use a stand-in exception, e.g. a `TaskRowNotFoundError` constructed with a fake task_id, or a plain `RuntimeError`), the orchestrator logs the error and the worker continues processing subsequent queue messages (does not crash the loop). Mirror the `test_producer_exception_continues_loop` pattern at `test_orchestrator_producer_resilience.py:184`.
- [x] 7.2 Add a test that `asyncio.CancelledError` raised by the consumer still propagates to the `except asyncio.CancelledError` drain path (graceful shutdown preserved), mirroring the producer-side CancelledError scenario.

## 8. Static checks and validation

- [x] 8.1 Run `uv run ruff check .` and `uv run ruff format --check .` — fix any lint/format issues introduced.
- [x] 8.2 Run `uv run lint-imports` — verify the new `TaskRowNotFoundError` import paths are consistent with the existing `UnitOfWorkNotInitializedError` import pattern.
- [x] 8.3 Run `python3 scripts/grace_check.py` — verify knowledge-graph.xml and source MODULE_CONTRACT/START_CONTRACT/CHANGE_SUMMARY markers are consistent after the edits.
- [x] 8.4 Run `openspec validate --all --json` — verify the change proposal and main specs validate cleanly after the delta specs.
- [x] 8.5 Run the targeted test suites: `uv run pytest -m unit tests/unit/test_application_orchestrator.py tests/unit/test_orchestrator_consumer_resilience.py` and `uv run pytest -m integration tests/integration/test_task_row_not_found.py` (or the added integration tests). Confirm all green.