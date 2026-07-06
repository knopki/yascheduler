# Tasks: drop-task-context-entity

## 1. Schema and Migration

- [x] 1.1 Create `yascheduler/infra/persistence/sql/migrations/010_extract_metadata_columns.sql` — ADD 7 columns, UPDATE backfill (`->>` for string cols, `->` for wcp/extra, `COALESCE` defaults, `extra = metadata - known_keys`), ALTER NOT NULL + DEFAULT, DROP metadata. Per design.md D6.
- [x] 1.2 Update `yascheduler/infra/persistence/sql/schema.sql` — add the seven typed columns to `CREATE TABLE yascheduler_tasks`, drop `metadata`, bump `last_migration` CONSTANT from `'009'` to `'010'`.
- [x] 1.3 Delete `yascheduler/infra/persistence/sql/task/update_meta.sql` (dead file).
- [x] 1.4 Run `uv run sqlfluff lint --dialect postgres --ignore-local-config --config pyproject.toml yascheduler/infra/persistence/sql` and fix any lint findings in the new/edited SQL.

## 2. Domain Model

- [x] 2.1 In `yascheduler/domain/model.py`: delete `TaskContext`, `TaskContextOverrides`, `_get_opt_str`, `TaskContext.to_metadata`, `TaskContext.from_metadata`.
- [x] 2.2 In `yascheduler/domain/model.py`: reshape `NewTask` fields to `label, engine, local_folder=None, webhook_url=None, webhook_custom_params=dict, extra=dict, status=TO_DO, allocated_node_id=None` (NO `remote_folder`, NO `error`, NO `context`).
- [x] 2.3 In `yascheduler/domain/model.py`: reshape `Task` fields to `task_id, label, engine, remote_folder, local_folder, webhook_url, webhook_custom_params, error, extra, created_at, updated_at, status=TO_DO, allocated_node_id=None, _events=()` (identity-first, no defaults on the first 10 fields; `engine` required after `label`).
- [x] 2.4 In `yascheduler/domain/model.py`: simplify `Task.fail(reason)` to `replace(self, status=DONE, error=reason)` (guards unchanged); same for `Task.reject(reason)`.
- [x] 2.5 In `yascheduler/domain/model.py`: delete `Task.with_context`; add `Task.with_remote_folder(self, remote_folder: str) -> Task` and `Task.with_download_results(self, *, local_folder: str, remote_folder: str) -> Task` (keyword-only, no `extra` update).
- [x] 2.6 In `yascheduler/domain/model.py`: update `Task.with_event` to read `self.webhook_url` / `self.webhook_custom_params` (was `self.context.X`); update contract annotations.
- [x] 2.7 In `yascheduler/domain/__init__.py`: remove `TaskContext` and `TaskContextOverrides` from `__all__` and the explicit import list.
- [x] 2.8 Update `MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` in `yascheduler/domain/model.py` and `yascheduler/domain/__init__.py` per GRACE-lite (TaskContext removal, new methods, field-list changes).

## 3. Persistence

- [x] 3.1 In `yascheduler/infra/persistence/postgres.py` `_row_to_task`: read the seven typed columns directly from the row; `webhook_custom_params`/`extra` via `row["..."]` (dict from pg8000) with `json.loads` str-fallback; drop `TaskContext.from_metadata` and `row["metadata"]` access.
- [x] 3.2 In `yascheduler/infra/persistence/postgres.py` `insert`: bind `:engine, :remote_folder=None, :local_folder, :webhook_url, :error=None, :webhook_custom_params, :extra, :title, :status, :node_id`; drop `json.dumps(new_task.context.to_metadata())` and the `:metadata` param.
- [x] 3.3 In `yascheduler/infra/persistence/postgres.py` `save`: bind the same typed columns; drop `json.dumps(task.context.to_metadata())` and the `:metadata` param.
- [x] 3.4 Update `yascheduler/infra/persistence/sql/task/insert.sql` — column list and VALUES per design.md D7; drop `metadata`.
- [x] 3.5 Update `yascheduler/infra/persistence/sql/task/update_by_id.sql` — SET clause per design.md D7; drop `metadata=:metadata`.
- [x] 3.6 Update `yascheduler/infra/persistence/sql/task/get_by_id.sql`, `list_by_status.sql`, `list_by_jobs.sql` — SELECT column list per design.md D7; drop `metadata`.
- [x] 3.7 Re-run `uv run sqlfluff lint` on the four edited SQL files; fix findings.
- [x] 3.8 Update `MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` in `postgres.py` per GRACE-lite (typed-column reads/writes, no metadata, no TaskContext, no json.dumps).

## 4. Application Use Cases

- [x] 4.1 In `yascheduler/application/submit_task.py`: extract typed fields from the caller `metadata` dict; construct `NewTask(label=., engine=., local_folder=., webhook_url=., webhook_custom_params=., extra=.)` (no `TaskContext.from_metadata`); after insert call `task.with_remote_folder(.).with_event(TaskCreated, engine_name=task.engine)`.
- [x] 4.2 In `yascheduler/application/consume_task.py` `_prepare_store_folder`: read `task.remote_folder`, `task.engine`, `task.local_folder` (was `task.context.X`).
- [x] 4.3 In `yascheduler/application/consume_task.py` `_decide_finalisation`: add `_format_download_error(combined_errors)` helper producing `"Download error: <path>: <msg>, <path>: <msg>"` (combined `permanent + transient`, `path=None` → bare `"<msg>"`); replace `str(error_map)` with the helper.
- [x] 4.4 In `yascheduler/application/consume_task.py` `_decide_finalisation`: replace the `updated_context = task.context.replace(...)` + `task.with_context(updated_context)` with `task.with_download_results(local_folder=meta_dict.get("local_folder") or task.local_folder, remote_folder=meta_dict.get("remote_folder") or task.remote_folder)`; delete the `extra_updates` merge block (L117-126) entirely.
- [x] 4.5 In `yascheduler/application/allocate_task.py`: read `task.engine` (was `task.context.engine`) at L86,147; `with_event(TaskAllocated, ..., engine_name=task.engine)`.
- [x] 4.6 In `yascheduler/application/orchestrator.py`: read `task.engine` (was `task.context.engine`) at L499.
- [x] 4.7 Update `MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` in the four edited application files per GRACE-lite.

