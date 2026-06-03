## 1. Abstract Unit of Work Protocol

- [x] 1.1 Create `application/uow.py` with `AbstractUnitOfWork` Protocol
- [x] 1.2 Define async context manager support and commit/rollback methods
- [x] 1.3 Add GRACE-lite markup

## 2. Use Cases

- [x] 2.1 Create `application/submit_task.py` — `submit_task()` async function
- [x] 2.2 Extract create_new_task logic from scheduler.py
- [x] 2.3 Create `application/allocate_task.py` — `allocate_task()` async function
- [x] 2.4 Extract allocate_task logic from scheduler.py (find free machine, start on machine)
- [x] 2.5 Create `application/consume_task.py` — `consume_task()` async function
- [x] 2.6 Extract consume_task logic from scheduler.py (download, mark done)
- [x] 2.7 Create `application/deallocate_nodes.py` — `deallocate_nodes()` async function
- [x] 2.8 Extract deallocator logic from scheduler.py (disable idle, delete VMs)
- [x] 2.9 Add GRACE-lite markup to all use case files
- [x] 2.10 Write unit tests for each use case with faked ports

## 3. Orchestrator

- [x] 3.1 Create `application/orchestrator.py` with `Orchestrator` class
- [x] 3.2 Extract producer-consumer loop infrastructure from scheduler.py
- [x] 3.3 Wire use cases into consumer loops
- [x] 3.4 Implement start/stop with cancellation event
- [x] 3.5 Implement stats printing loop
- [x] 3.6 Implement first-machine wait logic
- [x] 3.7 Add GRACE-lite markup
- [x] 3.8 Write unit tests: loop lifecycle, concurrency limits, cancellation

## 4. Dependency Injection

- [x] 4.1 Create `di.py` with `make_daemon(config)` factory
- [x] 4.2 Wire full daemon dependency graph: UoW factory, use cases, orchestrator
- [x] 4.3 Create `make_cli_deps(config)` factory
- [x] 4.4 Wire lightweight CLI deps: UoW factory, submit use case, query use case
- [x] 4.5 Stub `make_aiida(config)` for future use
- [x] 4.6 Add GRACE-lite markup

## 5. Scheduler Refactoring

- [x] 5.1 Replace `scheduler.create_new_task()` body with `submit_task()` call
- [x] 5.2 Replace `scheduler.allocate_task()` body with `allocate_task()` call
- [x] 5.3 Replace `scheduler.consume_task()` body with `consume_task()` call
- [x] 5.4 Replace deallocator producer/consumer with `deallocate_nodes()` call
- [x] 5.5 Remove extracted inline methods from scheduler.py (upload_task_data, etc.)
- [x] 5.6 Verify scheduler.py is ~300 lines (loop infrastructure only)
- [x] 5.7 Write characterization tests: old behavior == new behavior for all 4 operations

## 6. Client Refactoring

- [x] 6.1 Replace `from .scheduler import Scheduler` with `from .di import make_cli_deps`
- [x] 6.2 Rewrite `queue_submit_task_async()` to use submit_task via CLI deps
- [x] 6.3 Verify `queue_submit_task()` (sync) still works via `to_sync()`
- [x] 6.4 Verify `queue_get_tasks*` and `queue_get_task*` methods unchanged
- [x] 6.5 Write smoke test: full Yascheduler public API unchanged
- [x] 7.1 Refactor `utils.submit()` to use `make_cli_deps().submit`
- [x] 7.2 Refactor `utils.check_status()` to use `make_cli_deps().query`
- [x] 7.3 Refactor `utils.show_nodes()` to use `make_cli_deps().query`
- [x] 7.4 Refactor `utils.manage_node()` to use `make_cli_deps()`
- [x] 7.5 Refactor `utils.daemonize()` to use `make_daemon()`
- [x] 7.6 Write smoke tests: all 6 CLI commands still functional

## 8. Verification

- [x] 8.1 Run `grace_check.py` — all new and modified files pass
- [x] 8.2 Update `docs/knowledge-graph.xml` with M-* entries for application modules
- [x] 8.3 Run `openspec validate --all --json`
- [x] 8.4 Run `uv run pytest tests/unit/ -k "use_case or orchestrator or di"` — new tests pass
- [x] 8.5 Run `uv run pytest tests/unit/test_scheduler.py` — existing scheduler tests pass
- [x] 8.6 Run `uv run zuban check` — no type errors
- [x] 8.7 Run `uv run ruff check yascheduler/application/ yascheduler/di.py` — no lint errors
- [x] 8.8 Run full existing test suite — no regressions
- [x] 8.9 Verify `import yascheduler.client` does not trigger `import yascheduler.scheduler`
