## Why

Every domain event recording site manually copies `task_id`, `webhook_url`, and `webhook_custom_params` out of `task.context` into the event constructor — six call sites across four files, same three-line boilerplate each. This couples call sites to the `DomainEvent` base-class field set and invites copy-paste mistakes. A factory method on the `Task` aggregate that pulls those base fields from `task.context` and accepts only the subclass-specific fields removes the boilerplate while keeping events as self-contained snapshots.

## What Changes

- Add `Task.with_event(event_type, **fields) -> Task` to the `Task` aggregate (`yascheduler/domain/model.py`). It constructs an event of the given type with `task_id`, `webhook_url`, `webhook_custom_params` populated from `self.context` and the caller-supplied subclass-specific fields, then appends it via the existing `record_event` primitive. Five `@overload` declarations (one per concrete event type) give keyword-only, mypy-checked call sites.
- Convert the six event-recording call sites to `task.with_event(...)`:
  - `application/submit_task.py` — `TaskCreated`
  - `application/allocate_task.py` — `TaskFailed` (in `_validate_engine`), `TaskAllocated` (in `_try_start_on_machine`)
  - `application/consume_task.py` — `TaskFailed`, `TaskCompleted` (in `_record_finalization_event`)
  - `application/orchestrator.py` — `TaskAbandoned` (in `_task_consumer_consumer`)
- `Task.record_event(event)` remains unchanged as the low-level append primitive.
- Reword the "Use-case-to-event mapping" scenarios in the `message-bus` spec from hardcoded full constructors (`task.record_event(TaskCreated(task_id=..., webhook_url=..., webhook_custom_params=..., ...))`) to the `task.with_event(EventType, ...)` form. Observable behavior is unchanged: the same events with the same fields are recorded and dispatched.

## Capabilities

### New Capabilities
<!-- None. with_event is a convenience factory over the existing record_event/pull_events/dispatch path; it introduces no new spec-level behavior. -->

### Modified Capabilities
- `message-bus`: The "Use-case-to-event mapping" requirement scenarios are reworded to use `task.with_event(EventType, **specific_fields)` instead of hardcoded full event constructors. The mapping table gains a `with_event call` column and corrects two use-case column entries to the precise functions where recording happens (`_try_start_on_machine`, `_record_finalization_event`); the event→trigger mapping is unchanged. A new requirement documents `Task.with_event` as the aggregate factory method for event recording from context.

## Impact

- **Code**: `yascheduler/domain/model.py` (new method + overloads); six call sites across `submit_task.py`, `allocate_task.py`, `consume_task.py`, `orchestrator.py`. No new dependencies; uses existing `typing.overloads` and a `TypeVar` bound to `DomainEvent`.
- **APIs**: `Task.with_event` is a new public method on the domain aggregate. `Task.record_event` is unchanged. No CLI, client, INI, DB schema, or AiiDA changes.
- **Tests**: `tests/unit/test_domain_events.py` gains a `TestTaskWithEvent` suite (base-field substitution from context, keyword-only subclass fields, silent collision pop, integration with `pull_events`). Existing event-construction and `record_event` tests are unchanged.
- **GRACE**: `MODULE_MAP` and `CHANGE_SUMMARY` in `model.py` updated; `<class-Task>` annotation in `docs/knowledge-graph.xml` updated to mention `with_event`.
- **Behavior**: Observable behavior is identical — the same events with the same fields are recorded, collected, and dispatched. No migration needed.