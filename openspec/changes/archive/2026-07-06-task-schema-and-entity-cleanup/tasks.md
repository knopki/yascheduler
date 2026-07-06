# Tasks: task-schema-and-entity-cleanup

## 1. Database migrations and schema snapshot

- [x] 1.1 Create `yascheduler/infra/persistence/sql/migrations/006_rename_label_to_title.sql` with `ALTER TABLE yascheduler_tasks RENAME COLUMN label TO title;`
- [x] 1.2 Create `yascheduler/infra/persistence/sql/migrations/007_add_created_updated_at.sql` adding `created_at`/`updated_at` columns (`TIMESTAMPTZ NOT NULL DEFAULT NOW()`), creating the `yascheduler_touch_updated_at()` trigger function, and installing the `yascheduler_tasks_touch_updated_at` `BEFORE UPDATE` trigger (with `DROP TRIGGER IF EXISTS` guard)
- [x] 1.3 Create `yascheduler/infra/persistence/sql/migrations/008_status_to_enum.sql` with `CREATE TYPE task_status AS ENUM ('TO_DO', 'RUNNING', 'DONE')`, `ALTER TABLE yascheduler_tasks ALTER COLUMN status TYPE task_status USING CASE status WHEN 0 THEN 'TO_DO' WHEN 1 THEN 'RUNNING' WHEN 2 THEN 'DONE' END`, and `ALTER TABLE yascheduler_tasks ALTER COLUMN status SET DEFAULT 'TO_DO'`
- [x] 1.4 Create `yascheduler/infra/persistence/sql/migrations/009_drop_allocated_ip.sql` with `ALTER TABLE yascheduler_tasks DROP COLUMN IF EXISTS ip;`
- [x] 1.5 Update `yascheduler/infra/persistence/sql/schema.sql`: add `CREATE TYPE task_status AS ENUM ('TO_DO', 'RUNNING', 'DONE')` before `CREATE TABLE yascheduler_tasks`; rename `label` → `title` in the `CREATE TABLE yascheduler_tasks` statement; change `status SMALLINT NOT NULL DEFAULT 0` → `status task_status NOT NULL DEFAULT 'TO_DO'`; drop the `ip` column; add `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` and `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`; add the `yascheduler_touch_updated_at()` function and `yascheduler_tasks_touch_updated_at` trigger after the `CREATE TABLE yascheduler_tasks` statement; update the `last_migration` CONSTANT from `'005'` to `'009'`

## 2. Domain entity changes

- [x] 2.1 In `yascheduler/domain/model.py`, remove `allocated_ip` from `Task` fields; add `created_at: datetime` and `updated_at: datetime` fields (positioned before `_events`); keep `allocated_node_id` as the sole allocation signal
- [x] 2.2 In `yascheduler/domain/model.py`, remove `allocated_ip` from `NewTask` fields (it was already defaulting to None and unused pre-persistence); `NewTask` keeps `label`, `context`, `status`, `allocated_node_id`
- [x] 2.3 Update `Task.allocate_to` guard: `if self.allocated_ip is not None` → `if self.allocated_node_id is not None` (raise `TaskAlreadyAllocatedError`); the `replace(self, allocated_node_id=node.node_id, ...)` call drops `allocated_ip=`
- [x] 2.4 Update `Task.mark_running` guard: `if self.allocated_ip is None` → `if self.allocated_node_id is None` (raise `TaskNotAllocatedError`)
- [x] 2.5 Update the `Task` MODULE_CONTRACT/MODULE_MAP in `model.py` to reflect the new field list (drop `allocated_ip`, add `created_at`/`updated_at`); add a CHANGE_SUMMARY entry for the task-schema-and-entity-cleanup change
- [x] 2.6 Update the `NewTask` CONTRACT in `model.py` to drop `allocated_ip` from the INPUTS list
- [x] 2.7 Add focused unit tests for the updated guards: `allocate_to` raises on `allocated_node_id is not None` (not `allocated_ip`); `mark_running` raises when `allocated_node_id is None` (not `allocated_ip`); `allocate_to` returns a `Task` with no `allocated_ip` attribute

## 3. Persistence layer — SQL files

