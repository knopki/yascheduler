## 1. Domain events and exceptions

- [x] 1.1 Remove `has_errors` field from `TaskCompleted` in `yascheduler/domain/events.py`; update the module contract/map/change-summary
- [x] 1.2 Remove `TaskAlreadyAllocatedError` and `TaskNotAllocatedError` from `yascheduler/domain/exceptions.py`; update the module contract/map/change-summary; verify no remaining imports of them across the codebase

## 2. Task entity rewrite (`yascheduler/domain/model.py`)

- [x] 2.1 Rename `_events` field to `events` (public, `repr=True`) on `Task`; update the `Task` dataclass field declaration and the `START_CONTRACT: Task` INPUTS line
- [x] 2.2 Add `materialize_task(task: Task) -> Task` free function with `START_CONTRACT: materialize_task` — constructs `TaskCreated` from `task.task_id`/`task.webhook_url`/`task.webhook_custom_params`/`task.engine` and returns `replace(task, events=(event,))`
- [x] 2.3 Implement `Task.run(self, node_id: NodeId, remote_folder: str) -> Task` — guard `status != TO_DO` → `TaskNotTodoError`; `replace` setting `allocated_node_id`, `remote_folder`, `status=RUNNING`, and appending `TaskAllocated(node_id=node_id, engine_name=self.engine)` to `events`
- [x] 2.4 Implement `Task.reject(self, reason: str) -> Task` — guard `status != TO_DO` → `TaskNotTodoError`; `replace` setting `status=DONE`, `error=reason`, appending `TaskFailed(reason=reason)`
- [x] 2.5 Implement `Task.complete(self, *, local_folder: str, remote_folder: str) -> Task` — guard `status != RUNNING` → `TaskNotRunningError`; `replace` setting `status=DONE`, `local_folder`, `remote_folder`, appending `TaskCompleted(local_folder=local_folder)`
- [x] 2.6 Implement `Task.fail(self, reason: str, *, local_folder: str, remote_folder: str) -> Task` — guard `status != RUNNING` → `TaskNotRunningError`; `replace` setting `status=DONE`, `error=reason`, `local_folder`, `remote_folder`, appending `TaskFailed(reason=reason)`
- [x] 2.7 Implement `Task.abandon(self, node_id: NodeId | None, error: str = "node is gone") -> Task` — guard `status != RUNNING` → `TaskNotRunningError`; `replace` setting `status=DONE`, `error=error`; append `TaskAbandoned(node_id=node_id)` to `events` only when `node_id is not None`
- [x] 2.8 Remove `Task.allocate_to`, `mark_running`, `with_remote_folder`, `with_download_results`, `with_event` (including the 5 `@overload` decls), `record_event`, `pull_events`; remove the `_E` TypeVar if no longer used
- [x] 2.9 Update `START_MODULE_MAP`, `START_MODULE_CONTRACT`, and `START_CHANGE_SUMMARY` for `model.py` to reflect the new surface
- [x] 2.10 Update `yascheduler/domain/__init__.py` exports if `materialize_task` should be public (add to `__all__`); verify `TaskAlreadyAllocatedError`/`TaskNotAllocatedError` are no longer exported

## 3. Persistence layer

- [x] 3.1 Update `PostgresTaskRepository.insert` in `yascheduler/infra/persistence/postgres.py` to call `materialize_task(self._row_to_task(rows[0]))`; update the `insert` contract and change-summary; verify `_row_to_task` still sets `events=()`
- [x] 3.2 Simplify `PostgresUnitOfWork.collect_events` in `yascheduler/infra/persistence/postgres_uow.py` — read `task.events` directly, clear `_saved_tasks`, no `pull_events` call, no clean-task re-append; update the `collect_events` contract and change-summary

## 4. Use-case call-site rewrites

