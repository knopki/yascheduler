## Context

Six call sites record domain events by constructing full event instances with `task_id`, `webhook_url`, `webhook_custom_params` copied from `task.context` plus the subclass-specific fields. Example (`application/submit_task.py:92-99`):

```python
task = task.record_event(
    TaskCreated(
        task_id=task.task_id,
        webhook_url=task.context.webhook_url,
        webhook_custom_params=task.context.webhook_custom_params,
        engine_name=task.context.engine,
    )
)
```

The three base fields are identical across every event type. The `DomainEvent` base class (`yascheduler/domain/events.py:31-35`) is a frozen dataclass; its fields are required on every subclass constructor. Events are recorded on the `Task` aggregate via `record_event` (`yascheduler/domain/model.py:262-263`), collected by `PostgresUnitOfWork.collect_events`, and dispatched through `MessageBus` to `webhook_handler`, which reads `event.webhook_url` / `event.webhook_custom_params` and is a pure `event → HTTP POST` adapter with no persistence dependency.

Python 3.9 is the minimum (`pyproject.toml`). `typing.ParamSpec` is available via the `shared/compat.py` shim.

## Goals / Non-Goals

**Goals:**
- Remove the per-call-site boilerplate of copying `task_id`, `webhook_url`, `webhook_custom_params` from `task.context`.
- Keep mypy checking of subclass-specific fields (required fields and their types) at each call site, so a typo like `task.with_event(TaskAllocated, reason="x")` is a type error.
- Preserve the existing event snapshot semantics: the event carries its own delivery address; `webhook_handler` stays persistence-free.
- Leave `record_event(event)` as the low-level append primitive for tests and any direct event-construction path.
- Reword the "Use-case-to-event mapping" scenarios in the `message-bus` spec from hardcoded full constructors to the `task.with_event(EventType, **specific_fields)` form. Observable behavior unchanged.

**Non-Goals:**
- Do not remove `webhook_url` / `webhook_custom_params` from `DomainEvent` — the event remains a self-contained snapshot.
- Do not change the dispatch path (`record_event` → `_events` tuple → `uow.commit` → `pull_events` → `MessageBus.dispatch` → `webhook_handler`).
- Do not change `DomainEvent` or any subclass field set — event type shape is unchanged.
- Do not address the `allocate_task.py:94` FIXME about `_validate_engine` mutating in a new transaction; that is a separate concern.

## Decisions

### D1: `Task.with_event(event_type, **fields) -> Task` with five `@overload` declarations

**Choice.** Add a single method `with_event` to the `Task` aggregate that (a) constructs an event of the given type with `task_id`, `webhook_url`, `webhook_custom_params` taken from `self.context` and the caller-supplied subclass-specific fields, then (b) appends it via the existing `record_event` primitive. Type-checking at call sites is provided by five `@overload` declarations — one per concrete event subclass — each declaring the subclass-specific fields as keyword-only (via `*`):

```python
@overload
def with_event(self, event_type: type[TaskCreated], *, engine_name: str) -> Task: ...
@overload
def with_event(self, event_type: type[TaskAllocated], *, node_ip: str, engine_name: str) -> Task: ...
@overload
def with_event(self, event_type: type[TaskCompleted], *, local_folder: str, has_errors: bool) -> Task: ...
@overload
def with_event(self, event_type: type[TaskFailed], *, reason: str) -> Task: ...
@overload
def with_event(self, event_type: type[TaskAbandoned], *, node_ip: str) -> Task: ...
def with_event(self, event_type: type[E], **fields: object) -> Task:
    # runtime impl (see D3)
```

**Rationale.** The method belongs on `Task` because the base fields live on `task.context` — only the aggregate knows how to populate them. Keyword-only subclass fields (`*`) prevent positional-order mistakes (e.g. swapping `node_ip` and `engine_name`). Five overloads is a bounded set (the event hierarchy is stable: five concrete subclasses since the `domain-events` proposal, unchanged). Zero runtime cost: overloads are erased at runtime; the single generic implementation handles all cases.

**Alternative considered — generic `with_event(event_type, **fields)` with no overloads.** Simpler, but loses mypy checking of subclass-specific fields: `task.with_event(TaskAllocated, reason="x")` would type-check instead of erroring. Rejected because the whole point is catching such mistakes at the call site.

