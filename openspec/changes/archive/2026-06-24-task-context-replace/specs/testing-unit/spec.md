## MODIFIED Requirements

### Requirement: Domain entities lifecycle

Tests SHALL verify `Task`, `Node`, `ConnectedMachine`, `TaskContext`, `Engine`,
`ProcessResult`, `TaskStatus`, `MachineState` from `yascheduler.domain.model`:
- `Task` immutability, `allocate_to`/`mark_running`/`complete`/`fail` transitions
  and guard errors (`TaskAlreadyAllocatedError`, `TaskNotAllocatedError`,
  `TaskNotTodoError`, `TaskNotRunningError`)
- `Task.with_context(context)`: wholesale context replacement returns a new
  immutable Task, original is unchanged, `_events` tuple is preserved, no
  validation guard (works in any status), and chains with `with_event`/`fail`/
  `complete`
- `TaskContext` known fields, extra dict, `to_metadata`/`from_metadata` round-trip
  (None omission, extra key merge, webhook_custom_params preservation)
- `TaskContext.replace(**overrides)`: typed copy-with returning a new immutable
  `TaskContext`, single-field and multi-field overrides, original unchanged,
  no-override call returns an equal copy, type checker rejects unknown kwargs
  (verified via the drift-lock test asserting
  `set(TaskContextOverrides.__annotations__) == {"remote_folder", "local_folder",
  "error", "extra"}`)
- `Engine.validate_inputs` passes with all files, raises `MissingInputFileError`
  when a file is missing
- `ConnectedMachine.is_compatible`, `occupy`, `release` with state guards
- `Node` defaults (username="root", port=22, cloud=None, enabled=True)

#### Scenario: Task fail on non-running raises TaskNotRunningError
- **WHEN** `task.fail("reason")` is called on a TO_DO task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: TaskContext round-trip preserves extra
- **WHEN** `TaskContext(engine="fleur", extra={"fort.9": "data"})` is serialized and deserialized
- **THEN** extra keys are preserved

#### Scenario: with_context replaces context wholesale and preserves the original
- **WHEN** `task.with_context(new_context)` is called and the original `task.context` is inspected afterward
- **THEN** the returned Task has `context is new_context` and the original task's context is unchanged (frozen dataclass)

#### Scenario: with_context preserves the events tuple
- **WHEN** `task.with_context(new_context)` is called on a task with a non-empty `_events` tuple
- **THEN** the returned Task has an `_events` tuple equal to the original task's `_events`

#### Scenario: with_context performs no status validation
- **WHEN** `task.with_context(new_context)` is called on a DONE task
- **THEN** no error is raised and a new Task with the new context is returned

#### Scenario: with_context chains with with_event
- **WHEN** `task.with_context(new_context).with_event(TaskCreated, engine_name=new_context.engine)` is called
- **THEN** the returned Task has the new context and the `TaskCreated` event appended

#### Scenario: TaskContext.replace applies a single override and preserves the original
- **WHEN** `ctx.replace(remote_folder="/r/new")` is called on a `TaskContext` with `remote_folder=None`
- **THEN** the returned `TaskContext` has `remote_folder="/r/new"` and all other fields preserved, and the original `ctx.remote_folder` is still `None`

#### Scenario: TaskContext.replace applies multiple overrides simultaneously
- **WHEN** `ctx.replace(local_folder="/l", remote_folder="/r", extra={"k": "v"})` is called
- **THEN** the returned `TaskContext` has all three overridden fields set and all non-overridden fields preserved unchanged

#### Scenario: TaskContext.replace with no overrides returns an equal copy
- **WHEN** `ctx.replace()` is called with no arguments
- **THEN** the returned `TaskContext` compares equal to the original (`==`) but is not the same object (`is`)

#### Scenario: TaskContextOverrides keys match audited call-site usage
- **WHEN** `set(TaskContextOverrides.__annotations__)` is inspected
- **THEN** it equals exactly `{"remote_folder", "local_folder", "error", "extra"}` — the fields actually overridden somewhere in the codebase; drift in either direction (a new call site overriding an unlisted field, or a TypedDict field with no call site) fails this test