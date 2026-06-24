## Context

`TaskContext` (frozen dataclass, `yascheduler/domain/model.py:84`) is the
value object carrying task metadata (engine, paths, webhook config, extras).
Today, every site that needs a modified `TaskContext` reaches past the value
object into the `dataclasses` machinery:

```
replace(task.context, remote_folder=remote_folder)        # submit_task.py:90
replace(task.context, local_folder=..., remote_folder=..., extra={**...})  # consume_task.py:98
replace(self.context, error=reason)                       # model.py:237 (Task.fail)
replace(self.context, error=reason)                       # model.py:259 (Task.reject)
```

The prior `task-with-context` change hid the *entity-level* leak
(`replace(task, context=...)` → `Task.with_context`). This change hides the
remaining *value-object-level* leak (`replace(task.context, ...)` →
`TaskContext.replace`), completing the fluent chain at both layers.

The `dataclasses.replace` call gets field-name checking via the mypy
dataclasses plugin (it special-cases `replace`). Any hand-rolled replacement
must preserve that checking or it is a regression.

Precedent in the codebase: `Task.with_event` (5 overloads, one per event
subclass with distinct required fields) and `Task.with_context` (single
typed argument, wholesale replace). `ConnectedMachine.occupy`/`release`
hide `replace(self, state=...)` behind named transitions. The pattern is
established; `TaskContext.replace` fills the one gap.

## Goals / Non-Goals

**Goals:**
- Add `TaskContext.replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self`
  — typed copy-with returning a new immutable `TaskContext`, no merge, no
  validation guard.
- `TaskContextOverrides(TypedDict, total=False)` with exactly the 4 fields
  actually overridden somewhere in the codebase: `remote_folder`,
  `local_folder`, `error`, `extra`.
- Migrate the 4 call sites (2 application, 2 internal to `Task.fail`/`reject`).
- Drift-lock: a unit test asserting the TypedDict key set matches the audited
  override-usage set.
- Re-export `Unpack` from `yascheduler/shared/compat.py` (version-branched,
  mirroring `Self`/`ParamSpec`).
- GRACE-lite: contract, MODULE_MAP, CHANGE_SUMMARY, VERSION bump,
  knowledge-graph annotations.
- Preserve additive-only: raw `dataclasses.replace(ctx, ...)` stays valid.

**Non-Goals:**
- All-7-fields TypedDict (YAGNI — user directive: only fields actually
  overridden at call sites).
- General `evolve`/`with_overrides` for `Engine`/`Node`/`ProcessResult`/
  `ConnectedMachine` (no external raw `replace(...value-object...)` for them).
- Migrating `replace(self, ...)` at the Task/entity level
  (`allocate_to`/`mark_running`/`complete`/`fail`/`reject`/`record_event`/
  `with_context`/`pull_events`). Those are entity-field replacements; the new
  `TaskContext.replace` does not apply.
- Any validation guard on `TaskContext.replace` (value object, orthogonal to
  lifecycle; mirrors guard-free `Task.with_context` and `record_event`).
- Deprecating or prohibiting raw `dataclasses.replace(ctx, ...)`.

## Decisions

### D1: Name `replace`, mirroring `dataclasses.replace`

The method is named `replace` — the same word as the stdlib primitive it
delegates to.

**Rationale:** discoverability. A reader who knows `dataclasses.replace`
immediately knows what `TaskContext.replace` does. The method is a typed
facade over exactly that primitive.

**Lexical-scoping safety:** inside the method body, the bare name `replace`
resolves to the *imported* `dataclasses.replace` (lexical scope, module
level), not to the method (attribute access would be `self.replace` or
`TaskContext.replace`). No recursion, no shadowing bug. Verified:

```python
from dataclasses import replace  # module-level binding

@dataclass(frozen=True)
class TaskContext:
    def replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self:
        return replace(self, **overrides)  # <- module-level binding, not the method
```

**Alternatives rejected:**
- `update` — connotes in-place mutation; clashes with frozen semantics.
- `evolve` — attrs convention, foreign to this codebase's vocabulary.
- `with_overrides` — readable and consistent with `with_*` family, but longer
  and loses the stdlib-mirror discoverability. User chose `replace`.

### D2: `Unpack[TaskContextOverrides]` (TypedDict, total=False) — PEP 692

Signature: `def replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self`
where `TaskContextOverrides(TypedDict, total=False)` lists the overridable
fields.

**Rationale:** preserves the field-name + type checking that
`dataclasses.replace` gets from the mypy plugin. A typo (`remot_folder=`) is
a type error, not a silent runtime bug. `Unpack` (PEP 692) is the standard
mechanism for typed `**kwargs` backed by a TypedDict; mypy ≥1.6 and zuban
resolve it statically. `total=False` makes every override optional, matching
the "any subset" semantics of `dataclasses.replace`.