- [x] 4.1 `yascheduler/application/submit_task.py` — remove `with_remote_folder` + `with_event(TaskCreated)` chain; the `insert` call now returns a Task with `TaskCreated` already in `events`; just `save` + `commit`; remove the `datetime.now().strftime` remote_folder construction (moved to allocate); update contract/change-summary
- [x] 4.2 `yascheduler/application/allocate_task.py` `_validate_engine` — replace `task.reject("unsupported engine").with_event(TaskFailed, reason="unsupported engine")` with `task.reject("unsupported engine")`; update contract
- [x] 4.3 `yascheduler/application/allocate_task.py` `_try_start_on_machine` — compute `remote_folder = str(remote_tasks_dir / f"{dt_str}_{task.task_id}")` (needs `remote_tasks_dir` + `datetime` — add to function signature or thread from `allocate_task`); replace `task.allocate_to(node).mark_running()` + later `task.with_event(TaskAllocated, ...)` with `task.run(node.node_id, remote_folder)`; update contract/change-summary
- [x] 4.4 `yascheduler/application/allocate_task.py` `allocate_task` — thread `remote_tasks_dir` through to `_try_start_on_machine` (signature change); update the `allocate_task` contract INPUTS
- [x] 4.5 `yascheduler/application/consume_task.py` `_decide_finalisation` — replace `task.with_download_results(...)` + `task.fail(err).with_event(TaskFailed, reason=err)` with `task.fail(err, local_folder=..., remote_folder=...)`; replace `task.complete().with_event(TaskCompleted, local_folder=..., has_errors=False)` with `task.complete(local_folder=..., remote_folder=...)`; update contract/change-summary
- [x] 4.6 `yascheduler/application/orchestrator.py` `_task_consumer_consumer` — replace `task = task.fail("node is gone")` + conditional `task = task.with_event(TaskAbandoned, node_id=node_id)` with `task = task.abandon(node_id)` (single call; `abandon` handles the `node_id is None` edge); remove the `TaskAbandoned` import if no longer used directly; update contract/change-summary
- [x] 4.7 `yascheduler/application/orchestrator.py` `Orchestrator.__init__` / `start` — thread `remote_tasks_dir` into `allocate_task` calls (the `_allocator_consumer` passes it through); update the `allocate_task` call in `_allocator_consumer`

## 5. CLI / facade scan for `remote_folder` on TO_DO

- [x] 5.1 Grep `yascheduler/cli/` and `yascheduler/` (facade) for `remote_folder` reads; identify any renderer that assumes non-NULL on TO_DO tasks; update to tolerate NULL (the DB column is nullable); document findings in the change summary
  - Findings: `entrypoints/cli/check_status.py` `_display_remote_output` already NULL-tolerant (`if not remote_folder: print("OUTDATED TASK, SKIPPING"); return None`); `_render_view` only iterates RUNNING tasks (`running = [t for t in tasks if t.status == TaskStatus.RUNNING]`), so TO_DO tasks are never rendered; line 379 uses `task.remote_folder or ""` (NULL→empty string); `_render_json` line 174 passes `task.remote_folder` (None→JSON null) through. `entrypoints/client.py:85` only sets `metadata["remote_folder"]` when `t.remote_folder is not None`. No renderer assumes non-NULL on TO_DO. No changes required.

## 6. Knowledge graph and GRACE-lite

- [x] 6.1 Update `docs/knowledge-graph.xml` `M-DOMAIN-MODEL` annotations: remove `fn-allocate_to`/`fn-mark_running`/`fn-with_remote_folder`/`fn-with_download_results`/`fn-with_event`/`fn-record_event`/`fn-pull_events`; add `fn-run`/`fn-reject`/`fn-complete`/`fn-fail`/`fn-abandon`/`fn-materialize_task`
- [x] 6.2 Update `M-DOMAIN-EVENTS` annotations: remove `has_errors` reference from `TaskCompleted` purpose if present
- [x] 6.3 Update `M-DOMAIN-EXCEPTIONS` annotations: remove `TaskAlreadyAllocatedError`/`TaskNotAllocatedError`
- [x] 6.4 Run `python3 scripts/grace_check.py` and fix any reported markup drift; run `openspec validate --all --json` and confirm 0 failures

## 7. Unit tests — domain layer

