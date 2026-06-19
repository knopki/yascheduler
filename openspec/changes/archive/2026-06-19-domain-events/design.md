## Context

Phase 3.5 of the architecture migration. Use cases (Phase 3) currently call
webhooks directly — the same anti-pattern as `scheduler.py` had. Domain
Events decouple these side effects.

## Goals / Non-Goals

**Goals:**
- Define event types for task lifecycle transitions.
- Build a message bus that dispatches events after UoW commit.
- Move webhook logic from use cases to a dedicated handler.
- Remove `_do_task_webhook()` from `application/orchestrator.py` and `do_task_webhook`
  parameter from `allocate_task()` / `consume_task()` signatures (including
  `_validate_engine` helper in `allocate_task.py`).

**Non-Goals:**
- No event sourcing or CQRS.
- No external message broker (Kafka, Redis) — in-process dispatch only.
- No events for node lifecycle (Phase 4 will add `NodeProvisioned` if needed).

## Decisions

### D1: Events live in the domain layer

Events are domain concepts — they express business occurrences (`TaskCreated`,
`TaskAllocated`). Placing them in `domain/events.py` preserves clean layering:
`domain` has no upward dependencies; `application` imports from `domain`.

The alternative — placing events in `application/events.py` — would force
`domain/model.py` (Task record_event/pull_events) to depend upward into the
application layer, violating hexagonal architecture.

Path: `yascheduler/domain/events.py`

### D1b: Events as frozen dataclasses with typed fields

Each event subclass carries typed fields relevant to its domain meaning:

```python
@dataclass(frozen=True)
class DomainEvent:
    task_id: int
    webhook_url: str | None
    webhook_custom_params: dict[str, object]

@dataclass(frozen=True)
class TaskCreated(DomainEvent):
    engine_name: str

@dataclass(frozen=True)
class TaskAllocated(DomainEvent):
    node_ip: str
    engine_name: str

@dataclass(frozen=True)
class TaskCompleted(DomainEvent):
    local_folder: str
    has_errors: bool

@dataclass(frozen=True)
class TaskFailed(DomainEvent):
    reason: str

@dataclass(frozen=True)
class TaskAbandoned(DomainEvent):
    node_ip: str

Event = TaskCreated | TaskAllocated | TaskCompleted | TaskFailed | TaskAbandoned
```

**Rationale for typed fields over metadata dict:** Typed fields provide static
safety — handlers know exactly what data is available per event type. The
webhook handler constructs the payload dict from event fields, keeping the
serialisation concern where it belongs (adapter layer). A generic metadata dict
would lose type information at the handler boundary and make it unclear which
events carry which data.

**Rationale for `webhook_url` and `webhook_custom_params` in `DomainEvent`
base:** All task lifecycle events need the webhook URL to deliver notifications.
Currently `_do_task_webhook` extracts `webhook_url` from `task.context.to_metadata()`.
Placing these fields on the base class makes every event self-contained for
webhook delivery — the handler never needs to query a repository. Alternatives
considered: (a) query repository per event — adds DB dependency to handler and
complicates testing; (b) duplicate fields on each event subclass — redundant.
The base class approach is cleanest. Use cases populate these from
`task.context.webhook_url` and `task.context.webhook_custom_params` when
recording events.

### D2: Events collected on aggregates via immutable tuple, dispatched by UoW

`Task` is a `frozen=True` dataclass. To preserve immutability, events are stored
as a `tuple[DomainEvent, ...]` field and operations return new instances via
`dataclasses.replace()`:

```python
@dataclass(frozen=True)
class Task:
    # ... existing fields ...
    _events: tuple[DomainEvent, ...] = ()

    def record_event(self, event: DomainEvent) -> Task:
        return replace(self, _events=self._events + (event,))

    def pull_events(self) -> tuple[Task, tuple[DomainEvent, ...]]:
        return replace(self, _events=()), self._events
```

**Rationale for immutable over mutable list:** Task is `frozen=True` — all
lifecycle methods (`allocate_to`, `mark_running`, `complete`, `fail`, `reject`)
return new instances. Event recording follows the same pattern. No `__dict__`
hacks, no mutable wrapper, static analysis stays clean.

Flow:

1. Use case calls `task = task.record_event(TaskAllocated(...))` — returns a
   new Task instance with event appended.
2. `uow.tasks.save(task)` persists the task and tracks it for event collection.
3. `uow.commit()` persists the transaction, then `pull_events()` on each saved
   aggregate returns `(clean_task, collected_events)`.
4. Collected events are dispatched through the message bus.

This ensures handlers never fire before the transaction is committed.