**Alternatives rejected:**
- `**overrides: object` — loses field-name checking (the mypy plugin does
  not special-case a custom method). Silent typo bug. This is the regression
  the prior `task-with-context` brief rejected for the merge form.
- Sentinel enumeration (`def replace(self, *, engine=_UNSET, ...)`): works,
  preserves checking without TypedDict, but adds a `_UNSET` sentinel and a
  `locals()` filter idiom heavier than TypedDict+Unpack for the same outcome.
  TypedDict+Unpack reads cleaner and is the modern idiom for typed kwargs.
- Overloads per field — brittle, mirrors the field subset, combinatorial
  explosion when multiple fields are set together (consume_task sets 3 at
  once). YAGNI. `Task.with_event` uses overloads only because each event
  subclass has *different required fields* — here all overrides are optional.

### D3: TypedDict = exactly 4 fields (YAGNI)

`TaskContextOverrides` contains `remote_folder`, `local_folder`, `error`,
`extra` — the 4 fields actually overridden somewhere in the codebase (audit
by grep of `replace(...context...)` call sites). The other 3 `TaskContext`
fields (`engine`, `webhook_url`, `webhook_custom_params`) are never
overridden and are excluded.

**Rationale:** user directive (YAGNI). Adding a field not used anywhere is
speculative surface. The drift-lock test (D5) forces a TypedDict update if a
new call site overrides a currently-excluded field — the type checker also
rejects the unknown kwarg, so the omission is safe by construction.

**Risk:** if a future use case wants to override `engine`, it must add the
field to the TypedDict first. This is a one-line edit, surfaced immediately
by the type checker and the drift-lock test — acceptable friction for the
YAGNI win.

**Alternative rejected:** all 7 fields — speculative, drifts from actual
usage, no current call site needs it.

### D4: Return type `Self` (from `yascheduler.shared`)

`Self` (PEP 673) is the correct return type for a frozen-copy method on a
class that may be subclassed. `yascheduler/shared/compat.py` already
re-exports `Self` with a version branch (`typing_extensions.Self` on <3.11,
`typing.Self` on ≥3.11). `model.py` imports `Self` from `yascheduler.shared`,
matching the established pattern in `config/cloud.py`, `config/remote.py`,
`config/engine_repository.py`.

### D5: Drift-lock unit test

A unit test asserts the TypedDict key set matches the audited override-usage
set across call sites:

```python
def test_taskcontext_overrides_match_usage():
    expected = {"remote_folder", "local_folder", "error", "extra"}
    assert set(TaskContextOverrides.__annotations__) == expected
```

**Rationale:** locks both directions of drift. If a new call site overrides
`engine`, the type checker rejects `ctx.replace(engine=...)` until the
TypedDict is updated; if the TypedDict grows a field no call site uses, the
test fails. Cheap (one assertion), high value over the life of the value
object.

**Alternative rejected:** no drift-lock test — relies on the type checker
alone. The type checker catches the *new-usage* direction but not the
*unused-field* direction; the test catches both and documents the audited
set in code.

### D6: `Unpack` re-export via `yascheduler/shared/compat.py`

`compat.py` already provides version-branched re-exports for `Self` and
`ParamSpec`. Extend it symmetrically for `Unpack`:

```python
if sys.version_info < (3, 11):
    from typing_extensions import Unpack
else:
    from typing import Unpack
```

`__all__` gains `"Unpack"`. `yascheduler/shared/__init__.py` re-exports it.
`model.py` imports `Self, Unpack` from `yascheduler.shared`. `TypedDict` is
imported from `typing` (stdlib since 3.8); the drift-lock test accesses only
`__annotations__` keys, so `from __future__ import annotations` stringification
is harmless.

**Rationale:** `typing-extensions` is declared in `pyproject.toml`
`dependencies` with marker `python_version < '3.11'`. On 3.11+ it is not
installed; importing `typing_extensions` directly in `model.py` would
`ImportError` on a clean 3.11+ install. The compat shim is the codebase's
established solution to exactly this (already used for `Self`/`ParamSpec`).

**Alternative rejected:** import under `TYPE_CHECKING:` in `model.py` —
works (these are typing-only constructs, `from __future__ import annotations`
makes them strings at runtime), but diverges from the codebase's established
pattern (compat shim) and would leave `Unpack` unimportable at runtime for
any future runtime use. Consistency with `Self`/`ParamSpec` wins.

### D7: `Task.fail` / `Task.reject` internals migrated

The two internal `replace(self.context, error=reason)` calls (model.py:237,
259) migrate to `self.context.replace(error=reason)`. The outer
`replace(self, status=..., context=...)` stays as `dataclasses.replace`
(Task-level field replacement, not TaskContext-level).

