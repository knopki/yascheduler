# Spec Delta: testing-unit

## MODIFIED Requirements

### Requirement: Domain entities lifecycle

Tests SHALL verify `Task`, `Node`, `ConnectedMachine`, `Engine`,
`ProcessResult`, `TaskStatus`, `MachineState` from `yascheduler.domain.model`
(`TaskContext` and `TaskContextOverrides` are REMOVED — see the `domain-entities`
delta; they are no longer tested):
- `Task` immutability, `allocate_to`/`mark_running`/`complete`/`fail`/`reject`
  transitions and guard errors (`TaskAlreadyAllocatedError`,
  `TaskNotAllocatedError`, `TaskNotTodoError`, `TaskNotRunningError`)
- `Task.with_remote_folder(remote_folder)`: returns a new immutable Task with
  `remote_folder` set, all other fields preserved, `_events` tuple preserved,
  no validation guard (works in any status), and chains with `with_event`/`fail`/
  `complete`
- `Task.with_download_results(*, local_folder, remote_folder)`: returns a new
  immutable Task with both fields set, all other fields (including `extra`)
  preserved, `extra` NOT modified, accepts equal values (no-op-equivalent),
  keyword-only (positional args raise `TypeError`), no validation guard (works
  in any status)
- `Task.fail(reason)` / `Task.reject(reason)`: returns a new Task with
  `status=DONE` and `error=reason` (was `context.error`); guards unchanged
  (`TaskNotRunningError` / `TaskNotTodoError`)
- `Task.with_event` reads `self.webhook_url` / `self.webhook_custom_params`
  (was `self.context.X`); passes `task_id=self.task_id` (a `TaskId`)
- `Task.error` column format contract: bare human strings for
  `reject`/orchestrator `fail`, `"Download error: <path>: <msg>, ..."` for
  consume `fail`, `NULL`/`None` on success
- `NewTask` has no `task_id`, no `_events`, no `created_at`/`updated_at`, no
  `status`, no `allocated_node_id`, no `remote_folder`, no `error` (those appear
  only on `Task`, or are DB-defaulted); a pre-bound task is inserted then
  `allocate_to(node)` + `save()`
- `Engine.validate_inputs` passes with all files, raises `MissingInputFileError`
  when a file is missing
- `ConnectedMachine.is_compatible`, `occupy`, `release` with state guards
- `Node` defaults (username="root", port=22, cloud=None, enabled=True)

Tests SHALL construct `Task` / `NewTask` with the typed fields directly (no
`TaskContext(...)` wrapper, no `context=` kwarg). Test fixtures and helpers
(e.g. `tests/unit/conftest.py`) SHALL be updated to the new construction shape.
Test restructuring is NOT a design blocker (user-explicit); tests are updated
to compile and pass against the new model.

#### Scenario: Task fail on non-running raises TaskNotRunningError
- **WHEN** `task.fail("reason")` is called on a TO_DO task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: Task fail sets error to the reason
- **WHEN** `task.fail("out of memory")` is called on a RUNNING task
- **THEN** the returned Task has `status=DONE` and `error="out of memory"` (was `context.error`)

#### Scenario: Task reject sets error to the reason
- **WHEN** `task.reject("disk full")` is called on a TO_DO task
- **THEN** the returned Task has `status=DONE` and `error="disk full"` (was `context.error`)

#### Scenario: with_remote_folder sets the field and preserves the original
- **WHEN** `task.with_remote_folder("/r/new")` is called on a Task with `remote_folder=None`
- **THEN** the returned Task has `remote_folder="/r/new"` and all other fields (`task_id`, `label`, `engine`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`, `status`, `allocated_node_id`, `_events`) preserved unchanged; the original task is unchanged (frozen dataclass)

#### Scenario: with_remote_folder preserves the events tuple
- **WHEN** `task.with_remote_folder("/r/new")` is called on a task with a non-empty `_events` tuple
- **THEN** the returned Task has an `_events` tuple equal to the original task's `_events`

#### Scenario: with_remote_folder performs no status validation
- **WHEN** `task.with_remote_folder("/r/new")` is called on a DONE task
- **THEN** no error is raised and a new Task with the new `remote_folder` is returned

#### Scenario: with_remote_folder chains with with_event
- **WHEN** `task.with_remote_folder("/r/new").with_event(TaskCreated, engine_name=task.engine)` is called
- **THEN** the returned Task has `remote_folder="/r/new"` and the `TaskCreated` event appended

#### Scenario: with_download_results sets both fields and preserves extra
- **WHEN** `task.with_download_results(local_folder="/l", remote_folder="/r")` is called on a Task with `extra={"input.in": "ATOMS"}`
- **THEN** the returned Task has `local_folder="/l"`, `remote_folder="/r"`, and `extra={"input.in": "ATOMS"}` unchanged (extra NOT modified)

#### Scenario: with_download_results accepts equal values
- **WHEN** `task.with_download_results(local_folder=task.local_folder, remote_folder=task.remote_folder)` is called (same values)
- **THEN** a new Task is returned with the same values; no error is raised

#### Scenario: with_download_results is keyword-only
- **WHEN** `task.with_download_results("/l", "/r")` is called with positional arguments
- **THEN** `TypeError` is raised

#### Scenario: with_event reads webhook fields from self not self.context
- **WHEN** `task.with_event(TaskCreated, engine_name=task.engine)` is called on a Task with `webhook_url="https://example.com"`, `webhook_custom_params={"k": "v"}`
- **THEN** the constructed `TaskCreated` event has `event.webhook_url == "https://example.com"` and `event.webhook_custom_params == {"k": "v"}` (read from `self.webhook_url` / `self.webhook_custom_params`, was `self.context.X`)

#### Scenario: NewTask has no remote_folder or error
- **WHEN** a NewTask is constructed with `label="job"`, `engine="cp2k"`
- **THEN** it has no `remote_folder` attribute and no `error` attribute; those fields appear only on the post-persistence `Task`

#### Scenario: Engine validate_inputs passes
- **WHEN** `engine.validate_inputs({"input.in": "ATOMS"})` is called and `engine.input_files=("input.in",)`
- **THEN** it passes (no exception)

#### Scenario: Engine validate_inputs raises on missing file
- **WHEN** `engine.validate_inputs({})` is called and `engine.input_files=("input.in",)`
- **THEN** `MissingInputFileError` is raised

#### Scenario: No TaskContext or with_context in tests
- **WHEN** the unit test suite is inspected for `TaskContext`, `TaskContextOverrides`, `with_context`, `task.context`, `to_metadata`, or `from_metadata` references
- **THEN** none are present (the value object is removed; tests use the typed `Task` / `NewTask` fields directly)

#### Scenario: No TaskContext drift-lock test
- **WHEN** the unit test suite is inspected for a drift-lock test asserting `set(TaskContextOverrides.__annotations__) == {...}`
- **THEN** no such test exists (the `TaskContextOverrides` TypedDict is removed; the drift-lock concern is moot)