### D3: MessageBus — class-based registry

```python
class MessageBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable]] = {}

    def register(self, event_type: type, handler: Callable) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def dispatch(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            for handler in self._handlers.get(type(event), []):
                await handler(event)
```

Handlers are registered at startup (e.g., in `Orchestrator.start()` and `di.make_daemon()`).
Single dispatcher per process. No priority, no retry (handlers are responsible for
their own error handling).

### D4: Webhook handler lives in adapters/notifier

The webhook handler requires an `aiohttp.ClientSession` for HTTP calls, but
`MessageBus.dispatch()` passes only the event to handlers. Resolution: a
closure (or `functools.partial`) captures the session at registration time.

```python
# adapters/notifier/webhook.py
async def webhook_handler(event: DomainEvent, http: aiohttp.ClientSession) -> None:
    if not event.webhook_url:
        return  # skip if no URL configured
    if isinstance(event, TaskCreated):
        await _send_webhook(event.task_id, event.webhook_url, TaskStatus.TO_DO,
                            event.webhook_custom_params, http)
    elif isinstance(event, TaskAllocated):
        await _send_webhook(event.task_id, event.webhook_url, TaskStatus.RUNNING,
                            event.webhook_custom_params, http)
    elif isinstance(event, TaskCompleted):
        await _send_webhook(event.task_id, event.webhook_url, TaskStatus.DONE,
                            event.webhook_custom_params, http)
    elif isinstance(event, TaskFailed):
        await _send_webhook(event.task_id, event.webhook_url, TaskStatus.DONE,
                            event.webhook_custom_params, http)  # DONE+error
    elif isinstance(event, TaskAbandoned):
        await _send_webhook(event.task_id, event.webhook_url, TaskStatus.DONE,
                            event.webhook_custom_params, http)  # DONE+error

# Registration in DI:
bus.register(TaskCreated, functools.partial(webhook_handler, http=session))
bus.register(TaskAllocated, functools.partial(webhook_handler, http=session))
# ... etc.
```

The handler maps event types to webhook calls with the correct status code.
`webhook_url` and `webhook_custom_params` come from the `DomainEvent` base —
no repository lookup needed. It encapsulates retry logic and error logging
(moved from `_do_task_webhook`).

### D5: UoW collects and dispatches events after commit

`AbstractUnitOfWork` Protocol gains `collect_events()` and `publish_events()`
methods. Only one concrete implementation exists (`PostgresUnitOfWork`), so
the coordination risk is minimal — both are updated in the same change.

```python
class AbstractUnitOfWork(Protocol):
    tasks: TaskRepository
    nodes: NodeRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def collect_events(self) -> list[DomainEvent]: ...
    async def publish_events(self) -> None: ...
```

`PostgresUnitOfWork` holds a `MessageBus` reference and implements both methods:

```python
class PostgresUnitOfWork(AbstractUnitOfWork):
    def __init__(self, ..., bus: MessageBus):
        self._bus = bus
        self._saved_tasks: list[Task] = []

    async def collect_events(self) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        remaining: list[Task] = []
        for task in self._saved_tasks:
            clean_task, task_events = task.pull_events()
            events.extend(task_events)
            remaining.append(clean_task)
        self._saved_tasks = remaining
        return events

    async def publish_events(self) -> None:
        events = await self.collect_events()
        await self._bus.dispatch(events)
        self._saved_tasks.clear()

    async def commit(self):
        await self._run_sync(self._conn.commit)
        await self.publish_events()

    async def rollback(self):
        await self._run_sync(self._conn.rollback)
        self._saved_tasks.clear()  # discard events
```

`tasks.save(task)` appends to `_saved_tasks` so that `collect_events()` can
pull events from all aggregates touched in the transaction. The tracking is
done in the UoW wrapper:

```python
class PostgresTaskRepository(TaskRepository):
    def __init__(self, conn, saved_tasks: list[Task]):
        self._conn = conn
        self._saved_tasks = saved_tasks

    async def save(self, task: Task) -> None:
        # ... persist task to DB ...
        self._saved_tasks.append(task)
```

### D6: Empty events tuple is a valid initial state

The aggregate starts with `_events=()` by default. Use cases that don't record
events simply never call `record_event()` — `pull_events()` returns an empty
tuple. All use cases are converted in this change (no phased rollout).

### D7: Use-case-to-event mapping

