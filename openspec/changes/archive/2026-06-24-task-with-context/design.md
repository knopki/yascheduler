## Context

`Task` is a frozen dataclass (`yascheduler/domain/model.py`) exposing a
fluent, copy-with-return style: every lifecycle method (`allocate_to`,
`mark_running`, `complete`, `fail`, `reject`) and the event API
(`record_event`, `with_event`, `pull_events`) returns a new `Task` via
`dataclasses.replace(self, ...)`. The one place this style breaks is when a
use case needs to replace `task.context`: it drops to raw
`dataclasses.replace(task, context=...)`, leaking the entity boundary and
breaking the fluent chain.

`Task.with_event` (added in v1.10.0) is the direct precedent: a fluent
factory that constructs an event from `self.context` and records it. This
change adds the symmetric `with_context` — a fluent setter that replaces the
context wholesale and returns the new `Task`.

Current call sites (verified by grep, no others exist):
- `application/submit_task.py:91` — `replace(task, context=context)` after
  building a new `TaskContext` with `replace(task.context, remote_folder=...)`.
- `application/consume_task.py:108, 111` — `replace(task, context=updated_context)`
  in both the sftp-errors and success branches of `_record_finalization_event`.
- `application/consume_task.py:107` — a redundant
  `replace(updated_context, error=error_msg)` immediately before
  `.fail(error_msg)` (which sets `context.error` internally); drift, identical
  final context.

## Goals / Non-Goals

**Goals:**
- Add `Task.with_context(context: TaskContext) -> Task` — wholesale context
  replacement, returns new `Task`, no merge, no validation guard.
- Migrate the 3 `replace(task, context=...)` call sites to `with_context`.
- Drop the redundant `context.error` set in `consume_task.py:107`.
- Preserve the existing `replace(task, context=...)` escape hatch
  (additive-only; frozen dataclass keeps it valid).

**Non-Goals:**
- `TaskContext.with(**overrides)` copy-with helper — follow-up change.
- Converting `Task.fail`/`Task.reject` internals to `with_context` — they
  set both `status` and `context` in one `replace(self, ...)`; the
  context-only `with_context` does not help.
- Prohibiting or deprecating `replace(task, context=...)`.
- Any validation guard on context replacement (context is metadata,
  orthogonal to status; mirrors guard-free `record_event`).

## Decisions

### D1: Wholesale replacement, not merge

`with_context(context: TaskContext)` replaces `self.context` entirely. No
`**overrides`, no per-field merge into `self.context`.

**Rationale:** A merge form `with_context(**overrides)` would lose the mypy
field-name checking that `replace(self.context, ...)` provides today (a typo
in a `TaskContext` field name is a mypy error on `replace`; it would not be
on `**overrides: object`). Wholesale replacement with a typed single
argument keeps full static safety. Call sites that need to change one field
keep building the new `TaskContext` via `replace(task.context, field=...)`
(the `TaskContext.with` helper is a follow-up change).

**Alternative rejected:** `with_context(**overrides: object)` delegating to
`replace(self.context, **overrides)` — loses field-name checking, couples
`Task` to `TaskContext`'s field set.

### D2: Single typed argument, no overloads

One signature: `with_context(self, context: TaskContext) -> Task`. No
enumerated overloads per `TaskContext` field.

**Rationale:** Overloads would mirror `TaskContext`'s field set and drift on
change. The single typed argument is mypy-safe and sufficient. Contrast with
`with_event`, which uses 5 overloads because each event subclass has
different required fields — `TaskContext` is a single value object, not a
family.

**Alternative rejected:** enumerated overloads — brittle, YAGNI.

### D3: No validation guard

`with_context` performs no state check. Any `Task`, in any status, can have
its context replaced.