**Rationale:** consolidates every `replace(...context...)` usage behind the
new method. Internal-only, zero observable change, but consistent with the
migration goal — readers never see a raw `replace(self.context, ...)` once
this change lands.

**Alternative rejected:** leave `fail`/`reject` internals on raw
`dataclasses.replace` — preserves a mixed style (raw inside the entity,
facade outside). The marginal cost of migrating is one line each; the
consistency win is worth it.

### D8: Additive-only, escape hatch preserved

`dataclasses.replace(ctx, ...)` continues to work after this change. The
method is added, the call sites are migrated, but the raw pattern is not
deprecated or prohibited.

**Rationale:** `TaskContext` is a frozen dataclass; `replace` is structural.
Banning it would require a non-frozen wrapper or a `__setattr__` override,
both worse. Public interface stability (AGENTS.md) calls for additive-only
changes to domain entity surface; this change adds a method without removing
capability. Mirrors the `task-with-context` precedent (D4 there).

## Risks / Trade-offs

- **[Drift between TypedDict and dataclass fields]** → Mitigated by D5
  (drift-lock test) and the type checker (rejects unknown kwargs). Both
  directions of drift caught.

- **[Runtime `ImportError` on Python 3.11+ if `Unpack` imported from
  `typing_extensions` directly]** → Mitigated by D6: import via
  `yascheduler.shared.compat`, which branches on `sys.version_info`. No
  `typing_extensions` import in `model.py` at runtime on 3.11+.

- **[mypy/zuban `Unpack` support]** → `Unpack` (PEP 692) supported in mypy
  ≥1.6 and zuban. Verified the project already uses `Self` (PEP 673) via the
  compat shim from `config/*`; `Unpack` is the same kind of typing construct.
  Static check gates (`uv run zuban check`, `uv run ruff check`) are in the
  task list.

- **[Lexical shadowing confusion for readers]** → The bare `replace` in the
  method body resolving to the module-level import (not the method) is
  standard Python lexical scoping, but a reader unfamiliar with it might
  suspect recursion. The `START_CONTRACT: TaskContext.replace` block notes
  this explicitly (one line). No runtime risk.

- **[Behavior change from migrating `fail`/`reject` internals]** → None.
  `self.context.replace(error=reason)` is semantically identical to
  `replace(self.context, error=reason)` (the former delegates to the latter).
  Existing tests on `saved_task.context.error` stay green.

- **[YAGNI omission bites later]** → If a future use case needs to override
  `engine`/`webhook_url`/`webhook_custom_params`, the TypedDict must be
  extended first. One-line edit, surfaced by the type checker and the
  drift-lock test. Accepted trade-off for keeping the TypedDict honest about
  actual usage.

- **[GRACE-lite markup drift]** → Mitigated: `model.py` VERSION bump
  (1.11.0 → 1.12.0), `MODULE_MAP` + `CHANGE_SUMMARY` updates, `compat.py`
  VERSION bump + `MODULE_MAP` + `CHANGE_SUMMARY`, `knowledge-graph.xml`
  `M-DOMAIN-MODEL` annotations (`<fn-replace>`, `<type-TaskContextOverrides>`)
  and `M-SHARED` annotation (`<type-Unpack>`, matching the existing
  `<type-Self>`/`<type-ParamSpec>` prefix) are explicit tasks.
  `grace_check.py` runs in verification.

- **[Additive-only means no forcing migration]** → Accepted: the escape
  hatch stays. Future code *could* use `dataclasses.replace(ctx, ...)`.
  Deliberate trade-off for public interface stability; migrated call sites
  demonstrate the intended style.

## Migration Plan

Single change, no deploy/rollback complexity:
1. Extend `yascheduler/shared/compat.py` with `Unpack` (version branch) +
   GRACE markup; bump VERSION.
2. Add `TaskContextOverrides` TypedDict + `TaskContext.replace` method +
   GRACE markup to `model.py`; bump VERSION.
3. Migrate the 4 call sites (submit_task, consume_task, model.py ×2). Check
   whether `from dataclasses import replace` becomes dead in
   `submit_task.py` and `consume_task.py` after migration; remove if unused
   (the `model.py` import stays — Task-level `replace(self, ...)` remains).
4. Add unit tests (replace suite + drift-lock test).
5. Update knowledge graph (`M-DOMAIN-MODEL`, `M-SHARED` annotations).
6. Run verification (pytest unit, ruff, zuban, lint-imports, grace_check,
   openspec validate).

No DB schema change, no config change, no external API change, no
`pyproject.toml` dependency change. Rollback is reverting the commit.

## Open Questions

None. All forks closed during explore (name, signature, TypedDict field set,
fail/reject internals, compat strategy, drift-lock, additive-only stance).