| Location | Event recorded | When |
|---|---|---|
| `submit_task` | `TaskCreated(task_id, webhook_url, webhook_custom_params, engine_name)` | Always on new task submission |
| `allocate_task._allocate_free_machine` | `TaskAllocated(task_id, webhook_url, webhook_custom_params, node_ip, engine_name)` | After task allocated to a node |
| `allocate_task._validate_engine` | `TaskFailed(task_id, webhook_url, webhook_custom_params, reason="unsupported engine")` | When engine not found |
| `consume_task` | `TaskCompleted(task_id, webhook_url, webhook_custom_params, local_folder, has_errors)` | On successful task completion |
| `consume_task` | `TaskFailed(task_id, webhook_url, webhook_custom_params, reason)` | On task failure |
| `orchestrator._task_consumer_consumer` | `TaskAbandoned(task_id, webhook_url, webhook_custom_params, node_ip)` | After `task.fail("node is gone")` when node disappeared |

All events populate `webhook_url` and `webhook_custom_params` from
`task.context` at recording time.

All use cases are converted in this change — no phased rollout. The empty
`_events` tuple is a structural invariant (valid initial state), not a
migration mechanism.

### D8: Task rejection uses TaskFailed, not a separate event type

`Task.reject()` is called only from `_validate_engine` in `allocate_task.py`
when an engine is unsupported. The proposal records `TaskFailed(reason)` there
instead of introducing a separate `TaskRejected` event type. Rationale: reject
is a failure during validation — semantically it's the same as `TaskFailed`.
The webhook handler sends DONE+error in both cases, so no behavioural change.

### D9: Orchestrator cleanup

`application/orchestrator.py` changes:
- Remove `_do_task_webhook()` method entirely.
- Remove `do_task_webhook` parameter from `_allocator_consumer` and
  `_task_consumer_consumer` call-sites.
- `_task_consumer_consumer`: after `task.fail("node is gone")`, record
  `TaskAbandoned` via `task = task.record_event(TaskAbandoned(
  task_id=task.task_id, webhook_url=task.context.webhook_url,
  webhook_custom_params=task.context.webhook_custom_params, node_ip=ip))`
  instead of calling `_do_task_webhook`.
- Remove `webhook_sem` and `http` session management (moved to
  `adapters/notifier/webhook.py`).

### D10: Use case changes

`application/submit_task.py`:
- Record `TaskCreated` event after task creation: `task = task.record_event(
  TaskCreated(task_id=task.task_id, webhook_url=task.context.webhook_url,
  webhook_custom_params=task.context.webhook_custom_params,
  engine_name=task.context.engine))`.
  This is additive — currently no webhook fires on submission. After this change,
  webhook fires on creation (behavioural change noted in proposal).

`application/allocate_task.py`:
- Remove `do_task_webhook` parameter from `allocate_task()` and `_validate_engine()`.
- `_allocate_free_machine`: record `TaskAllocated(task_id=task.task_id,
  webhook_url=task.context.webhook_url,
  webhook_custom_params=task.context.webhook_custom_params,
  node_ip=ip, engine_name=task.context.engine)` instead of calling webhook.
- `_validate_engine`: record `TaskFailed(task_id=task.task_id,
  webhook_url=task.context.webhook_url,
  webhook_custom_params=task.context.webhook_custom_params,
  reason="unsupported engine")` instead of calling webhook.

`application/consume_task.py`:
- Remove `do_task_webhook` parameter from `consume_task()`.
- Record `TaskCompleted(task_id=task.task_id,
  webhook_url=task.context.webhook_url,
  webhook_custom_params=task.context.webhook_custom_params,
  local_folder=..., has_errors=...)` or `TaskFailed(task_id=task.task_id,
  webhook_url=task.context.webhook_url,
  webhook_custom_params=task.context.webhook_custom_params,
  reason=...)` depending on outcome.

### D11: Domain exports

`domain/__init__.py` updated to export all event types and the `Event` union
type alias from `domain.events`.

## Risks / Trade-offs

- **Handler failure doesn't rollback**: If webhook fails after commit, the
  task is DONE but webhook wasn't sent. Acceptable — webhook is best-effort.
  Current code has the same behavior (webhook exceptions are caught and logged).
- **Event tuple on aggregate**: Events are stored on the Task aggregate as an
  immutable `_events: tuple[DomainEvent, ...]` via `record_event()` /
  `pull_events()`. Both return new Task instances — no mutation of frozen
  dataclass. The UoW calls `pull_events()` after commit and dispatches through
  the message bus. Aggregate-level event replay is not supported beyond
  `pull_events()` — acceptable for our use case.
- **In-process dispatch only**: No persistence of events, no outbox pattern.
  If the process crashes between commit and dispatch, events are lost.
  Acceptable for v1 — webhook is non-critical.
