## 1. Integration/e2e conftest fixtures

- [x] 1.1 In `tests/integration/conftest.py`: remove `from yascheduler.db import DB`; add a session-shared bare `MessageBus()` (import `from yascheduler.application import MessageBus`); add function-scoped `pg_conn` (raw `pg8000.native.Connection` from `_db_config`), `pg_executor` (`ThreadPoolExecutor(max_workers=1)`), and `uow_factory` (callable → `PostgresUnitOfWork(_db_config, bus)`) fixtures; move `TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE` + `conn.close()` + `executor.shutdown()` into the `pg_conn` teardown. Update `pytest_collection_modifyitems` (unchanged). Update the `db` fixture: replace it with the layered set (drop `db`).
- [x] 1.2 In `tests/e2e/conftest.py`: same migration as 1.1 — drop `from yascheduler.db import DB`, add the session `MessageBus()` + function-scoped `pg_conn`/`pg_executor`/`uow_factory`; move `TRUNCATE`/close into `pg_conn` teardown; remove the `db` fixture.
- [x] 1.3 Verify both conftests import-clean and `uv run ruff check tests/integration/conftest.py tests/e2e/conftest.py` passes.

## 2. Migrate test_persistence_adapter.py

- [x] 2.1 In `tests/integration/test_persistence_adapter.py`: remove `from yascheduler.db import DB`; change each repo-construction test signature from `(db: DB)` to `(pg_conn, pg_executor)` and replace `PostgresTaskRepository(db.conn, db.executor)` → `PostgresTaskRepository(pg_conn, pg_executor)` (and `PostgresNodeRepository(db.conn, db.executor)` likewise).
- [x] 2.2 Verify the two UoW tests (`test_uow_integration`, `test_uow_rollback_integration`) are unchanged except removing the now-unused `DB` import; they already take `_db_config` + `_init_schema` and build their own `PostgresUnitOfWork(..., MessageBus())`.
- [x] 2.3 Run `uv run pytest -m integration tests/integration/test_persistence_adapter.py` — all tests pass.

## 3. Rewrite test_db_integration.py to UoW + repos

- [x] 3.1 In `tests/integration/test_db_integration.py`: replace `from yascheduler.db import DB, TaskStatus` with `from yascheduler.domain.model import Task, TaskContext, Node` and `from yascheduler.domain.model import TaskStatus as DomainTaskStatus`; import `PostgresTaskRepository`/`PostgresNodeRepository`/`PostgresUnitOfWork`/`MessageBus` as needed. Change every test signature from `(db: DB)` to `(uow_factory,)` (and `pg_conn`/`pg_executor` where direct repo construction is used).
- [x] 3.2 Migrate node tests: `db.add_node("ip","user",port=,ncpus=,cloud=,enabled=)` → `async with uow_factory() as uow: await uow.nodes.add(Node(ip=..., username=..., port=..., ncpus=..., cloud=..., enabled=...)); await uow.commit()`. `db.get_node`→`uow.nodes.get`; `get_all_nodes`→`uow.nodes.list_all`; `get_enabled_nodes`→`uow.nodes.list_enabled`; `get_disabled_nodes`→`uow.nodes.list_disabled`; `has_node`→`bool(await uow.nodes.get(ip))`; `enable_node`/`disable_node`/`remove_node`→`uow.nodes.enable/disable/remove`; `count_nodes_clouds`→`uow.nodes.count_by_cloud`; `count_nodes_by_status`→`uow.nodes.count_by_status`.
- [x] 3.3 Migrate task tests: construct domain `Task(task_id=0, label=..., context=TaskContext.from_metadata(meta), status=DomainTaskStatus(...), allocated_ip=ip)`; `db.add_task`→`uow.tasks.insert(task); uow.commit()`; `db.get_task`→`uow.tasks.get`; `set_task_running`→`get` then `task.allocate_to(ip).mark_running()` then `save`; `set_task_done`/`set_task_error`→`get`, rebuild `Task` with new `TaskContext`/status, `save`; `get_tasks_by_status`→`uow.tasks.list_by_status({DomainTaskStatus(s.value)})`; `get_tasks_by_jobs`→`uow.tasks.list_by_jobs([ids])`; `get_task_ids_by_ip_and_status`→`uow.tasks.list_ids_by_ip_and_status(ip, DomainTaskStatus(...))`.
- [x] 3.4 Rewrite `test_get_tasks_with_cloud_by_id_status` as in-test composition: `tasks = await uow.tasks.list_by_jobs(ids)`; `matching = [t for t in tasks if t.status == s]`; `ips = [t.allocated_ip for t in matching if t.allocated_ip]`; `nodes = await uow.nodes.get_by_ips(ips)`; assert cloud per allocated_ip.
- [x] 3.5 `test_add_tmp_node` → `uow.nodes.add_tmp("azure","root")`; assert returned IP `startswith("prov")` and `uow.nodes.get(ip)` shows `enabled=False, cloud="azure", username="root"`.
- [x] 3.6 Delete `test_migrate_idempotency` (the legacy `DB.migrate` path is gone; `apply_schema` is covered by `test_postgres_schema.py`).
- [x] 3.7 Update the file's GRACE-lite MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY to reflect the UoW-based scope; bump VERSION. Run `uv run pytest -m integration tests/integration/test_db_integration.py` — all remaining tests pass.

