# Explore Brief — task-context-replace

## Alternatives rejected

- **`replace(**overrides: object)` losing field-name checking**: rejected —
  `dataclasses.replace` gets field-name checking via the mypy dataclasses
  plugin (special-cased). A custom method with `**overrides: object` loses
  this — a typo like `remot_folder=` is silently accepted, creates a spurious
  new field on the copy while the real field stays `None` → runtime bug.
  This is exactly the regression the previous `task-with-context` brief
  rejected for the merge form `with_context(**overrides)`.

- **Sentinel enumeration signature** (`def replace(self, *, engine=_UNSET, ...)`):
  rejected — works technically, preserves checking without TypedDict, but
  adds a `_UNSET` sentinel and a `locals()` filter idiom that's heavier
  than TypedDict+Unpack for the same outcome. TypedDict+Unpack reads
  cleaner and is idiomatic for typed kwargs in modern Python.

- **Enumerated overloads per field**: rejected — brittle, mirrors the field
  subset, drifts on change, combinatorial explosion if multiple fields are
  set together (consume_task sets 3 at once). YAGNI. Previous `with_event`
  uses overloads because each event subclass has *different required
  fields* — `TaskContext.replace` has no required overrides (all optional,
  keyword-only).

- **Name `update`**: rejected — connotes in-place mutation, clashes with
  frozen semantics; surprises the reader of a frozen dataclass.

- **Name `evolve`**: rejected — attrs convention, foreign to this codebase's
  vocabulary. `with_*` and `replace` are the local precedents (`with_context`,
  `with_event`, raw `dataclasses.replace`).

- **Name `with_overrides`**: rejected — readable and consistent with
  `with_context`/`with_event`, but user chose `replace` to mirror the stdlib
  primitive being delegated to. Decision: `replace`.

- **Including all 7 TaskContext fields in the TypedDict**: rejected (YAGNI) —
  only fields actually overridden somewhere in the codebase go in.
  Audit of `replace(...context...)` call sites yields 4 fields:
  `remote_folder`, `local_folder`, `extra`, `error`. `engine`,
  `webhook_url`, `webhook_custom_params` are never overridden — excluded.

- **Migrating `Task.fail`/`Task.reject` internals (model.py:237,259)**:
  ACCEPTED into scope — `replace(self.context, error=reason)` →
  `self.context.replace(error=reason)`. Internal-only, zero behavior change,
  but consolidates all `replace(self.context, ...)` usages behind the new
  method. Consistent with the migration goal.

## Final approach (labels / mapping)

Single method on `TaskContext`:

```python
class TaskContextOverrides(TypedDict, total=False):
    remote_folder: str | None
    local_folder: str | None
    error: str | None
    extra: dict[str, object]

def replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self:
    return replace(self, **overrides)
```

- Name: `replace` (shadows `dataclasses.replace` lexically — the bare name
  `replace` in the method body resolves to the imported function, not the
  method; no recursion, no shadowing bug).
- Signature: typed kwargs via `Unpack[TaskContextOverrides]` (PEP 692).
- TypedDict `total=False`: all overrides optional; callers pass any subset.
- Return type: `Self` from `typing_extensions` — correct for frozen copy.
- YAGNI: only 4 fields actually overridden anywhere are in the TypedDict.
- Drift-locked by a unit test: `assert set(TaskContextOverrides.__annotations__) ==
  {fields actually overridden in source}` — but since we deliberately keep
  only 4, the test asserts the SET of override-capable fields equals the set
  of fields actually used at call sites, catching both directions of drift
  (adding a call site for a new field forces adding it to the TypedDict;
  removing the last call site for a field prompts consideration of removal).

## Cross-module data flows

Call sites migrated (4 total, in 2 files — model.py migrates its own
internal calls too):

1. `yascheduler/application/submit_task.py:90` —
   `replace(task.context, remote_folder=remote_folder)` →
   `task.context.replace(remote_folder=remote_folder)`.
   Read chain becomes:
   `task = task.with_context(task.context.replace(remote_folder=remote_folder)).with_event(TaskCreated, engine_name=task.context.engine)`.

2. `yascheduler/application/consume_task.py:98` —
   `replace(task.context, local_folder=..., remote_folder=..., extra={**...})` →
   `task.context.replace(local_folder=..., remote_folder=..., extra={**...})`.
   Stays as a standalone statement assigning to `updated_context`; the
   subsequent `task.with_context(updated_context)...` chain from the prior
   change is unchanged.

3. `yascheduler/domain/model.py:237` (inside `Task.fail`) —
   `context=replace(self.context, error=reason)` →
   `context=self.context.replace(error=reason)`.
   Internal to `Task.fail`; no observable change. The outer
   `replace(self, status=..., context=...)` stays as `dataclasses.replace`
   (Task-level field replacement, not TaskContext-level).

4. `yascheduler/domain/model.py:259` (inside `Task.reject`) —
   same as #3.

NOT migrated (out of scope):
- `Task.with_context` (model.py:281): `return replace(self, context=context)`
  — this is Task-level, not TaskContext-level. Stays as `dataclasses.replace`.
- `Task.record_event`, `pull_events`, `allocate_to`, `mark_running`, `complete`
  — all Task-level `replace(self, ...)`. Untouched.
- `ConnectedMachine.occupy`/`release`, `Task.record_event` — Task/Machine-level,
  not TaskContext. Untouched.
- Tests using `replace(task, task_id=...)` — Task-level, unrelated.

## Known open questions

None remaining. All forks closed during explore:
1. Name → `replace` (user decision, mirrors `dataclasses.replace`).
2. TypedDict fields → only 4 actually-used (YAGNI, user directive).
3. `fail`/`reject` internals → in scope (consolidates all context-replace
   usages behind the method; internal-only, zero observable change).
4. Drift-locked → unit test asserting `TaskContextOverrides.__annotations__`
   keys match the audited call-site override fields.
5. Return type → `Self` (typing_extensions).
6. Shadowing safety → verified: lexical scoping resolves bare `replace` in
   the method body to the imported `dataclasses.replace`, not the method.
   No runtime recursion. Existing `from dataclasses import ... replace`
   import stays; the method name does not shadow the module-level name.
7. Python 3.9 compat → `Unpack`/`Self` are typing constructs, runtime no-ops
   on ≤3.10 (typing, not runtime values); mypy/zuban resolve them statically.
   `requires-python = ">=3.9"` honored. Resolved import strategy: extend
   `yascheduler/shared/compat.py` to re-export `Unpack` with the same
   version-branch pattern it already uses for `Self`/`ParamSpec`
   (`typing_extensions.Unpack` on <3.11, `typing.Unpack` on ≥3.11); `model.py`
   imports `Self` and `Unpack` from `yascheduler.shared`. No new runtime
   dependency — `typing-extensions` is already declared in `pyproject.toml`
   `dependencies` with marker `python_version < '3.11'`.