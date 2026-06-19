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

- Create `domain/events.py` with event dataclasses: `TaskCreated`,
  `TaskAllocated`, `TaskCompleted`, `TaskFailed`, `TaskAbandoned`.
- Create `application/message_bus.py` with a dispatch loop that processes
  events after `uow.commit()`.
- Create `adapters/notifier/webhook.py` as the webhook event handler.
- Update use cases to record events on `Task` aggregates instead of calling
  `_do_task_webhook()` directly. `submit_task` currently has no webhook calls —
  this change adds `TaskCreated` event recording to it (behavioural change:
  webhook will now fire on task creation where it didn't before).
- Update `AbstractUnitOfWork` and `PostgresUnitOfWork` to collect and dispatch
  events after commit.
- Remove `_do_task_webhook()` method from `application/orchestrator.py`.
- Remove `do_task_webhook` parameter from `allocate_task()` and `consume_task()`
  signatures and all call-sites (including `_validate_engine` helper in
  `allocate_task.py` which calls `do_task_webhook` on engine validation failure).
- Task aggregate gains `_events: tuple[DomainEvent, ...]` field (immutable).
  `record_event()` returns a new Task via `replace()` with appended event.
  `pull_events()` returns a new Task with empty tuple plus the collected events.
  Task remains `frozen=True`.

## Capabilities

### New Capabilities
- `domain-events`: Event dataclasses with typed fields for task lifecycle transitions.
  `DomainEvent` base carries `webhook_url: str | None` and `webhook_custom_params: dict[str, object]`
  so the webhook handler has all data it needs without querying a repository.
- `message-bus`: `MessageBus` class that dispatches recorded events after UoW commit.
- `webhook-handler`: Event handler that sends webhook notifications for each
  task lifecycle event.

### Modified Capabilities
- `abstract-uow`: `AbstractUnitOfWork` Protocol gains `collect_events()` and
  `publish_events()` methods.
- `postgres-uow`: `PostgresUnitOfWork` implements event collection from saved
  aggregates and dispatch via `MessageBus` after commit.
- `domain-entities`: Task aggregate gains `_events: tuple[DomainEvent, ...]`
  field (default empty). `record_event(event)` returns a new Task with event
  appended via `dataclasses.replace()` (preserves `frozen=True`). `pull_events()`
  returns `(new_task_with_empty_events, collected_events_tuple)`. Event recording
  uses `task.context.webhook_url` and `task.context.webhook_custom_params` for
  the `DomainEvent` base fields.
- `use-cases`: Use cases replace inline `_do_task_webhook()` calls with
  `task = task.record_event(...)`. `submit_task` gains `TaskCreated` event
  recording (currently has no webhook calls — behavioural change: webhook fires
  on creation where it didn't before). `_validate_engine` in `allocate_task.py`
  records `TaskFailed(reason="unsupported engine")` instead of calling
  `do_task_webhook` — no separate `TaskRejected` event type; rejection is a
  failure during validation.
- `orchestrator`: `_task_consumer_consumer` records `TaskAbandoned` via
  `task = task.record_event(TaskAbandoned(...))` after `task.fail()` instead of
  calling `_do_task_webhook()` directly. `TaskAbandoned` is recorded at the
  use-case level (not a Task lifecycle method) because the abandon semantics
  belong to the orchestrator, not the aggregate.
- `testing-unit`: New unit tests for events, message bus, webhook handler, and
  updated UoW event dispatch.

## Impact

- New files: `domain/events.py`, `application/message_bus.py`,
  `adapters/notifier/webhook.py`.
- Modified: `domain/model.py` — Task aggregate gains `_events: tuple`,
  `record_event()`, `pull_events()` (immutable, via `replace()`).
- Modified: `application/uow.py` — `AbstractUnitOfWork` gains `collect_events()`
  and `publish_events()` methods on the Protocol.
- Modified: `adapters/persistence/postgres_uow.py` — `PostgresUnitOfWork`
  dispatches events after commit.
- Modified: `application/orchestrator.py` — remove `_do_task_webhook()` method,
  remove `do_task_webhook` parameter from `_allocator_consumer` and
  `_task_consumer_consumer` call-sites; record events via `task.record_event()`
  instead.
- Modified: `application/allocate_task.py` — remove `do_task_webhook` parameter,
  record `TaskAllocated` event via `task.record_event()`; `_validate_engine`
  records `TaskFailed` on unsupported engine instead of calling webhook.
- Modified: `application/consume_task.py` — remove `do_task_webhook` parameter,
  record `TaskCompleted` or `TaskFailed` event via `task.record_event()`.
- Modified: `application/submit_task.py` — record `TaskCreated` event (additive,
  currently no webhook calls exist).
- Modified: `domain/__init__.py` — export event types from `domain.events`.
- No new dependencies. aiohttp already in project.
- `docs/knowledge-graph.xml` updated.

## Non-Goals

- No event sourcing or CQRS.
- No external message broker (Kafka, Redis) — in-process dispatch only.
- No events for node lifecycle (Phase 4 will add `NodeProvisioned` if needed).
