## 1. Domain Ports — TaskRepository limit parameter

- [x] 1.1 Add `limit: int | None = None` parameter to `TaskRepository.list_by_status` in `domain/ports.py`
- [x] 1.2 Update `PostgresTaskRepository.list_by_status` in `adapters/persistence/postgres.py` to pass `limit` to SQL query
- [x] 1.3 Update SQL query file in `adapters/persistence/sql/` to support optional LIMIT clause

## 2. Rewrite allocate_task use case

- [x] 2.1 Rewrite `allocate_task` signature: replace `task: TaskModel, db: DB` with `task_id: int, uow_factory: Callable[[], AbstractUnitOfWork]`
- [x] 2.2 Replace `_validate_engine` to load task via UoW and use domain `Task.context.engine` instead of `task.metadata.get("engine")`
- [x] 2.3 Replace `_find_free_machines` to query running tasks via `uow.tasks.list_by_status({TaskStatus.RUNNING})` instead of `db.get_tasks_by_status`
- [x] 2.4 Replace `_try_start_on_machine` to use `task.allocate_to(ip).mark_running()` + `uow.tasks.save()` + `uow.commit()` instead of `db.set_task_running` + `db.commit`
- [x] 2.5 Remove `from yascheduler.db import DB, TaskModel, TaskStatus` — use domain types only

## 3. Rewrite consume_task use case

- [x] 3.1 Rewrite `consume_task` signature: replace `task: TaskModel, db: DB` with `task_id: int, uow_factory: Callable[[], AbstractUnitOfWork]`
- [x] 3.2 Update `_prepare_store_folder` to read from `task.context.remote_folder`, `task.context.extra` instead of `meta["remote_folder"]`, `meta["engine"]`
- [x] 3.3 Update `_finalize_task` to use `task.complete()` or `task.fail()` + `uow.tasks.save()` instead of `db.set_task_done` / `db.set_task_error`
- [x] 3.4 Remove `from yascheduler.db import DB, TaskModel, TaskStatus` — use domain types only

## 4. Rewrite deallocate_nodes use case

- [x] 4.1 Rewrite `deallocate_nodes` signature: replace `db: DB` with `uow_factory: Callable[[], AbstractUnitOfWork]`; add `idle_machines` parameter
- [x] 4.2 Replace DB queries: `uow.tasks.list_by_status` for busy IPs, `uow.nodes.list_enabled` / `uow.nodes.list_disabled` for node queries
- [x] 4.3 Replace `db.disable_node` + `db.commit` with `uow.nodes.disable` + `uow.commit`
- [x] 4.4 Change return type to `list[str]` (disabled node IPs) instead of None
- [x] 4.5 Remove `from yascheduler.db import DB, NodeModel, TaskStatus` — use domain types only

## 5. Update Orchestrator

- [x] 5.1 Replace `db: DB` constructor parameter with `uow_factory: Callable[[], AbstractUnitOfWork]`; remove `self._db`
- [x] 5.2 Update `_allocator_producer` to query via `async with self._uow_factory() as uow: tasks = await uow.tasks.list_by_status(...)` yielding domain `Task`
- [x] 5.3 Update `_task_consumer_producer` to query via UoW yielding domain `Task`
- [x] 5.4 Update `_deallocator_producer` to call `deallocate_nodes` use case with `uow_factory` and handle returned IPs for SSH disconnect + cloud deallocation
- [x] 5.5 Update `_connect_machine_producer` to query via `uow.nodes.list_enabled()`
- [x] 5.6 Update `_print_stats` to use UoW for `count_tasks_by_status` / `count_nodes_by_status`
- [x] 5.7 Update `_start_task_on_machine` to accept domain `Task` and read `task.context.remote_folder`, `task.context.extra` instead of `task.metadata[...]`
- [x] 5.8 Update `_upload_task_data` to accept domain `Task` and read input files from `task.context.extra`
- [x] 5.9 Update `_exec_spawn_command` to accept domain `Task` and read `task.allocated_ip` instead of `task.ip`
- [x] 5.10 Update `_allocator_consumer` to pass `task_id` (from domain `Task`) to new `allocate_task` signature
- [x] 5.11 Update `_task_consumer_consumer` to pass `task_id` to new `consume_task` signature; handle machine lookup by `task.allocated_ip`
- [x] 5.12 Update queue type hints: `UMessage[int, Task]` instead of `UMessage[int, TaskModel]`
- [x] 5.13 Remove `from yascheduler.db import DB, NodeModel, TaskModel, TaskStatus` — use domain types

## 6. Update Dependency Injection

- [x] 6.1 Update `make_daemon` to create `PostgresUnitOfWork` factory and pass `uow_factory` to `Orchestrator`; keep `DB.create` for schema migration only
- [x] 6.2 Remove `db=db` from `Orchestrator(...)` constructor call

## 7. Update GRACE-lite artifacts

- [x] 7.1 Update `MODULE_CONTRACT` and `MODULE_MAP` in all modified files (allocate_task, consume_task, deallocate_nodes, orchestrator, di)
- [x] 7.2 Update `CHANGE_SUMMARY` entries in all modified files
- [x] 7.3 Update `docs/knowledge-graph.xml`: remove `M-DB` from depends of `M-APPLICATION-ALLOCATE`, `M-APPLICATION-CONSUME`, `M-APPLICATION-DEALLOCATE`, `M-APPLICATION-ORCHESTRATOR`; add `M-APPLICATION-UOW` dependency; update `<annotations>` for changed signatures

## 8. Verification

- [x] 8.1 Run `uv run zuban check` and `uv run ruff check .`
- [x] 8.2 Run `openspec validate --all --json`
- [x] 8.3 Run `python3 scripts/grace_check.py`
- [x] 8.4 Run existing test suite and verify no regressions
