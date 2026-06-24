# Explore brief: task-with-event

## Problem
Six call sites manually copy `task_id`, `webhook_url`, `webhook_custom_params`
from `task.context` into every domain event constructor. Boilerplate, error-
prone, and couples call sites to the base-class field set.

## Alternatives rejected
- **Remove webhook fields from DomainEvent, look up from Task at dispatch.**
  Rejected: webhook_handler is a pure `event → HTTP POST` adapter with no
  persistence dependency. Looking up Task post-commit would add a DB round-
  trip per event and a new cross-layer dependency (notifier → persistence).
  Snapshot semantics on the event is the right design; the pain is the
  boilerplate, not the fields.
- **ParamSpec/Concatenate to type-check kwargs against event constructors.**
  Rejected: dataclass `__init__` is synthesized; mypy treats it specially and
  does not reliably bind `Callable[Concatenate[...], E]` to it. Also requires
  positional-only prefix fields, which dataclass base fields are not. Risk of
  silent `Any` inference — false safety, worse than explicit `**fields`.
- **Unpack[TypedDict] (PEP 692).** Rejected: dict-literal ergonomics worse than
  kwargs; less mature mypy support.

## Selected approach: `Task.with_event` with 5 `@overload` declarations
- One overload per concrete event type. `*` makes subclass-specific fields
  keyword-only (no positional-order mistakes). mypy checks required fields
  and types per event type.
- Runtime impl is generic `with_event(self, event_type, **fields)`; pops
  `task_id`/`webhook_url`/`webhook_custom_params` silently if a caller passes
  them (collision guard), then constructs from `self.context`.
- `record_event(event)` remains the low-level primitive (tests, append-only
  contract); `with_event` is the convenience factory over it.

## Call sites to convert (6)
| File | Line | Current | Target |
|---|---|---|---|
| application/submit_task.py | 92-99 | `TaskCreated(task_id=..., webhook_url=..., webhook_custom_params=..., engine_name=...)` | `task.with_event(TaskCreated, engine_name=task.context.engine)` |
| application/allocate_task.py | 86-93 | `TaskFailed(..., reason="unsupported engine")` | `task.with_event(TaskFailed, reason="unsupported engine")` |
| application/allocate_task.py | 143-151 | `TaskAllocated(..., node_ip=..., engine_name=...)` | `task.with_event(TaskAllocated, node_ip=machine.ip, engine_name=task.context.engine)` |
| application/consume_task.py | 109-116 | `TaskFailed(..., reason=error_msg)` | `task.with_event(TaskFailed, reason=error_msg)` |
| application/consume_task.py | 119-127 | `TaskCompleted(..., local_folder=..., has_errors=False)` | `task.with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)` |
| application/orchestrator.py | 310-317 | `TaskAbandoned(..., node_ip=ip)` | `task.with_event(TaskAbandoned, node_ip=ip)` |

## Specs touched
- `message-bus` (MODIFIED): the "Use-case-to-event mapping" requirement's
  scenarios currently hardcode full constructors
  (`task.record_event(TaskCreated(task_id=..., webhook_url=..., ...))`).
  Reword to `task.with_event(TaskCreated, engine_name=...)` form. Behavior
  unchanged (same events, same fields, same dispatch path).
- `domain-events` (UNCHANGED): event *type* shape (fields on each subclass
  and base) is unchanged. Spec describes the data contract, not the call
  form.
- `webhook-handler` (UNCHANGED): handler reads `event.webhook_url` /
  `event.webhook_custom_params`; agnostic to how the event was constructed.
- `domain-entities` (UNCHANGED): covers Task lifecycle methods
  (`allocate_to`, `mark_running`, `complete`, `fail`, `reject`), not the
  event-recording API. The event-recording API lives in `message-bus`.

## Cross-module data flow (unchanged)
use case → `task.with_event(EventType, **specific)` → constructs event with
`task_id` + webhook fields from `task.context` + caller fields →
`task.record_event(event)` appends to `_events` tuple → `uow.tasks.save(task)`
→ `uow.commit()` → `pull_events()` → `MessageBus.dispatch()` →
`webhook_handler(event, http)`.

## Open questions: none
All resolved during exploration:
- Name: `with_event` (returns Task with event, builds from type).
- Overloads for type safety at call sites.
- `record_event` kept as primitive, not deprecated.
- Silent pop on base-field collision (no TypeError).
- Python 3.9 compatible (TypeVar bound + `**fields: object`).
- Proposal created (public API on aggregate + spec rewording = audit trail).