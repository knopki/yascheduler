## 1. Domain Events

- [ ] 1.1 Create `application/events.py` with `Event` type alias
- [ ] 1.2 Implement `TaskCreated` frozen dataclass
- [ ] 1.3 Implement `TaskAllocated` frozen dataclass
- [ ] 1.4 Implement `TaskCompleted` frozen dataclass
- [ ] 1.5 Implement `TaskFailed` frozen dataclass
- [ ] 1.6 Implement `TaskAbandoned` frozen dataclass
- [ ] 1.7 Add GRACE-lite markup
- [ ] 1.8 Write unit tests: construction, field access, immutability

## 2. Message Bus

- [ ] 2.1 Create `application/message_bus.py`
- [ ] 2.2 Implement `HANDLERS: dict[type, list[Callable]]` registry
- [ ] 2.3 Implement `async def handle(event)` dispatch function
- [ ] 2.4 Add GRACE-lite markup
- [ ] 2.5 Write unit tests: dispatch to handler, no handler, multiple handlers

## 3. UoW Event Support

- [ ] 3.1 Extend `AbstractUnitOfWork` with `events: list[Event]` attribute
- [ ] 3.2 Update `PostgresUnitOfWork.__aenter__` to init `_collected_events = []`
- [ ] 3.3 Update `PostgresUnitOfWork.commit()` — dispatch events after DB commit
- [ ] 3.4 Update `PostgresUnitOfWork.rollback()` — clear events
- [ ] 3.5 Write unit tests: commit dispatches, rollback clears, events collected

## 4. Webhook Handler

- [ ] 4.1 Create `adapters/notifier/__init__.py`
- [ ] 4.2 Create `adapters/notifier/webhook.py` with `webhook_handler`
- [ ] 4.3 Move `do_task_webhook()` logic from scheduler.py
- [ ] 4.4 Map each event type to correct TaskStatus for webhook payload
- [ ] 4.5 Preserve retry logic (backoff) and rate limiting (semaphore)
- [ ] 4.6 Preserve aiohttp ClientSession management
- [ ] 4.7 Add GRACE-lite markup
- [ ] 4.8 Write unit tests: each event type → correct HTTP call, retry, skip on no URL

## 5. Use Case & Scheduler Cleanup

- [ ] 5.1 Update `allocate_task` — record `TaskAllocated` event, remove webhook call
- [ ] 5.2 Update `consume_task` — record `TaskCompleted` or `TaskFailed`, remove webhook
- [ ] 5.3 Update `submit_task` — record `TaskCreated` event, remove optional webhook
- [ ] 5.4 Update orchestrator `task_consumer_consumer` — record `TaskAbandoned`, remove webhook
- [ ] 5.5 Remove `do_task_webhook()` method from scheduler.py
- [ ] 5.6 Remove `WebhookPayload` class from scheduler.py
- [ ] 5.7 Remove `webhook_sem` and `http` session management from scheduler.py
- [ ] 5.8 Write characterization tests: webhooks fire with same data as before

## 6. Verification

- [ ] 6.1 Run `grace_check.py` — all new and modified files pass
- [ ] 6.2 Update `docs/knowledge-graph.xml`
- [ ] 6.3 Run `openspec validate --all --json`
- [ ] 6.4 Run `uv run pytest tests/unit/ -k "event or message_bus or webhook"` — tests pass
- [ ] 6.5 Run full existing test suite — no regressions
- [ ] 6.6 Verify webhook smoke test: submit → allocate → consume produces 3 webhook calls