- [x] 3.1 Update `yascheduler/infra/persistence/sql/task/insert.sql`: rename `label` → `title` in column list and `:label` → `:title` param; remove `ip` column and `:ip` param; change `status` write to accept the enum label string (no SQL change needed — the param is just bound as a string now); `RETURNING` clause includes `task_id, title, status, metadata, allocated_node_id, created_at, updated_at` (was `task_id, label, ip, status, metadata, allocated_node_id`)
- [x] 3.2 Update `yascheduler/infra/persistence/sql/task/update_by_id.sql`: rename `label` → `title` in SET and `:label` → `:title` param; remove `ip = :ip` from SET; change `status = :status` (param now bound as enum-label string); `RETURNING` clause stays `task_id` only (the trigger sets `updated_at`; `save` does not refresh)
- [x] 3.3 Update `yascheduler/infra/persistence/sql/task/get_by_id.sql`: column list renames `label` → `title`, removes `ip`, adds `created_at`, `updated_at`
- [x] 3.4 Update `yascheduler/infra/persistence/sql/task/list_by_status.sql`: column list renames `label` → `title`, removes `ip`, adds `created_at`, `updated_at`; change `cast(:statuses AS int[])` → `cast(:statuses AS task_status[])`
- [x] 3.5 Update `yascheduler/infra/persistence/sql/task/list_by_jobs.sql`: column list renames `label` → `title`, removes `ip`, adds `created_at`, `updated_at`
- [x] 3.6 Rename `yascheduler/infra/persistence/sql/task/get_ids_by_ip_and_status.sql` → `get_ids_by_node_id_and_status.sql`; change predicate `WHERE ip = :ip AND status = :status` → `WHERE allocated_node_id = :node_id AND status = :status`
- [x] 3.7 `yascheduler/infra/persistence/sql/task/update_status.sql`: change `status = :status` binding (param now bound as enum-label string, no SQL syntax change)
- [x] 3.8 `yascheduler/infra/persistence/sql/task/count_by_status.sql`: no SQL change (`GROUP BY status` works with enum); verify the read-side mapping in step 4

## 4. Persistence layer — Python repository

- [x] 4.1 In `yascheduler/infra/persistence/postgres.py` `PostgresTaskRepository._row_to_task`: remove `allocated_ip=row.get("ip") or None`; add `created_at=row["created_at"]` and `updated_at=row["updated_at"]` reads; change `label=row.get("label", "")` → `label=row.get("title", "")` (DB column is now `title`); change `status=TaskStatus(row["status"])` → `status=TaskStatus[row["status"]]` (name lookup, was int cast)
- [x] 4.2 In `PostgresTaskRepository.save`: remove `ip=task.allocated_ip`; change `label=task.label` → `title=task.label` (param rename, value unchanged); change `status=task.status.value` → `status=task.status.name` (enum-label string, was int); keep `node_id=task.allocated_node_id.value` (or None)
- [x] 4.3 In `PostgresTaskRepository.insert`: remove `ip=new_task.allocated_ip`; change `label=new_task.label` → `title=new_task.label`; change `status=new_task.status.value` → `status=new_task.status.name`; keep `node_id=new_task.allocated_node_id.value` (or None)
- [x] 4.4 In `PostgresTaskRepository.update_status`: change `status=status.value` → `status=status.name`
- [x] 4.5 In `PostgresTaskRepository.list_by_status`: change `statuses=[s.value for s in statuses]` → `statuses=[s.name for s in statuses]`
- [x] 4.6 In `PostgresTaskRepository.count_by_status`: change `TaskStatus(row["status"])` → `TaskStatus[row["status"]]` (name lookup, was int cast — pg8000 returns the enum label as a `str`)
- [x] 4.7 Rename `PostgresTaskRepository.list_ids_by_ip_and_status` → `list_ids_by_node_id_and_status(self, node_id: NodeId, status: TaskStatus)`; change the `load_query("task/get_ids_by_ip_and_status")` → `load_query("task/get_ids_by_node_id_and_status")`; change `ip=ip` param → `node_id=node_id.value`; change `status=status.value` → `status=status.name`
- [x] 4.8 In `yascheduler/domain/ports.py`, rename `TaskRepository` Protocol method `list_ids_by_ip_and_status(ip: str, status: TaskStatus) -> list[TaskId]` → `list_ids_by_node_id_and_status(node_id: NodeId, status: TaskStatus) -> list[TaskId]` (port-level rename matching the adapter in 4.7)
- [x] 4.9 Update the `PostgresTaskRepository` MODULE_CONTRACT/MODULE_MAP and the `_row_to_task` CONTRACT in `postgres.py` to reflect the new method name, the enum read/write, and the dropped `allocated_ip`; update the `TaskRepository` port CONTRACT in `ports.py` if present; add a CHANGE_SUMMARY entry
- [x] 4.10 Add/update unit tests for `_row_to_task` (enum name lookup, `title`→`label`, `created_at`/`updated_at` reads, no `allocated_ip`), `count_by_status` (name lookup), `list_ids_by_node_id_and_status` (node_id param), and a Protocol-conformance test that `PostgresTaskRepository` satisfies the updated `TaskRepository` Protocol (with `list_ids_by_node_id_and_status`)

