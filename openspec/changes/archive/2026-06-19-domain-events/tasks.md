## 1. Domain Events

- [x] 1.1 Create `domain/events.py` with `DomainEvent` base frozen dataclass (`task_id: int`, `webhook_url: str | None`, `webhook_custom_params: dict[str, object]`)
- [x] 1.2 Implement `TaskCreated(DomainEvent)` with field: `engine_name: str`
- [x] 1.3 Implement `TaskAllocated(DomainEvent)` with fields: `node_ip: str`, `engine_name: str`
- [x] 1.4 Implement `TaskCompleted(DomainEvent)` with fields: `local_folder: str`, `has_errors: bool`
- [x] 1.5 Implement `TaskFailed(DomainEvent)` with field: `reason: str`
- [x] 1.6 Implement `TaskAbandoned(DomainEvent)` with field: `node_ip: str`
- [x] 1.7 Define `Event` type alias as union of all event types
- [x] 1.8 Update `domain/__init__.py` to export all event types and `Event` alias from `domain.events`
- [x] 1.9 Add GRACE-lite markup to `domain/events.py`
- [x] 1.10 Write unit tests in `tests/unit/test_domain_events.py`: construction with all fields, field access, immutability, frozen enforcement, `Event` union type

## 2. Task Aggregate Event Support

- [x] 2.1 Add `_events: tuple[DomainEvent, ...] = ()` field to `Task` dataclass in `domain/model.py` (preserves `frozen=True`)
- [x] 2.2 Implement `record_event(self, event: DomainEvent) -> Task` — returns `replace(self, _events=self._events + (event,))`
- [x] 2.3 Implement `pull_events(self) -> tuple[Task, tuple[DomainEvent, ...]]` — returns `(replace(self, _events=()), self._events)`
- [x] 2.4 Update GRACE-lite markup on modified Task methods
- [x] 2.5 Write unit tests in `tests/unit/test_domain_events.py`: `record_event` returns new Task with event appended, `pull_events` returns clean task and collected events, `pull_events` on empty tuple returns `(new_task, ())`, original Task unchanged after `record_event`

## 3. Message Bus

- [x] 3.1 Create `application/message_bus.py`
- [x] 3.2 Implement `MessageBus` class with `_handlers: dict[type, list[Callable]]` registry
- [x] 3.3 Implement `register(event_type, handler)` method
- [x] 3.4 Implement `async dispatch(events: Sequence[DomainEvent])` method — iterates events, calls all registered handlers for each event's type
- [x] 3.5 Add GRACE-lite markup
- [x] 3.6 Write unit tests in `tests/unit/test_message_bus.py`: dispatch to single handler, event with no handlers silently ignored, multiple handlers per event type, `functools.partial`-wrapped handler receives only event at dispatch

## 4. UoW Event Support

- [x] 4.1 Add `collect_events() -> list[DomainEvent]` and `publish_events() -> None` to `AbstractUnitOfWork` Protocol in `application/uow.py`
- [x] 4.2 Update `PostgresUnitOfWork.__init__` in `adapters/persistence/postgres_uow.py` to accept `bus: MessageBus` and init `_saved_tasks: list[Task] = []`
- [x] 4.3 Update `PostgresTaskRepository.__init__` in `adapters/persistence/postgres.py` to accept `saved_tasks: list[Task]` from UoW; `save()` appends task to `saved_tasks`
- [x] 4.4 Implement `collect_events()` — iterate `_saved_tasks`, call `task.pull_events()` on each, collect `(clean_task, events)` pairs, replace `_saved_tasks` with clean tasks, return flat event list
- [x] 4.5 Implement `publish_events()` — collect events, dispatch via `bus.dispatch()`, clear `_saved_tasks`
- [x] 4.6 Update `commit()` — call `publish_events()` after DB commit
- [x] 4.7 Update `rollback()` — clear `_saved_tasks` (discard events)
- [x] 4.8 Update DI wiring (`di.py`) — create `MessageBus`, create `aiohttp.ClientSession` (owned by DI, closed on shutdown), register handlers via `functools.partial(webhook_handler, http=session)` for each event type (see Section 5 for handler signature), pass `bus` to `PostgresUnitOfWork`
- [x] 4.9 Update test mocks to implement `collect_events()` and `publish_events()`
- [x] 4.10 Write unit tests in `tests/unit/test_message_bus.py`: commit dispatches events, rollback clears without dispatch, events collected from multiple aggregates, `pull_events` integration

## 5. Webhook Handler