**Alternative considered — `ParamSpec` / `Concatenate` against the dataclass `__init__`.** The idea: bind the dataclass constructor's signature and strip the base fields via `Concatenate[task_id_type, webhook_url_type, webhook_custom_params_type, P]`. Rejected because (a) dataclass `__init__` is synthesized and mypy treats dataclasses specially — binding `Callable[Concatenate[...], E]` to it is unreliable and risks silent `Any` inference (false safety, worse than explicit `**fields`); (b) `Concatenate` requires a positional-only prefix, which dataclass base fields are not; (c) the three base fields are heterogeneous (`int`, `str | None`, `dict[str, object]`), so `Concatenate` would drag them into the `with_event` signature, coupling it to base-class shape changes. Overloads avoid all three issues.

**Alternative considered — `Unpack[TypedDict]` (PEP 692).** Rejected: requires dict-literal ergonomics (worse than kwargs at the call site) and has less mature mypy support.

### D2: `record_event` remains unchanged as the low-level primitive

`record_event(event: DomainEvent) -> Task` (`model.py:262-263`) is unchanged. It is the append primitive; `with_event` is the convenience factory that constructs the event and delegates to `record_event`. Tests that construct events directly and call `record_event` (`tests/unit/test_domain_events.py:TestTaskEvents`) continue to work. Not deprecated — both coexist.

### D3: Runtime implementation — silent pop of base-field collisions

The generic runtime implementation pops `task_id`, `webhook_url`, `webhook_custom_params` from `**fields` if a caller passes them, then constructs the event from `self.context` for those three and the remaining `**fields` for the subclass-specific ones:

```python
E = TypeVar("E", bound=DomainEvent)

def with_event(self, event_type: type[E], **fields: object) -> Task:
    fields.pop("task_id", None)
    fields.pop("webhook_url", None)
    fields.pop("webhook_custom_params", None)
    event = event_type(
        task_id=self.task_id,
        webhook_url=self.context.webhook_url,
        webhook_custom_params=self.context.webhook_custom_params,
        **fields,
    )
    return self.record_event(event)
```

**Silent pop, not `raise TypeError`.** If a caller passes `task_id` in `**fields`, the overload signatures already make that a mypy error (the overload declares only subclass-specific fields). The runtime pop is a defensive guard against untyped callers and against a "double-bind" crash (passing `task_id` both via context and via kwargs would otherwise raise `TypeError: multiple values for keyword argument 'task_id'`). Silent pop matches the principle "caller's intent = caller's problem" and avoids a runtime crash on a path that is already a type error.

### D4: `orchestrator.py:310-317` — `with_event` reads context after `task.fail()`

At the converted site in `_task_consumer_consumer`, the code does `task = task.fail("node is gone")` before recording the event. `fail()` (`model.py:219-231`) returns `replace(self, status=DONE, context=replace(self.context, error=reason))` — it sets `context.error` but preserves `context.webhook_url` and `context.webhook_custom_params`. So `task.with_event(TaskAbandoned, node_ip=ip)` reads the preserved webhook fields from context. Semantically equivalent to the current explicit constructor call. Verified against `model.py`.

## Risks / Trade-offs

- **Five overload declarations must track the event hierarchy.** If a new event subclass is added, a corresponding overload must be added or that type falls back to the generic (untyped `**fields`) signature. Mitigation: the hierarchy is stable and small; a new event type is a deliberate change that would touch `events.py` and the `message-bus` mapping table anyway, so adding one overload is incremental.
- **Silent pop masks a real mistake if a caller passes `task_id` in untyped code.** Mitigation: typed call sites get a mypy error via the overload; the pop only protects untyped paths from crashing, not from being wrong.
- **`with_event` adds a second event-recording API on `Task`.** Two methods (`record_event`, `with_event`) could confuse readers. Mitigation: `with_event` is the convenience factory for context-sourced construction; `record_event` is the primitive for pre-constructed events. The distinction is documented in contracts and in the `message-bus` spec.
- **No behavioral risk.** Observable behavior is identical: the same events with the same fields are recorded, collected, and dispatched. No migration, no rollback strategy needed.