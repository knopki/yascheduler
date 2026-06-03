## Context

Phase 3.5 of the architecture migration. Use cases (Phase 3) currently call
webhooks directly — the same anti-pattern as `scheduler.py` had. Domain
Events decouple these side effects.

## Goals / Non-Goals

**Goals:**
- Define event types for task lifecycle transitions.
- Build a message bus that dispatches events after UoW commit.
- Move webhook logic from use cases to a dedicated handler.
- Remove `do_task_webhook()` from `scheduler.py`.

**Non-Goals:**
- No event sourcing or CQRS.
- No external message broker (Kafka, Redis) — in-process dispatch only.
- No events for node lifecycle (Phase 4 will add `NodeProvisioned` if needed).

## Decisions

### D1: Events as frozen dataclasses

```python
@dataclass(frozen=True)
class TaskCreated:
    task_id: int
    engine_name: str
    webhook_url: str | None
    custom_params: dict[str, object]

@dataclass(frozen=True)
class TaskAllocated:
    task_id: int
    node_ip: str
    engine_name: str

@dataclass(frozen=True)
class TaskCompleted:
    task_id: int
    local_folder: str
    has_errors: bool = False

@dataclass(frozen=True)
class TaskFailed:
    task_id: int
    reason: str

@dataclass(frozen=True)
class TaskAbandoned:
    task_id: int
    node_ip: str
```

Each event carries the minimum data needed by handlers — no domain objects.

### D2: Events collected on aggregates, dispatched by UoW

1. Use case calls `task.record_event(TaskAllocated(...))` — event appended to
   an internal list on the aggregate.
2. `uow.tasks.save(task)` persists both the task and its events.
3. `uow.commit()` persists the transaction, then iterates collected events
   and passes them to the message bus.
4. Message bus calls registered handlers.

This ensures handlers never fire before the transaction is committed.

### D3: Message bus — simple dict of list[handler]

```python
HANDLERS: dict[type, list[Callable]] = {
    TaskCreated: [webhook_handler],
    TaskAllocated: [webhook_handler],
    TaskCompleted: [webhook_handler],
    TaskFailed: [webhook_handler],
    TaskAbandoned: [webhook_handler],
}

async def handle(event: Event) -> None:
    for handler in HANDLERS.get(type(event), []):
        await handler(event)
```

Single dispatcher. No priority, no retry (handlers are responsible for
their own error handling).

### D4: Webhook handler lives in adapters/notifier

```python
# adapters/notifier/webhook.py
async def webhook_handler(event: Event, http: aiohttp.ClientSession) -> None:
    if isinstance(event, TaskCreated):
        await _send_webhook(event.task_id, TaskStatus.TO_DO, ...)
    elif isinstance(event, TaskAllocated):
        await _send_webhook(event.task_id, TaskStatus.RUNNING, ...)
    elif isinstance(event, TaskCompleted):
        await _send_webhook(event.task_id, TaskStatus.DONE, ...)
    # ...
```

The handler maps event types to webhook calls with the correct status code.
It encapsulates retry logic and error logging (moved from `do_task_webhook`).

### D5: UoW Protocol extended for events

`AbstractUnitOfWork` gains:

```python
class AbstractUnitOfWork(Protocol):
    tasks: TaskRepository
    nodes: NodeRepository
    events: list[Event]  # collected during the transaction

    async def commit(self) -> None: ...    # commits, then dispatches events
    async def rollback(self) -> None: ...   # discards events
```

`PostgresUnitOfWork.commit()` implementation:
```python
async def commit(self):
    await self._run_sync(self._conn.commit)
    for event in self._collected_events:
        await message_bus.handle(event)
    self._collected_events.clear()
```

### D6: Events optional during transition

Use cases that don't need event dispatch can skip recording events. The UoW
works correctly with an empty event list. This allows gradual adoption —
not all use cases must be converted simultaneously.

## Risks / Trade-offs

- **Handler failure doesn't rollback**: If webhook fails after commit, the
  task is DONE but webhook wasn't sent. Acceptable — webhook is best-effort.
  Current code has the same behavior (webhook exceptions are caught and logged).
- **Event list on UoW, not on aggregate**: For simplicity, events are stored
  on the UoW (list), not embedded in Task. This means aggregate-level event
  replay is not supported. Acceptable for our use case.
- **In-process dispatch only**: No persistence of events, no outbox pattern.
  If the process crashes between commit and dispatch, events are lost.
  Acceptable for v1 — webhook is non-critical.
