## 1. Schema — migration 004 and schema.sql snapshot

- [x] 1.1 Create `yascheduler/infra/persistence/sql/migrations/004_add_allocated_node_id.sql` with the `ALTER TABLE yascheduler_tasks ADD COLUMN allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL` statement and the `UPDATE yascheduler_tasks t SET allocated_node_id = (SELECT n.node_id FROM yascheduler_nodes n WHERE n.ip = t.ip) WHERE t.ip IS NOT NULL` backfill (two statements, one file — applied in one transaction by the migration runner)
- [x] 1.2 Update `yascheduler/infra/persistence/sql/schema.sql`: add `allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL` to the `CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement; bump the DO block `last_migration` CONSTANT from `'003'` to `'004'`
- [x] 1.3 Update the `START_CHANGE_SUMMARY` in `schema.sql` (if present) or add a brief comment noting migration 004 and the new column

## 2. SQL — task query files (5 files)

- [x] 2.1 `sql/task/insert.sql`: add `allocated_node_id` to the INSERT column list (`label, metadata, ip, status, allocated_node_id`), add `:node_id` to the VALUES list, add `allocated_node_id` to the RETURNING clause (`RETURNING task_id, label, ip, status, metadata, allocated_node_id`)
- [x] 2.2 `sql/task/update_by_id.sql`: add `allocated_node_id = :node_id` to the SET clause (alongside `label`, `status`, `ip`, `metadata`); RETURNING clause stays `RETURNING task_id`
- [x] 2.3 `sql/task/get_by_id.sql`: add `allocated_node_id` to the SELECT column list (`task_id, label, ip, status, metadata, allocated_node_id`)
- [x] 2.4 `sql/task/list_by_status.sql`: add `allocated_node_id` to the SELECT column list
- [x] 2.5 `sql/task/list_by_jobs.sql`: add `allocated_node_id` to the SELECT column list
- [x] 2.6 Verify `sql/task/update_status.sql` and `sql/task/get_ids_by_ip_and_status.sql` and `sql/task/count_by_status.sql` are NOT touched (status-only / task_id-only / aggregate — no `allocated_node_id`)

## 3. Domain model — Task, NewTask, allocate_to

- [x] 3.1 `yascheduler/domain/model.py`: add `allocated_node_id: NodeId | None = None` field to `NewTask` (after `allocated_ip`); update the `START_CONTRACT: NewTask` INPUTS list to include `allocated_node_id: NodeId | None`
- [x] 3.2 `yascheduler/domain/model.py`: add `allocated_node_id: NodeId | None = None` field to `Task` (after `allocated_ip`, before `_events`); update the `START_CONTRACT: Task` INPUTS list to include `allocated_node_id: NodeId | None`
- [x] 3.3 `yascheduler/domain/model.py`: change `Task.allocate_to` signature from `allocate_to(self, ip: str)` to `allocate_to(self, node: Node)`; update the body to `return replace(self, allocated_ip=node.ip, allocated_node_id=node.node_id)`; keep the `TaskAlreadyAllocatedError` guard on `self.allocated_ip is not None`; update the `START_CONTRACT: Task.allocate_to` INPUTS (`{ node: Node - the node to bind (carries ip and node_id) }`) and OUTPUTS (`{ Task - new Task with allocated_ip and allocated_node_id set }`)
- [x] 3.4 Add `Node` to the import list in `model.py` if not already imported (allocate_to now references `Node` in its signature) — verify it's available (it's in the same module, so likely just the type annotation order)
- [x] 3.5 Update the `START_CHANGE_SUMMARY` in `model.py` with a new LAST_CHANGE entry describing the `allocated_node_id` field addition and the `allocate_to(node)` signature change
- [x] 3.6 Update the `START_MODULE_MAP` in `model.py` if the exported surface description for `NewTask`/`Task`/`allocate_to` changed substantively

## 4. Persistence adapter — PostgresTaskRepository

- [x] 4.1 `yascheduler/infra/persistence/postgres.py` `PostgresTaskRepository.insert`: add `node_id=new_task.allocated_node_id.value if new_task.allocated_node_id else None` to the `_run` kwargs (alongside `label`, `metadata`, `ip`, `status`); update the `START_CONTRACT: insert` SIDE_EFFECTS to mention binding `allocated_node_id`
- [x] 4.2 `yascheduler/infra/persistence/postgres.py` `PostgresTaskRepository.save`: add `node_id=task.allocated_node_id.value if task.allocated_node_id else None` to the `_run` kwargs (alongside `task_id`, `label`, `status`, `ip`, `metadata`); update the `START_CONTRACT: save` SIDE_EFFECTS to mention binding `allocated_node_id`
- [x] 4.3 `yascheduler/infra/persistence/postgres.py` `_row_to_task`: add `allocated_node_id=NodeId(int(row["allocated_node_id"])) if row.get("allocated_node_id") else None` to the `Task(...)` constructor call; update the `START_CONTRACT: _row_to_task` INPUTS (`row with keys task_id, label, ip, status, metadata, allocated_node_id`) and OUTPUTS (`Task carries task_id: TaskId and allocated_node_id: NodeId | None`)
- [x] 4.4 Verify `NodeId` is imported in `postgres.py` (it likely already is, from the prior node-id changes — confirm)
- [x] 4.5 Update the `START_CHANGE_SUMMARY` in `postgres.py` with a new LAST_CHANGE entry describing the `allocated_node_id` bind/read

## 5. Application — allocate_task.py

- [x] 5.1 `yascheduler/application/allocate_task.py` `_find_free_machines`: change the return type annotation from `list[MachineSession]` to `list[tuple[MachineSession, Node]]`; replace `enabled_ips = {n.ip for n in enabled_nodes}` with `nodes_by_ip = {n.ip: n for n in enabled_nodes}`; change the list comprehension to `[(s, nodes_by_ip[s.machine.ip]) for s in repository.list_free(platforms=list(engine.platforms)) if s.machine.ip in nodes_by_ip and s.machine.ip not in busy_node_ips]`; update the `START_CONTRACT: _find_free_machines` OUTPUTS (`list[tuple[MachineSession, Node]]` — paired by ip, Node carries node_id) and SIDE_EFFECTS (mention `nodes_by_ip` dict and the ip-matching ambiguity note)
- [x] 5.2 `yascheduler/application/allocate_task.py` `_try_start_on_machine`: add `node: Node` parameter to the signature (after `session: MachineSession`); change `task = task.allocate_to(session.ip).mark_running()` to `task = task.allocate_to(node).mark_running()`; add `node_id=%s` to the two log lines (`task_id=%s ip=%s` → `task_id=%s ip=%s node_id=%s`, passing `node.node_id`); update the `START_CONTRACT: _try_start_on_machine` INPUTS to include `node: Node - the Node paired with the session (carries node_id for allocate_to)`
- [x] 5.3 `yascheduler/application/allocate_task.py` `_allocate_free_machine`: change the loop from `for session in free_sessions:` to `for session, node in free_sessions:`; update the `_try_start_on_machine` call to pass `node` (e.g. `_try_start_on_machine(session, node, engine, task, ...)`); update the `START_CONTRACT: _allocate_free_machine` SIDE_EFFECTS if the per-session description references the session alone
- [x] 5.4 Update the `START_CHANGE_SUMMARY` in `allocate_task.py` with a new LAST_CHANGE entry describing `_find_free_machines` returning pairs and `_try_start_on_machine` taking `(session, node)`

## 6. GRACE-lite — knowledge graph

- [x] 6.1 Update `docs/knowledge-graph.xml`: `M-DOMAIN-MODEL` annotations — `type-Task` and `type-NewTask` PURPOSE mention `allocated_node_id: NodeId | None`; `fn-allocate_to` PURPOSE mentions "binds allocated_ip and allocated_node_id from a Node"
- [x] 6.2 Update `docs/knowledge-graph.xml`: `M-APPLICATION-ALLOCATE` annotations — `fn-_find_free_machines` PURPOSE mentions "returns list[(MachineSession, Node)]"; `fn-_try_start_on_machine` PURPOSE mentions "takes (session, node), calls allocate_to(node)"
- [x] 6.3 Update `docs/knowledge-graph.xml`: `M-PERSISTENCE-POSTGRES` annotations — note `allocated_node_id` bind/read in `insert`/`save`/`_row_to_task`
- [x] 6.4 Run `python3 scripts/grace_check.py` and confirm exit 0 (XML + source checks pass after the contract/summary updates)

## 7. Tests — unit (domain model)

- [x] 7.1 `tests/unit/test_domain_model.py` (or equivalent): add `test_allocate_to_takes_node_and_binds_both_fields` — construct a `Node(node_id=NodeId(7), ip="10.0.0.1", ...)`, call `task.allocate_to(node)`, assert returned Task has `allocated_ip="10.0.0.1"` AND `allocated_node_id=NodeId(7)`; assert original status preserved
- [x] 7.2 Add `test_allocate_to_rejects_already_allocated` — call `allocate_to(node)` on a task with `allocated_ip` already set, assert `TaskAlreadyAllocatedError` raised; assert neither field changed
- [x] 7.3 Add `test_new_task_has_allocated_node_id_default_none` — instantiate `NewTask(label=..., context=...)`, assert `allocated_node_id is None`
- [x] 7.4 Add `test_task_with_context_preserves_allocated_node_id` — call `task.with_context(new_ctx)` on a task with `allocated_node_id=NodeId(5)`, assert the returned Task retains `allocated_node_id=NodeId(5)`
- [x] 7.5 Update any existing `test_allocate_to*` tests that call `allocate_to("10.0.0.1")` (string ip) to call `allocate_to(node)` with a constructed `Node` instead

## 8. Tests — unit (application use cases)

- [x] 8.1 `tests/unit/test_application_use_cases.py` `TestAllocateTask`: update `_find_free_machines` tests to assert the return type is `list[tuple[MachineSession, Node]]` and each `Node` carries `node_id`; update mocks of `uow.nodes.list_enabled` to return `Node` objects with `node_id`
- [x] 8.2 Add `test_find_free_machines_pairs_session_with_node_by_ip` — mock `list_enabled` to return two Nodes (different ips) and `repository.list_free` to return two sessions matching those ips; assert the result pairs each session with the correct Node
- [x] 8.3 Add `test_find_free_machines_dup_ip_collapses_to_one_node` — mock `list_enabled` to return two Nodes with the SAME ip (dup-IP), mock `list_free` to return one session for that ip; assert the result has one pair and the Node is one of the two (last-wins) — documents the same-ambiguity-as-today behavior
- [x] 8.4 Update `_try_start_on_machine` / `_allocate_free_machine` tests: pass `(session, node)` pairs; assert `task.allocate_to(node)` is called (not `allocate_to(ip)`); assert `uow.tasks.save` receives a task with `allocated_node_id` set
- [x] 8.5 Add `test_try_start_on_machine_logs_node_id` — capture the log, assert `node_id=%s` appears alongside `ip=%s` in the allocation log line

## 9. Tests — unit (postgres persistence)

- [x] 9.1 `tests/unit/test_persistence_postgres.py` (or equivalent): add `test_row_to_task_reads_allocated_node_id` — pass a row dict with `allocated_node_id=5`, assert returned `Task.allocated_node_id == NodeId(5)`
- [x] 9.2 Add `test_row_to_task_handles_null_allocated_node_id` — pass a row with `allocated_node_id=None` (or missing key), assert `Task.allocated_node_id is None`
- [x] 9.3 Add `test_insert_binds_allocated_node_id` — mock the `_run` to capture kwargs, call `insert(NewTask(..., allocated_node_id=NodeId(5)))`, assert `node_id=5` is in the kwargs
- [x] 9.4 Add `test_save_binds_allocated_node_id` — mock `_run`, call `save(task)` with `task.allocated_node_id=NodeId(7)`, assert `node_id=7` in kwargs
- [x] 9.5 Add `test_save_binds_null_allocated_node_id` — call `save(task)` with `task.allocated_node_id=None`, assert `node_id=None` in kwargs
- [x] 9.6 Verify the SQL file content tests (if any exist that assert on column lists) check `allocated_node_id` in `insert.sql`/`update_by_id.sql`/`get_by_id.sql`/`list_by_status.sql`/`list_by_jobs.sql` SELECT/INSERT/RETURNING clauses

## 10. Tests — integration (migration + schema)

- [x] 10.1 `tests/integration/` (testcontainers PostgreSQL): add `test_migration_004_adds_allocated_node_id_column` — run `apply_schema` + `apply_migrations` on a fresh DB, assert `yascheduler_tasks.allocated_node_id` column exists, is nullable, and has the FK with `ON DELETE SET NULL` action
- [x] 10.2 Add `test_migration_004_backfills_existing_tasks` — seed a DB at migration 003 with tasks having non-NULL `ip` values and matching `yascheduler_nodes` rows, run `apply_migrations`, assert each task's `allocated_node_id` matches the node with the same ip
- [x] 10.3 Add `test_migration_004_leaves_unallocated_tasks_null` — seed a task with `ip IS NULL`, run migrations, assert its `allocated_node_id` stays NULL
- [x] 10.4 Add `test_fk_on_delete_set_null` — insert a node and a task referencing it via `allocated_node_id`, delete the node row, assert the task's `allocated_node_id` became NULL (and the task row + `allocated_ip` are preserved)
- [x] 10.5 Add `test_fresh_db_seeds_to_004` — run `apply_schema` on empty DB, assert `yascheduler_migrations` has `migration_id='004'` and `apply_migrations` skips migration 004 (already seeded)
- [x] 10.6 Add `test_schema_sql_create_table_includes_allocated_node_id` — inspect `schema.sql`, assert `CREATE TABLE IF NOT EXISTS yascheduler_tasks` includes `allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL`

## 11. Verification

- [x] 11.1 Run `uv run pytest -m unit` — all unit tests pass (including the new domain/application/persistence tests)
- [x] 11.2 Run `uv run pytest -m integration` — all integration tests pass (including the new migration 004 / schema / FK tests)
- [x] 11.3 Run `uv run zuban check` — type checks pass (`allocate_to(node: Node)` signature, `_find_free_machines` return type, `allocated_node_id` field types all check cleanly)
- [x] 11.4 Run `uv run ruff check .` and `uv run ruff format --check .` — lint/format pass
- [x] 11.5 Run `uv run lint-imports` — import layering unchanged (no new cross-layer imports; `Node` is domain-internal)
- [x] 11.6 Run `openspec validate --all --json` — all specs valid after the change
- [x] 11.7 Run GRACE-lite validation (`python3 scripts/grace_check.py`) — exit 0 (task 6.4)
- [x] 11.8 Confirm no read-path site was accidentally changed: grep `allocated_ip` usage in `orchestrator.py`, `abandon_node.py`, `show_nodes.py`, `check_status.py`, `client.py` — all should still read `allocated_ip` (unchanged); only `allocate_task.py` (`_try_start_on_machine`) and the domain model / persistence adapter should reference `allocated_node_id`