## 1. Domain aggregate

- [x] 1.1 Add `Task.with_event` to `yascheduler/domain/model.py`: five `@overload` declarations (one per concrete event subclass, keyword-only subclass-specific fields via `*`) + generic runtime implementation (`TypeVar` bound to `DomainEvent`, silent pop of `task_id`/`webhook_url`/`webhook_custom_params`, construct from `self.context`, delegate to `record_event`). Imports: `overload`, `TypeVar` from `typing`; event classes from `.events`.
- [x] 1.2 Update `MODULE_MAP` and `CHANGE_SUMMARY` in `yascheduler/domain/model.py` (add `with_event` to the Task description; bump VERSION; record the change). Add a `START_CONTRACT: Task.with_event` block above the method matching the style of `Task.record_event` (PURPOSE/INPUTS/OUTPUTS/SIDE_EFFECTS/LINKS).
- [x] 1.3 Update `docs/knowledge-graph.xml` `<class-Task>` annotation PURPOSE to mention `with_event`.

## 2. Call-site conversions

- [x] 2.1 `yascheduler/application/submit_task.py:92-99` — replace `task.record_event(TaskCreated(task_id=..., webhook_url=..., webhook_custom_params=..., engine_name=task.context.engine))` with `task.with_event(TaskCreated, engine_name=task.context.engine)`.
- [x] 2.2 `yascheduler/application/allocate_task.py:86-93` (in `_validate_engine`) — replace `task.record_event(TaskFailed(...))` with `task.with_event(TaskFailed, reason="unsupported engine")`.
- [x] 2.3 `yascheduler/application/allocate_task.py:143-151` (in `_try_start_on_machine`) — replace `task.record_event(TaskAllocated(...))` with `task.with_event(TaskAllocated, node_ip=machine.ip, engine_name=task.context.engine)`.
- [x] 2.4 `yascheduler/application/consume_task.py:109-116` (in `_record_finalization_event`, failure branch) — replace `task.record_event(TaskFailed(...))` with `task.with_event(TaskFailed, reason=error_msg)`.
- [x] 2.5 `yascheduler/application/consume_task.py:119-127` (in `_record_finalization_event`, success branch) — replace `task.record_event(TaskCompleted(...))` with `task.with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)`.
- [x] 2.6 `yascheduler/application/orchestrator.py:310-317` (in `_task_consumer_consumer`) — replace `task.record_event(TaskAbandoned(...))` with `task.with_event(TaskAbandoned, node_ip=ip)`. Verify `task.fail("node is gone")` ran first so webhook fields are preserved in context.

## 3. Tests

- [x] 3.1 Add `TestTaskWithEvent` suite to `tests/unit/test_domain_events.py` covering: base-field substitution from context; keyword-only subclass fields (positional call raises TypeError); silent pop of base-field collisions; delegation to `record_event` via `pull_events`; `with_event` after `fail()` reads preserved webhook fields; `record_event` still works as the low-level primitive. Add `with_event` to the test file MODULE_MAP/CHANGE_SUMMARY.
- [x] 3.2 Confirm existing `TestTaskEvents` (record_event/pull_events) and event-construction tests still pass unchanged.

## 4. Validation

- [x] 4.1 `uv run pytest -m unit` passes.
- [x] 4.2 `uv run zuban check` passes.
- [x] 4.3 `uv run ruff check .` and `uv run ruff format --check .` pass.
- [x] 4.4 `uv run lint-imports` passes.
- [x] 4.5 `python3 scripts/grace_check.py` passes (markup + graph cross-refs).
- [x] 4.6 `openspec validate --all --json` passes.