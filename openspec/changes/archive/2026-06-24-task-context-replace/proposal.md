## Why

Use cases build a new `TaskContext` via raw `dataclasses.replace(task.context, field=...)`,
reaching past the value object's boundary into the `dataclasses` machinery. The
symmetric `Task.with_context` (added in the prior `task-with-context` change)
already hides the *entity-level* `replace(task, context=...)`, but the
*value-object-level* `replace(task.context, ...)` still leaks. This adds
`TaskContext.replace(**overrides)` — a typed copy-with helper that mirrors
`dataclasses.replace` by name, returns a new immutable `TaskContext`, and
restores the fluent chain at the value-object layer.

## What Changes

- Add `TaskContext.replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self`
  to `yascheduler/domain/model.py`: returns a new `TaskContext` via
  `dataclasses.replace(self, **overrides)`. No merge into a stored context, no
  validation guard (value object, orthogonal to lifecycle). The method name
  `replace` shadows nothing at runtime — the bare name `replace` inside the
  body resolves lexically to the imported `dataclasses.replace`, not to the
  method (no recursion).
- Add `TaskContextOverrides(TypedDict, total=False)` with exactly the 4 fields
  actually overridden somewhere in the codebase: `remote_folder`, `local_folder`,
  `error`, `extra`. The other 3 `TaskContext` fields (`engine`, `webhook_url`,
  `webhook_custom_params`) are never overridden and are excluded (YAGNI). A
  drift-lock unit test asserts the TypedDict key set matches the audited
  override-usage set across call sites.
- Migrate the 4 call sites that use `replace(task.context, ...)` /
  `replace(self.context, ...)`:
  - `yascheduler/application/submit_task.py:90`:
    `replace(task.context, remote_folder=remote_folder)` →
    `task.context.replace(remote_folder=remote_folder)`.
  - `yascheduler/application/consume_task.py:98`:
    `replace(task.context, local_folder=..., remote_folder=..., extra=...)` →
    `task.context.replace(local_folder=..., remote_folder=..., extra=...)`.
  - `yascheduler/domain/model.py:237` (inside `Task.fail`):
    `replace(self.context, error=reason)` → `self.context.replace(error=reason)`.
  - `yascheduler/domain/model.py:259` (inside `Task.reject`):
    `replace(self.context, error=reason)` → `self.context.replace(error=reason)`.
- After migration, the `from dataclasses import ... replace` import stays in
  `model.py` (used for `replace(self, ...)` at the Task/entity level and for
  `ConnectedMachine`/other entities). It MAY become removable from
  `submit_task.py` and `consume_task.py` if no other `replace(...)` use remains
  there — checked during implementation; remove if dead, leave if used.
- GRACE-lite: add `START_CONTRACT: TaskContext.replace`, add the
  `TaskContextOverrides` TypedDict to `MODULE_MAP`, bump `VERSION`
  (1.11.0 → 1.12.0), add `START_CHANGE_SUMMARY` entry in `model.py`. Update
  `docs/knowledge-graph.xml` `M-DOMAIN-MODEL` `<annotations>` with
  `<fn-replace PURPOSE="Typed copy-with returning new TaskContext" />` on the
  `TaskContext` side and a `<type-TaskContextOverrides>` annotation.
- Update `openspec/specs/domain-entities/spec.md`: extend the "TaskContext typed
  metadata" requirement with a `replace` scenario (typed overrides, returns new
  immutable `TaskContext`, original unchanged, unknown field name rejected by
  type checker, drift-lock on override fields).
- Update `openspec/specs/testing-unit/spec.md`: extend the "Domain entities
  lifecycle" requirement to cover `TaskContext.replace` (immutability,
  single-field and multi-field overrides, original unchanged, drift-lock test
  for `TaskContextOverrides` keys).
- Add focused unit tests in `tests/unit/test_domain_model.py` for
  `TaskContext.replace` and the drift-lock test.

### Out of scope

- Extending `TaskContextOverrides` to all 7 `TaskContext` fields — YAGNI; only
  fields actually overridden at call sites go in. Adding a new override field
  elsewhere forces a TypedDict update (enforced by the drift-lock test and by
  the type checker rejecting unknown kwargs).
