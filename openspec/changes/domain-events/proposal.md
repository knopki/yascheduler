## Why

Phase 3.5 of the architecture migration. Phase 3 (`application-layer`)
extracted use cases from `scheduler.py`, but webhook calls remain scattered
across use cases — called inline before/after `uow.commit()` with
inconsistent ordering.

Domain Events decouple side effects from business logic: use cases record
events on aggregates, the message bus dispatches them AFTER commit. This
centralises webhook logic in one handler module and prevents the class of
bugs where side effects fire before persistence is confirmed.

## What Changes

- Create `application/events.py` with event dataclasses: `TaskCreated`,
  `TaskAllocated`, `TaskCompleted`, `TaskFailed`, `TaskAbandoned`.
- Create `application/message_bus.py` with a dispatch loop that processes
  events after `uow.commit()`.
- Create `adapters/notifier/webhook.py` as the webhook event handler.
- Update use cases to record events on `Task` aggregates instead of calling
  `do_task_webhook()` directly.
- Update `AbstractUnitOfWork` and `PostgresUnitOfWork` to collect and dispatch
  events after commit.
- Remove all `do_task_webhook()` calls from scheduler.py/use cases.

## Capabilities

### New Capabilities
- `domain-events`: Event dataclasses for task lifecycle transitions.
- `message-bus`: Dispatch loop that processes recorded events after UoW commit.
- `webhook-handler`: Event handler that sends webhook notifications for each
  task lifecycle event.

### Modified Capabilities
<!-- None — purely additive to the application layer. -->

## Impact

- New files: `application/events.py`, `application/message_bus.py`,
  `adapters/notifier/webhook.py`.
- Modified: `application/uow.py` — `AbstractUnitOfWork` gains event collection
  and dispatch support.
- Modified: `adapters/persistence/postgres_uow.py` — `PostgresUnitOfWork`
  dispatches events after commit.
- Modified: use cases — remove webhook calls, record events instead.
- Modified: `scheduler.py` — `do_task_webhook()` method removed.
- No new dependencies. aiohttp already in project.
- `docs/knowledge-graph.xml` updated.