## 5. SSH Operations

- [x] 5.1 In `yascheduler/infra/ssh/operations/deployment.py`: replace `task.context.extra[input_file]` (L135) → `task.extra[input_file]`; replace `task.context.remote_folder` (L207,221) → `task.remote_folder`.
- [x] 5.2 Update `MODULE_CONTRACT` / `CHANGE_SUMMARY` in `deployment.py` per GRACE-lite (the `_write_remote_file` requirement text in `ssh-infrastructure` spec mentions `task.extra` now).

## 6. Entry Points and Facade

- [x] 6.1 In `yascheduler/entrypoints/client.py` `_task_to_dict`: replace `t.context.to_metadata()` with inline reconstruction — the six typed fields with `None` omitted, then `**t.extra` merged; preserve the public `{task_id, label, status, metadata, node}` shape.
- [x] 6.2 In `yascheduler/entrypoints/cli/check_status.py`: replace `task.context.engine` (L188), `task.context.local_folder` (L189), `task.context.remote_folder` (L190, L341, L409) with `task.engine`, `task.local_folder`, `task.remote_folder`.
- [x] 6.3 Update `MODULE_CONTRACT` / `CHANGE_SUMMARY` in `client.py` and `check_status.py` per GRACE-lite.

## 7. Tests

- [x] 7.1 Update `tests/unit/conftest.py` task fixtures (L89 and any `Task(context=TaskContext(...))` constructions) to use the new `Task(...)` / `NewTask(...)` typed-field construction (no `TaskContext`, no `context=` kwarg).
- [x] 7.2 Update `tests/unit/test_domain_model.py`: remove TaskContext / TaskContextOverrides / with_context / to_metadata / from_metadata tests; add `with_remote_folder`, `with_download_results`, error-format-contract, `with_event` reads-typed-fields tests; remove the drift-lock test asserting `set(TaskContextOverrides.__annotations__)`.
- [x] 7.3 Update `tests/unit/test_persistence_adapter.py`, `test_application_use_cases.py`, `test_application_orchestrator.py`, `test_client_query.py`, `test_domain_events.py`, `test_query_tasks.py`, `test_domain_ports.py`, `test_cloud_alloc_session_lifecycle.py`, `test_ssh_gateway_retry_rollback.py`, `test_cli_check_status.py`, `test_cli_behavioral.py` to the new `Task` / `NewTask` shape (no `task.context.X`, no `TaskContext(...)` construction).
- [x] 7.4 Update `tests/integration/test_db_integration.py`, `test_persistence_adapter.py`, `test_migrations.py`, `test_client_query_integration.py`, `test_never_connected_node_abandon.py`, `test_task_row_not_found.py`, `test_allocated_node_id_migration.py` — assert typed-column round-trip, `extra` JSONB round-trip, new error format; drop `metadata` column reads and `TaskContext` constructions; verify migration 010 runs cleanly in the migration-sequence test.
- [x] 7.5 Update `tests/e2e/test_consume_retry.py`, `test_full_cycle.py`, `test_hetzner_live.py` — read `task.error` / `task.local_folder` (was `task.context.error` / `task.context.local_folder`); node IP via `uow.nodes.get_by_id(task.allocated_node_id).ip`; the `"No such file" in str(task.error)` substring assertion still passes against the new `"Download error: /remote/1.out: No such file"` format.

## 8. GRACE-lite Knowledge Graph

- [x] 8.1 Update `docs/knowledge-graph.xml`: remove `TaskContext` / `TaskContextOverrides` / `to_metadata` / `from_metadata` / `with_context` annotations from `M-DOMAIN-MODEL`; add `with_remote_folder` / `with_download_results` / `error column format contract` annotations.
- [x] 8.2 Run `python3 scripts/grace_check.py` and fix any findings.

## 9. Verification

- [x] 9.1 Run `uv run pytest -m unit` — all unit tests pass.
- [x] 9.2 Run `uv run pytest -m integration` — all integration tests pass (migration 010 + typed-column round-trip + extra JSONB).
- [x] 9.3 Run `uv run pytest -m e2e` — e2e tests pass (test_full_cycle, test_consume_retry; hetzner live test skipped without the gate env var).
- [x] 9.4 Run `uv run ruff check . && uv run ruff format --check .` — lint/format pass.
- [x] 9.5 Run `uv run zuban check` if configured — static checks pass.
- [x] 9.6 Run `uv run lint-imports` — import structure passes.
- [x] 9.7 Run `openspec validate --all --json` — all 21 specs valid (already passing during proposal creation; re-run after any spec edits).
- [x] 9.8 Run `python3 scripts/grace_check.py` — GRACE-lite validation passes.