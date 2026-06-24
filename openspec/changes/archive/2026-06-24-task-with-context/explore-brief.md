# Explore Brief — task-with-context

## Alternatives rejected

- **`with_context(**overrides)` merging into `self.context`**: rejected —
  loses mypy field-name checking that `replace(self.context, ...)` gives today,
  requires `Task` to know `TaskContext` fields. User explicitly rejected the
  merge form.
- **`TaskContext.with(**overrides)` helper**: rejected for THIS change —
  deferred to a follow-up change. `TaskContext` copy-with stays via raw
  `dataclasses.replace` at call sites for now.
- **Enumerated overloads per `TaskContext` field**: rejected — brittle,
  mirrors `TaskContext` field set, drifts on change. YAGNI for the single
  typed-argument form chosen.
- **Converting internal `fail`/`reject` to use `with_context`**: rejected —
  they set both `status` and `context` in one `replace(self, ...)` call;
  `with_context` (context-only) does not help them, and the conversion is
  internal-only (readers never see it), zero readability gain.
- **Adding a `with_context` validation guard** (e.g. forbid context change in
  DONE state): rejected — `TaskContext` is metadata orthogonal to status;
  `record_event` is also guard-free; matches existing precedent.

## Final approach (labels / mapping)

Single method on `Task`:

```python
def with_context(self, context: TaskContext) -> Task:
    return replace(self, context=context)
```

- Pure wholesale replacement — no merge, no per-field overrides.
- Typed single argument → mypy-safe (no field-name checking loss).
- No validation guard (orthogonal to status, mirrors `record_event`).
- Additive-only: `replace(task, context=...)` stays valid (frozen dataclass);
  call sites migrated, pattern not prohibited. Public interface stability
  preserved.

## Cross-module data flows

Call sites migrated (3 logical, in 2 files):

1. `yascheduler/application/submit_task.py:90-91` — set `remote_folder`:
   ```
   context = replace(task.context, remote_folder=remote_folder)   # stays (TaskContext helper is follow-up)
   task = task.with_context(context)                               # was: replace(task, context=context)
        .with_event(TaskCreated, engine_name=task.context.engine)
   ```

2. `yascheduler/application/consume_task.py:98-114` — finalize context, then
   branch on sftp_errors:
   ```
   updated_context = replace(task.context, local_folder=..., remote_folder=..., extra=...)  # stays
   if sftp_errors:
       # CLEANUP: drop redundant `replace(updated_context, error=error_msg)`
       # — `.fail(error_msg)` already sets context.error internally.
       task = task.with_context(updated_context).fail(error_msg).with_event(TaskFailed, reason=error_msg)
   else:
       task = task.with_context(updated_context).complete().with_event(TaskCompleted, ...)
   ```

NOT migrated (out of scope):
- `model.py:237,259` — internal to `Task.fail`/`Task.reject`, both set status
  AND context in one `replace(self, ...)`; `with_context` (context-only) does
  not help.
- `tests/unit/test_application_use_cases.py:117`,
  `tests/unit/test_application_events.py:70` — `replace(task, task_id=42)`
  is Task-level (not context); unrelated, stays.

## Known open questions

None remaining. All forks closed during explore:
1. Validation policy → no guard (mirrors `record_event`).
2. Versioning → minor bumps where new domain API is consumed.
3. consume_task error-branch double-set of `context.error` → clean up (drop
   the explicit `replace(updated_context, error=...)`, rely on `.fail()`'s
   internal set; final context is identical, behavior preserved).
4. AiiDA plugin → read-only consumer, does not use `replace(task, context=...)`;
   unaffected (verified by grep).