**Rationale:** `TaskContext` is metadata (engine name, paths, webhook config,
extras), orthogonal to the task's lifecycle status. `record_event` is
similarly guard-free. Adding a guard would invent a constraint that does not
exist semantically and would block legitimate use (e.g. a use case updating
`remote_folder` on a TO_DO task before persistence, as `submit_task` does
today).

**Alternative rejected:** forbid context change on DONE tasks — invents a
rule with no basis in the domain.

### D4: Additive-only, escape hatch preserved

`replace(task, context=...)` continues to work after this change. The
method is added, the call sites are migrated, but the raw `dataclasses.replace`
pattern is not deprecated or prohibited.

**Rationale:** `Task` is a frozen dataclass; `replace` is structural. Banning
it would require a non-frozen wrapper or a `__setattr__` override, both worse.
Public interface stability (AGENTS.md) calls for additive-only changes to
`class Yascheduler` and the domain entity surface; this change adds a method
without removing capability.

### D5: Cleanup of redundant `context.error` set in consume_task

`consume_task.py:107` does `updated_context = replace(updated_context, error=error_msg)`
immediately before `task = replace(task, context=updated_context).fail(error_msg)`.
But `Task.fail(reason)` internally does
`replace(self, status=DONE, context=replace(self.context, error=reason))` —
it sets `context.error` itself. The explicit set on line 107 is drift,
producing an identical final context (same `error` value, same source
`error_msg`, `local_folder`/`remote_folder`/`extra` carried by
`updated_context` either way).

**Rationale:** Removing line 107 changes no observable behavior. The
post-cleanup chain reads cleanly:
`task.with_context(updated_context).fail(error_msg).with_event(TaskFailed, reason=error_msg)`.

**Risk check:** `Task.fail` raises `TaskNotRunningError` if `status != RUNNING`.
This is **existing** behavior — line 108 already calls `.fail(error_msg)`
today, so any non-RUNNING task would already raise. The cleanup does not
introduce this constraint; it only removes a redundant line above it.

## Risks / Trade-offs

- **[mypy field-checking loss at call sites]** → Mitigated: call sites keep
  using `replace(task.context, field=...)` to build the new `TaskContext`
  (the `TaskContext.with` helper is deferred). `with_context` only takes the
  fully-built `TaskContext`, so no field-name checking is lost in the
  migrated code. The merge form that *would* lose checking was rejected (D1).

- **[Behavior change from consume_task cleanup]** → Mitigated: verified the
  final context is identical with and without line 107 (same `error` value
  from the same `error_msg` source; `fail`'s internal `replace(self.context,
  error=reason)` produces the same result). The `TaskNotRunningError` guard
  in `.fail()` is pre-existing, not introduced by the cleanup. Existing
  `test_application_use_cases.py` and `test_application_orchestrator.py`
  assertions on `saved_task.context.error` stay green.

- **[GRACE-lite markup drift]** → Mitigated: `model.py` VERSION bump
  (1.10.0 → 1.11.0), `MODULE_MAP` and `CHANGE_SUMMARY` updates, and
  `knowledge-graph.xml` `M-DOMAIN-MODEL` annotation are all listed as explicit
  tasks. `grace_check.py` runs in verification.

- **[Additive-only means no forcing migration]** → Accepted: the escape
  hatch stays. Future code *could* use `replace(task, context=...)` directly.
  This is a deliberate trade-off for public interface stability; the migrated
  call sites demonstrate the intended style, and the `TaskContext.with`
  follow-up will further reduce the raw-`replace` surface.

## Migration Plan

Single-change, no deploy/rollback complexity:
1. Add `Task.with_context` + GRACE markup + knowledge graph annotation.
2. Migrate the 3 call sites + drop the redundant line 107.
3. Add unit tests.
4. Run verification (pytest unit, ruff, zuban, grace_check, openspec validate).

No DB schema change, no config change, no external API change, no
dependency change. Rollback is reverting the commit.

## Open Questions

None. All forks closed during explore (validation policy, versioning,
consume_task cleanup, AiiDA plugin impact).