- [x] 5.1 Create `adapters/notifier/__init__.py`
- [x] 5.2 Create `adapters/notifier/webhook.py` with `async webhook_handler(event: DomainEvent, http: aiohttp.ClientSession)`
- [x] 5.3 Implement early-return when `event.webhook_url is None`
- [x] 5.4 Map each event type to correct TaskStatus: TaskCreated→TO_DO (0), TaskAllocated→RUNNING (1), TaskCompleted→DONE (2), TaskFailed→DONE (2) error, TaskAbandoned→DONE (2) error
- [x] 5.5 Use `event.webhook_url` and `event.webhook_custom_params` from `DomainEvent` base for payload construction
- [x] 5.6 Preserve retry logic (fibonacci backoff via `backoff.fibo`, `max_time=60`) and rate limiting (semaphore)
- [x] 5.7 Handle webhook HTTP errors — log and suppress, never propagate
- [x] 5.8 Add GRACE-lite markup
- [x] 5.9 Write unit tests in `tests/unit/test_webhook_handler.py`: each event type→correct HTTP call with status, retry on 503, skip on `webhook_url=None`, error logged not raised, `webhook_custom_params` in payload

## 6. Use Case Changes

- [x] 6.1 Update `application/submit_task.py` — record `TaskCreated(task_id=task.task_id, webhook_url=task.context.webhook_url, webhook_custom_params=task.context.webhook_custom_params, engine_name=task.context.engine)` via `task = task.record_event(...)`. Additive behavioural change: webhook now fires on creation.
- [x] 6.2 Update `application/allocate_task.py` — remove `do_task_webhook` parameter from `allocate_task()` and `_validate_engine()`
- [x] 6.3 In `_allocate_free_machine`: record `TaskAllocated(task_id=task.task_id, webhook_url=task.context.webhook_url, webhook_custom_params=task.context.webhook_custom_params, node_ip=ip, engine_name=task.context.engine)` via `task = task.record_event(...)` instead of calling webhook
- [x] 6.4 In `_validate_engine`: record `TaskFailed(task_id=task.task_id, webhook_url=task.context.webhook_url, webhook_custom_params=task.context.webhook_custom_params, reason="unsupported engine")` instead of calling webhook. No `TaskRejected` event type.
- [x] 6.5 Update `application/consume_task.py` — remove `do_task_webhook` parameter from `consume_task()`
- [x] 6.6 In `consume_task`: record `TaskCompleted(...)` or `TaskFailed(...)` via `task = task.record_event(...)` with all base fields from `task.context`, instead of calling webhook
- [x] 6.7 Update GRACE-lite markup on modified use cases
- [x] 6.8 Write characterization tests in `tests/unit/test_application_use_cases.py`: verify webhooks fire via event dispatch (not direct calls), `submit_task` now fires TaskCreated event, `_validate_engine` fires TaskFailed (not separate rejection)

## 7. Orchestrator Cleanup

- [x] 7.1 Remove `_do_task_webhook()` method from `application/orchestrator.py`
- [x] 7.2 Remove `do_task_webhook` parameter from `_allocator_consumer` and `_task_consumer_consumer` call-sites
- [x] 7.3 In `_task_consumer_consumer`: after `task.fail("node is gone")`, record `TaskAbandoned(task_id=task.task_id, webhook_url=task.context.webhook_url, webhook_custom_params=task.context.webhook_custom_params, node_ip=ip)` via `task = task.record_event(...)` instead of calling `_do_task_webhook`
- [x] 7.4 Remove unused `from yascheduler.webhook import WebhookPayload` import from `application/orchestrator.py` (after removing `_do_task_webhook`). `WebhookPayload` class in `yascheduler/webhook.py` stays — it may be part of the public interface (re-exported from `scheduler.py`).
- [x] 7.5 Remove `webhook_sem` and `_http` session management from `application/orchestrator.py` (retry logic and semaphore moved to webhook handler; session created and owned by DI)
- [x] 7.6 Update GRACE-lite markup on modified orchestrator methods
- [x] 7.7 Write/update unit tests: `_task_consumer_consumer` records TaskAbandoned event, no `_do_task_webhook` calls remain

## 8. Verification

- [x] 8.1 Run `grace_check.py` — all new and modified files pass
- [x] 8.2 Update `docs/knowledge-graph.xml`: add M-DOMAIN-EVENTS, M-APPLICATION-MESSAGE-BUS, M-NOTIFIER-WEBHOOK; update annotations for M-DOMAIN-MODEL (record_event/pull_events/_events), M-APPLICATION-UOW (collect_events/publish_events), M-PERSISTENCE-UOW (bus dispatch, saved_tasks), M-APPLICATION-ORCHESTRATOR (remove webhook, add TaskAbandoned), M-APPLICATION-ALLOCATE (remove do_task_webhook, add TaskAllocated/TaskFailed), M-APPLICATION-CONSUME (remove do_task_webhook, add TaskCompleted/TaskFailed), M-DI (MessageBus wiring)
- [x] 8.3 Run `openspec validate --all --json`
- [x] 8.4 Run `uv run pytest tests/unit/ -k "event or message_bus or webhook or use_case"` — all tests pass
- [x] 8.5 Run full existing test suite — no regressions
- [x] 8.6 Verify webhook smoke test: submit→allocate→consume produces 3 webhook calls via events