## 5. Use case — query_tasks

- [x] 5.1 In `yascheduler/application/query_tasks.py`, change `query_tasks` return type from `list[Task]` to `tuple[list[Task], dict[NodeId, Node]]`; after fetching tasks inside the UoW, batch-load nodes via `uow.nodes.get_by_ids(list({t.allocated_node_id for t in tasks if t.allocated_node_id is not None}))` when the set is non-empty (else `{}`); return `(tasks, nodes_by_id)`
- [x] 5.2 Update the `query_tasks` CONTRACT (PURPOSE, OUTPUTS, SIDE_EFFECTS) and MODULE_MAP in `query_tasks.py` to reflect the tuple return and the node batch-load; add a CHANGE_SUMMARY entry
- [x] 5.3 Update `tests/unit/test_query_tasks.py` to assert the new return shape `(list[Task], dict[NodeId, Node])` across all scenarios (query by statuses, query by jobs, both-raises, neither-empty, all-unallocated-returns-empty-nodes)

## 6. Client facade — Yascheduler

- [x] 6.1 In `yascheduler/entrypoints/client.py` `queue_get_tasks_async`: unpack `tasks, nodes_by_id = await query_tasks(job_ids, statuses, deps.uow_factory)` and pass `nodes_by_id` to `_task_to_dict`
- [x] 6.2 Update `_task_to_dict(t: Task)` → `_task_to_dict(t: Task, nodes_by_id: dict[NodeId, Node])`: drop `"ip"` and `"cloud"` keys; add `"node"` key built from `nodes_by_id.get(t.allocated_node_id)` (or `None`); the `node` dict has `{ip, port, username, cloud}` from the resolved `Node`; keep `task_id`, `label`, `status`, `metadata` unchanged
- [x] 6.3 Update the `queue_get_tasks_async` and `_task_to_dict` CONTRACTs and the MODULE_MAP in `client.py`; add a CHANGE_SUMMARY entry
- [x] 6.4 Add/update unit tests for `_task_to_dict` with `nodes_by_id` (allocated task → nested `node` with all four fields; unallocated task → `node: null`; flat `ip`/`cloud` keys absent)

## 7. CLI — yastatus

- [x] 7.1 In `yascheduler/entrypoints/cli/check_status.py` `_render_info`: change `ip={task.allocated_ip or "-"}` → `node_id={task.allocated_node_id}` (or `node_id=-` when None)
- [x] 7.2 In `check_status.py` `_render_json`: drop flat `allocated_ip`/`port`/`cloud` keys; add `created_at` and `updated_at` (ISO-8601 via `.isoformat()`); add nested `node` object `{ip, port, username, cloud}` built from `nodes_by_id.get(task.allocated_node_id)` (or `None`); keep `task_id`, `status`, `label`, `engine`, `local_folder`, `remote_folder`
- [x] 7.3 In `check_status.py` `_render_view` (verbose): change the display line that reads `task.allocated_ip or ""` to read `node.ip` from the resolved `Node` (already available via `nodes_by_id.get(task.allocated_node_id)`)
- [x] 7.4 Update the `_render_json` CONTRACT (PURPOSE, INPUTS — already takes `nodes_by_id`, OUTPUTS — new shape) and the `_render_info` CONTRACT in `check_status.py`; add a CHANGE_SUMMARY entry
- [x] 7.5 Update the `check_status.py` MODULE_CONTRACT/MODULE_MAP if public surface changed; update stale CHANGE_SUMMARY entries that mention `allocated_ip`
- [x] 7.6 Add/update unit tests for `_render_json` (new nested-`node` shape, `created_at`/`updated_at` ISO-8601, flat fields absent, `node: null` for unallocated), `_render_info` (`node_id=` field)

## 8. CLI — manage_node call sites

- [x] 8.1 In `yascheduler/entrypoints/cli/manage_node.py` `_remove_node_hard`: change `await uow.tasks.list_ids_by_ip_and_status(node.ip, TaskStatus.RUNNING)` → `await uow.tasks.list_ids_by_node_id_and_status(node.node_id, TaskStatus.RUNNING)`
- [x] 8.2 In `manage_node.py` `_remove_node_soft`: same rename as 8.1
- [x] 8.3 Update the `_remove_node_hard` and `_remove_node_soft` CONTRACTs (INPUTS mention `node.ip keys the task lookup` → `node.node_id keys the task lookup`); add a CHANGE_SUMMARY entry
- [x] 8.4 Update `tests/` covering `_remove_node_hard`/`_remove_node_soft` to assert the `list_ids_by_node_id_and_status(node.node_id, ...)` call (was `list_ids_by_ip_and_status(node.ip, ...)`)

