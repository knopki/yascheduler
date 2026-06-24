## Why

Use cases set `task.context` via `dataclasses.replace(task, context=...)`, a
two-layer copy that breaks the fluent, copy-with-return style `Task` already
exposes (`allocate_to`, `mark_running`, `complete`, `fail`, `reject`,
`record_event`, `with_event`). The entity boundary leaks: callers reach into
the `dataclasses` machinery to mutate a field through the entity. Adding a
`with_context` setter — the direct analog of `with_event` — restores the
fluent chain (`task.with_context(ctx).with_event(...)`) and keeps the entity
in control of its own field replacement.

## What Changes

- Add `Task.with_context(context: TaskContext) -> Task` to
  `yascheduler/domain/model.py`: wholesale context replacement, returns a new
  `Task` via `replace(self, context=context)`. No merge, no per-field
  overrides, no validation guard (context is metadata orthogonal to status,
  mirroring the guard-free `record_event`). Additive-only —
  `replace(task, context=...)` stays valid (frozen dataclass); pattern is not
  prohibited.
- Migrate the 3 call sites that currently use `replace(task, context=...)`:
  - `yascheduler/application/submit_task.py:91`:
    `replace(task, context=context)` → `task.with_context(context)`
  - `yascheduler/application/consume_task.py:108` (sftp_errors branch):
    `replace(task, context=updated_context)` → `task.with_context(updated_context)`
  - `yascheduler/application/consume_task.py:111` (success branch):
    `replace(task, context=updated_context)` → `task.with_context(updated_context)`
- **Clean up** `consume_task.py:107`: drop the redundant
  `updated_context = replace(updated_context, error=error_msg)`. The subsequent
  `.fail(error_msg)` already sets `context.error=reason` internally; the
  explicit set is drift, producing an identical final context. Behavior
  preserved.
- GRACE-lite: add `START_CONTRACT: Task.with_context`, update `MODULE_MAP`
  (`Task - ... with_context`), bump `VERSION` (1.10.0 → 1.11.0), add
  `START_CHANGE_SUMMARY` entry in `model.py`. Update
  `docs/knowledge-graph.xml` `M-DOMAIN-MODEL` `<annotations>` with
  `<fn-with_context .../>`.
- Update `openspec/specs/domain-entities/spec.md`: extend the "Task entity
  with status lifecycle" requirement with a `with_context` scenario.
- Update `openspec/specs/testing-unit/spec.md`: extend the "Domain entities
  lifecycle" requirement to cover `with_context` (immutability, wholesale
  replace, original unchanged, `_events` preserved, chaining with
  `with_event`/`fail`/`complete`).
- Add focused unit tests in `tests/unit/test_domain_model.py` mirroring the
  `with_event` suite in `tests/unit/test_domain_events.py`.

### Out of scope

- A `TaskContext.with(**overrides)` / copy-with helper — planned as a separate
  follow-up change. Call sites keep using raw `replace(task.context, ...)`
  to build the new `TaskContext` for now.
- Converting `Task.fail` / `Task.reject` internals to `with_context` — they
  set both `status` and `context` in a single `replace(self, ...)`; the
  context-only `with_context` does not help, and the change is internal-only
  with zero readability gain.
- Migrating `replace(task, task_id=...)` in tests — Task-level field replace,
  unrelated to context.
- AiiDA plugin — read-only consumer, does not use `replace(task, context=...)`
  (verified by grep).

## Capabilities

### New Capabilities

_None._ `with_context` extends the existing `Task` entity, expressed as a
modification to `domain-entities`.

### Modified Capabilities

- `domain-entities`: the "Task entity with status lifecycle" requirement gains
  a `with_context(context: TaskContext) -> Task` behavior — wholesale context
  replacement returning a new immutable Task, no validation guard.
- `testing-unit`: the "Domain entities lifecycle" requirement gains coverage
  for `Task.with_context` (immutability, wholesale replace, original
  unchanged, `_events` preserved, chaining).

## Impact

- **Code**: `yascheduler/domain/model.py` (new method + GRACE markup);
  `yascheduler/application/submit_task.py` (1 call-site migration);
  `yascheduler/application/consume_task.py` (2 call-site migrations + 1
  redundant-set cleanup).
- **Tests**: `tests/unit/test_domain_model.py` (new `with_context` suite);
  existing assertions on migrated use cases are behavioral and stay green
  (`inserted_arg.context.extra`, `saved_task.context.error`, etc.).
- **External API**: `class Yascheduler` public API unchanged. The new
  `Task.with_context` is a domain-entity method, additive-only; existing
  `replace(task, context=...)` continues to work. No breaking change.
- **Specs**: `openspec/specs/domain-entities/spec.md` and
  `openspec/specs/testing-unit/spec.md` updated via delta specs in
  `openspec/changes/task-with-context/specs/`.
- **Knowledge graph**: `docs/knowledge-graph.xml` `M-DOMAIN-MODEL`
  `<annotations>` gains `<fn-with_context>`.
- **Dependencies**: none added or removed.