## 4. Rewrite test_full_cycle.py (e2e) to UoW + repos

- [x] 4.1 In `tests/e2e/test_full_cycle.py`: replace `from yascheduler.db import DB, TaskStatus` with domain imports (`TaskStatus as DomainTaskStatus` from `yascheduler.domain.model`); change the test signature from `(e2e_config, db: DB, ssh_container)` to `(e2e_config, uow_factory, ssh_container)`.
- [x] 4.2 `db.add_node(ip_addr=..., username=..., port=..., enabled=True)` + `db.commit()` → `async with uow_factory() as uow: await uow.nodes.add(Node(ip=..., username=..., port=..., enabled=True)); await uow.commit()`.
- [x] 4.3 `db.get_task(task_id)` → `async with uow_factory() as uow: t = await uow.tasks.get(task_id)`; `task.ip` → `task.allocated_ip`; `task.status == TaskStatus.X` → `DomainTaskStatus.X`; `task.metadata.get("local_folder")` → `task.context.local_folder`.
- [x] 4.4 `db.remove_node(ssh_container["host"])` → `async with uow_factory() as uow: await uow.nodes.remove(ssh_container["host"]); await uow.commit()`.
- [x] 4.5 Update the file's GRACE-lite headers; bump VERSION. Run `uv run pytest -m e2e tests/e2e/test_full_cycle.py` — passes against the real SSH + Postgres containers.

## 5. Delete legacy modules and the facade

- [x] 5.1 Delete `yascheduler/db.py`.
- [x] 5.2 Delete `tests/fixtures/models.py` (zero importers) and `tests/fixtures/fake_db.py` (only used by test_fake_db.py).
- [x] 5.3 Delete `tests/unit/test_fake_db.py`, `tests/unit/test_models.py`, `tests/unit/test_db.py`.
- [x] 5.4 Confirm `uv run pytest -m unit` still passes (the deleted unit tests are gone; domain + persistence-adapter coverage remains).

## 6. OpenSpec spec deltas (already authored — finalize + validate)

- [x] 6.1 Confirm the 6 delta spec files under `openspec/changes/remove-legacy-db/specs/` match the frozen proposal/design (db-wrapper REMOVED, package-facades/test-db-integration/dependency-injection/testing-unit/e2e-testing MODIFIED/REMOVED as authored).
- [x] 6.2 Run `openspec validate --changes remove-legacy-db --json` → `remove-legacy-db` `valid: true` with no issues.

## 7. Knowledge graph + architecture docs

- [x] 7.1 In `docs/knowledge-graph.xml`: remove the `<M-DB>` element (L39-62); remove `<CrossLink from="M-DB" to="M-PERSISTENCE-POSTGRES" ...>` (L926); update `<DF-PERSISTENCE>` (L901) to `M-PERSISTENCE-POSTGRES -> M-PERSISTENCE`; remove `M-DB` from `M-CLI-COMMANDS` `<depends>` (L118); scan all other `<depends>` for `M-DB` and remove any found.
- [x] 7.2 In `docs/ARCHITECTURE.md`: remove/revise the `db.py` references (L85, 119, 173, 261, 462, 536, 556, 574) so the legacy facade is no longer described as present.
- [x] 7.3 Run `python3 scripts/grace_check.py` → exit 0 (XML + source checks pass after graph edits).

## 8. Full verification

- [x] 8.1 `uv run pytest -m unit` — passes.
- [x] 8.2 `uv run pytest -m integration` — passes (testcontainers PostgreSQL).
- [x] 8.3 `uv run pytest -m e2e` — passes (testcontainers PostgreSQL + SSH).
- [x] 8.4 `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` — all pass. (These already catch any stray `import yascheduler.db`, since the module no longer exists — no bespoke grep guard is needed.)
- [x] 8.5 `openspec validate --all --json` — `remove-legacy-db` valid (the unrelated `shared-kernel-extraction` failure is pre-existing and out of scope).
- [x] 8.6 GRACE-lite validation: `python3 scripts/grace_check.py` → exit 0.