## 9. Orchestrator and abandon_node cleanup

- [x] 9.1 In `yascheduler/application/orchestrator.py:454` `ip = task.allocated_ip or ""`: replace with `node.ip` via the resolved node (the orchestrator resolves the node already), or drop the `ip` from the log line — decide during implementation (trivial)
- [x] 9.2 Verify `yascheduler/application/abandon_node.py` has no lingering `allocated_ip` reads (the code was already rekeyed to `allocated_node_id` per its CHANGE_SUMMARY; confirm and clean up any stale text)
- [x] 9.3 Update any CHANGE_SUMMARY entries in `orchestrator.py`/`abandon_node.py` that mention `allocated_ip` to reflect the removal

## 10. AiiDA plugin confirmation

- [x] 10.1 Grep `entrypoints/aiida_plugin.py` (and any AiiDA-related modules) for reads of `yastatus --json` output or `queue_get_tasks()["ip"]`/`["allocated_ip"]`; confirm none exist (the plugin parses `yastatus` default mode only). Document the finding in the change summary.

## 11. Integration tests

- [x] 11.1 Add an integration test (testcontainers) for migrations 006–009 applied in order against a legacy DB at migration `005`: assert `label`→`title` rename, `created_at`/`updated_at` columns present, trigger sets `updated_at` on UPDATE, `status` column is `task_status` enum with correct labels, `ip` column dropped
- [x] 11.2 Add an integration test that `apply_schema` on a fresh DB produces the final shape (enum type, trigger, columns) and seeds `last_migration = '009'`; subsequent `apply_migrations` is a no-op
- [x] 11.3 Add an integration test for `PostgresTaskRepository`: `insert` returns a `Task` with `created_at`/`updated_at` set; `save` (UPDATE) triggers `updated_at` to advance; `list_by_status` with `cast(:statuses AS task_status[])` works; `count_by_status` returns name-lookup keys; `list_ids_by_node_id_and_status` filters by `allocated_node_id`
- [x] 11.4 Add an integration test that migration 008 fails (and rolls back) when a row has an out-of-range `status` integer (e.g. 3) — the `USING CASE` maps to NULL, `NOT NULL` violates, migration fails, DB stays at migration `007`
- [x] 11.5 Update `tests/integration/test_db_integration.py:518` which calls `list_ids_by_ip_and_status` to call `list_ids_by_node_id_and_status` instead
- [x] 11.6 Update `tests/unit/test_persistence_allocated_node_id.py:226-229` which loads `task/get_ids_by_ip_and_status` to load `task/get_ids_by_node_id_and_status` and assert the new predicate

## 12. E2E tests

- [x] 12.1 Grep `tests/e2e/` for assertions on `task.allocated_ip`; list every occurrence
- [x] 12.2 Rewrite e2e assertions that read `task.allocated_ip` to read `task.allocated_node_id` + a node lookup (or the new `node.ip` JSON field / `node.ip` facade dict field)
- [x] 12.3 Update `tests/e2e/test_hetzner_live.py` and `test_full_cycle.py` task-shape assertions to include `created_at`/`updated_at` and the nested `node` object (where applicable)

## 13. Knowledge graph and GRACE-lite

- [x] 13.1 Update `docs/knowledge-graph.xml` `M-DOMAIN-MODEL` annotations for `Task`/`NewTask` (drop `allocated_ip`, add `created_at`/`updated_at`); update `M-PERSISTENCE-SQL`/`class-TaskRepository` annotation to reflect `list_ids_by_node_id_and_status` and the enum read/write; add CrossLinks if dependency structure changed (it did not — private-only field changes, but the method rename is public-surface on the repository)
- [x] 13.2 Run `python3 scripts/grace_check.py` and fix any XML/markup drift introduced by the contract/CHANGE_SUMMARY edits
- [x] 13.3 Run `openspec validate --all --json` and confirm it passes

## 14. Static checks and final verification

- [x] 14.1 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`; fix any issues
- [x] 14.2 Run `uv run pytest -m unit` and confirm all unit tests pass
- [x] 14.3 Run `uv run pytest -m integration` and confirm all integration tests pass (requires Docker for testcontainers)
- [x] 14.4 Run `uv run pytest -m e2e` and confirm all e2e tests pass (requires Docker; skip cloud-only tests unless configured)
- [x] 14.5 Run `openspec validate --all --json` one final time after all spec/code edits and confirm it passes