- A general `evolve`/`with_overrides` facility for other value objects
  (`Engine`, `Node`, `ProcessResult`, `ConnectedMachine`). No external raw
  `replace(...value-object...)` exists for them (they already have
  `occupy`/`release`/etc.). YAGNI.
- Migrating `replace(self, ...)` at the Task/entity level to any helper. Those
  are entity-field replacements, not value-object-field replacements; the new
  `TaskContext.replace` does not apply. `dataclasses.replace` stays as the
  mechanism inside `Task.allocate_to`/`mark_running`/`complete`/`fail`/
  `reject`/`record_event`/`with_context`/`pull_events`.
- Migrating `replace(task, task_id=...)` in tests — Task-level field replace,
  unrelated to context.
- AiiDA plugin — read-only consumer, does not call `replace(task.context, ...)`
  (verified by grep).
- Any validation guard on `TaskContext.replace` — value object, orthogonal to
  lifecycle; mirrors guard-free `Task.with_context` and `record_event`.

## Capabilities

### New Capabilities

_None._ `TaskContext.replace` extends the existing `TaskContext` value object,
expressed as a modification to `domain-entities`.

### Modified Capabilities

- `domain-entities`: the "TaskContext typed metadata" requirement gains a
  `replace(**overrides) -> Self` behavior — typed copy-with returning a new
  immutable `TaskContext`, overrides drawn from `TaskContextOverrides`
  (`remote_folder`, `local_folder`, `error`, `extra`), no validation guard.
- `testing-unit`: the "Domain entities lifecycle" requirement gains coverage
  for `TaskContext.replace` (immutability, single/multi-field overrides,
  original unchanged, drift-lock test for `TaskContextOverrides` keys).

## Impact

- **Code**: `yascheduler/domain/model.py` (new method + TypedDict + GRACE
  markup); `yascheduler/application/submit_task.py` (1 call-site migration);
  `yascheduler/application/consume_task.py` (1 call-site migration); the two
  internal `Task.fail`/`Task.reject` sites in `model.py` migrate too.
- **Imports**: `model.py` gains `Self` and `Unpack`, imported from
  `yascheduler.shared` (the existing compat facade). `yascheduler/shared/compat.py`
  is extended to re-export `Unpack` with the same version-branch strategy it
  already uses for `Self`/`ParamSpec` (`typing_extensions.Unpack` on <3.11,
  `typing.Unpack` on ≥3.11); compat.py gets a VERSION bump, a `MODULE_MAP`
  entry for `Unpack`, and a `CHANGE_SUMMARY` entry. `dataclasses.replace`
  import stays in `model.py` (Task-level uses remain); possibly removed from
  `submit_task.py`/`consume_task.py` if dead after migration.
- **Tests**: `tests/unit/test_domain_model.py` (new `TaskContext.replace` suite
  + drift-lock test); existing use-case tests are behavioral and stay green.
- **External API**: `class Yascheduler` public API unchanged. The new
  `TaskContext.replace` is a value-object method, additive-only; raw
  `dataclasses.replace(ctx, ...)` continues to work (frozen dataclass). No
  breaking change.
- **Specs**: `openspec/specs/domain-entities/spec.md` and
  `openspec/specs/testing-unit/spec.md` updated via delta specs in
  `openspec/changes/task-context-replace/specs/`.
- **Knowledge graph**: `docs/knowledge-graph.xml` `M-DOMAIN-MODEL`
  `<annotations>` gains `<fn-replace>` (under `class-TaskContext` region) and
  `<type-TaskContextOverrides>`.
- **Dependencies**: no new runtime dependency. `typing-extensions` is already
  declared in `pyproject.toml` `dependencies` with marker
  `python_version < '3.11'`; on 3.11+ the compat shim imports `Unpack`/`Self`
  from `typing` instead. No `pyproject.toml` change.
- **Python compat**: `requires-python = ">=3.9"` honored. `Unpack` (PEP 692)
  and `Self` (PEP 673) are typing constructs; `yascheduler/shared/compat.py`
  already provides a version-branched re-export for `Self`/`ParamSpec` and is
  extended symmetrically for `Unpack`. No runtime behavior depends on
  `typing_extensions` on 3.11+.