- [x] 7.1 `tests/unit/test_domain_model.py` — rewrite lifecycle method tests: replace `allocate_to(node).mark_running()` chains with `run(node_id, remote_folder)`; replace `complete()`/`fail(reason)` with `complete(local_folder=, remote_folder=)`/`fail(reason, local_folder=, remote_folder=)`; add `reject`/`abandon` tests; add `abandon(None)` no-event test; update the `with_remote_folder`/`with_download_results` test classes (remove them)
- [x] 7.2 `tests/unit/test_domain_model.py` — add `materialize_task` test: given a Task with `events=()`, returns a Task with one `TaskCreated` in `events` carrying the right `task_id`/`webhook_url`/`webhook_custom_params`/`engine_name`
- [x] 7.3 `tests/unit/test_domain_events.py` — remove `TestTaskWithEvent` suite and `record_event`/`pull_events` tests; add a `TaskCompleted` has-no-`has_errors`-field test; add `materialize_task`-attaches-`TaskCreated` test
- [x] 7.4 `tests/unit/test_message_bus.py` — replace `task.record_event(event)` with direct `replace(task, events=(event,))` for fixture construction; update any `pull_events` assertions to read `task.events` directly

## 8. Unit tests — application layer

- [x] 8.1 `tests/unit/test_application_use_cases.py` — update `submit_task` tests: the returned Task's `remote_folder` is now `None` at submit time (remove `saved_arg.remote_folder.endswith("_42")` assertion at line 165); assert `TaskCreated` is in `events` after `insert`; update `allocate_task` tests to expect `task.run(...)` instead of `allocate_to`/`mark_running`/`with_event` mock calls
- [x] 8.2 `tests/unit/test_allocate_task_node_pairing.py` — update the SCOPE line and any assertions referencing `allocate_to` to reference `run`

## 9. Integration / e2e tests

- [x] 9.1 `tests/integration/test_db_integration.py` — replace `task.allocate_to(node).mark_running().with_remote_folder("/r")` chains (lines 256, 312, 431, 504, 508, 517, 550, 558) with `task.run(node.node_id, "/r")`; replace `with_download_results(...).complete()` (line 319) with `task.complete(local_folder=, remote_folder=)`; update the lifecycle test docstring
- [x] 9.2 `tests/integration/test_persistence_adapter.py` — replace `allocate_to`/`mark_running`/`with_remote_folder` chains (lines 150, 179, 233, 358, 363, 369) with `run`; replace `with_remote_folder` at line 102 with direct field construction or `run`; update any `pull_events` assertions to read `task.events`
- [x] 9.3 `tests/integration/test_never_connected_node_abandon.py` — replace `inserted_task.allocate_to(persisted_node)` (line 169) with `replace(inserted_task, allocated_node_id=persisted_node.node_id)` (test-only edge-case fixture construction via the frozen dataclass)
- [x] 9.4 `tests/integration/test_task_status_field_check.py` — replace `task.allocate_to(node).mark_running().with_remote_folder("/r")` (line 216) with `task.run(node.node_id, "/r")`
- [x] 9.5 `tests/e2e/test_full_cycle.py` — update any `_ALLOCATED_MARKER` log-line assertion if the `[AllocateTask][_try_allocate_to_machine][ALLOCATED]` log marker changed; verify e2e still passes with testcontainers

## 10. Static checks and validation

- [x] 10.1 Run `uv run pytest -m unit` and fix failures — 777 passed, 1 skipped
- [x] 10.2 Run `uv run pytest -m integration` with testcontainers and fix failures — 104 passed, 1 skipped
- [x] 10.3 Run `uv run pytest -m e2e` with testcontainers (if available) and fix failures — 4 passed, 2 skipped (hetzner live needs real cloud creds)
- [x] 10.4 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`; fix reported issues — all pass
- [x] 10.5 Run `openspec validate --all --json` and confirm 0 failures — 19 passed, 0 failed
- [x] 10.6 Run `python3 scripts/grace_check.py` and confirm exit 0 — 0 errors, exit 0