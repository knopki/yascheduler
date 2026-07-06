# Spec Delta: test-db-integration

## MODIFIED Requirements

### Requirement: Task CRUD integration

Tests SHALL verify task operations via `PostgresTaskRepository` (through
`uow.tasks`) using the domain `Task` / `NewTask` entities and
`yascheduler.domain.TaskStatus` (`TaskContext` is REMOVED — see the
`domain-entities` delta; it is no longer tested): `insert`, `get`,
`update_status`, `save` (for set_running / set_done / set_error transitions),
`list_by_status`, `list_by_jobs`. Lifecycle transitions SHALL be expressed via
the domain `Task` methods (`allocate_to`, `mark_running`, `complete`, `fail`,
`reject`, `with_remote_folder`, `with_download_results`) operating on the
typed fields directly, then persisted via `uow.tasks.save`.

Tests SHALL construct `Task` / `NewTask` with the typed fields directly (no
`TaskContext(...)` wrapper, no `context=` kwarg). The `extra` JSONB column
(input-file payloads and unknown keys) SHALL be asserted to round-trip
through `insert` + `get` / `list_by_status` / `list_by_jobs`. The seven typed
columns (`engine`, `remote_folder`, `local_folder`, `webhook_url`, `error`,
`webhook_custom_params`, `extra`) SHALL be asserted to round-trip. `error`
SHALL be asserted to persist the new format contract values (bare strings for
`reject`/orchestrator `fail`, `"Download error: ..."` for consume `fail`,
`NULL` on success — see the `domain-entities` delta).

#### Scenario: Full task lifecycle
- **WHEN** `insert` → `save(task.allocate_to(node).mark_running())` → `save` with DONE status and updated typed fields is executed
- **THEN** each step reflects the correct status and typed fields (`engine`, `remote_folder`, `local_folder`, `error`, `extra`, `allocated_node_id`) in `uow.tasks.get`

#### Scenario: set_task_error embeds error
- **WHEN** a task is saved with `task.error="crash"` (via `task.fail("crash")` or `task.reject("crash")`) and status DONE
- **THEN** `uow.tasks.get(id)` returns status DONE and the row's `error` column equals `"crash"` (the typed column carries the error string directly; no `metadata` JSONB serialization)

#### Scenario: extra JSONB round-trips
- **WHEN** a task is saved with `extra={"input.in": "ATOMS", "input.xyz": "..."}` and retrieved via `uow.tasks.get(id)`
- **THEN** the retrieved task's `extra` equals `{"input.in": "ATOMS", "input.xyz": "..."}` (the `extra` JSONB column round-trips; pg8000 adapts `dict` ↔ JSONB natively)

#### Scenario: typed columns round-trip
- **WHEN** a task is saved with `engine="cp2k"`, `remote_folder="/r"`, `local_folder="/l"`, `webhook_url="https://..."`, `webhook_custom_params={"k": "v"}`, `error=None`, `extra={}` and retrieved
- **THEN** the retrieved task has the same values for all seven typed columns; `error` is `None` (NULL in the DB)

#### Scenario: No TaskContext or metadata in tests
- **WHEN** the integration test suite is inspected for `TaskContext`, `task.context`, `to_metadata`, `from_metadata`, or `row["metadata"]` references
- **THEN** none are present (the value object and the `metadata` column are removed; tests use the typed `Task` fields and the typed columns directly)

#### Scenario: No json.dumps/json.loads on metadata in tests
- **WHEN** the integration test suite is inspected for `json.dumps(...metadata...)` or `json.loads(...metadata...)` references
- **THEN** none are present (the `metadata` column is removed; `webhook_custom_params` and `extra` are bound as `dict` and adapted by pg8000 natively; `_row_to_task` reads them as `dict` directly with a `json.loads` str-fallback)