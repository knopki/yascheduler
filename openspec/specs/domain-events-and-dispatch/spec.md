# Domain Events and Dispatch

## Purpose

The domain event types emitted by the Task aggregate and use cases, the in-process
`MessageBus` that decouples event recording from side-effect handlers, the
`collect_events` / `publish_events` UoW hooks, and the `webhook_handler` adapter —
the registered side-effect handler that translates events into outbound HTTP
webhook calls. Events are immutable value objects carrying webhook delivery
metadata on the base class.

## Requirements

### Requirement: DomainEvent base type with webhook fields

The system SHALL define a `DomainEvent` frozen dataclass base in
`yascheduler.domain.events` with fields `task_id: TaskId`, `webhook_url: str |
None`, `webhook_custom_params: dict[str, object]`. An `Event` type alias SHALL be
defined as a union of all domain event subclasses.

`task_id` is a `TaskId` (the Task-side analog of `NodeId`), not a bare `int`.
Events are constructed only from `Task.with_event`, which passes
`task_id=self.task_id` (already a `TaskId` — no `.value` extraction at
construction). At the webhook boundary, `infra/notifier/webhook.py` extracts
`.value`.

#### Scenario: All events carry webhook fields and TaskId
- **WHEN** any event type is instantiated via `Task.with_event`
- **THEN** it is a frozen dataclass with `webhook_url`, `webhook_custom_params`, and `event.task_id` is a `TaskId` instance (not a bare `int`)

### Requirement: Concrete event types

The system SHALL provide the following events (each a frozen dataclass subclass
of `DomainEvent`), importable from `yascheduler.domain.events`:

- `TaskCreated` — `engine_name: str`
- `TaskAllocated` — `node_id: NodeId`, `engine_name: str`
- `TaskCompleted` — `local_folder: str`, `has_errors: bool`
- `TaskFailed` — `reason: str`
- `TaskAbandoned` — `node_id: NodeId`

`TaskAllocated` and `TaskAbandoned` carry `node_id: NodeId` (was
`node_ip: str`). The field is the node identity, not the transport
address. `node_ip` is removed — it was the last ip-as-identity field in
the event layer. Emission sites pass `task.allocated_node_id` (was
`task.allocated_ip` / `session.ip`).

`webhook_handler` builds `WebhookPayload(task_id=event.task_id.value,
status=<status>.value, custom_params=event.webhook_custom_params)` — it
does NOT read `node_id` (or the prior `node_ip`), so the webhook wire
format is unchanged. No external breakage.

#### Scenario: TaskCreated carries engine_name

- **WHEN** `TaskCreated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, engine_name="fleur")` is created
- **THEN** `event.engine_name == "fleur"` and `event.task_id == TaskId(42)`

#### Scenario: TaskAllocated carries node_id

- **WHEN** `TaskAllocated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, node_id=NodeId(7), engine_name="fleur")` is created
- **THEN** `event.node_id == NodeId(7)` and `event.engine_name == "fleur"` (the field is `node_id: NodeId`, NOT `node_ip: str`)

#### Scenario: TaskAbandoned carries node_id

- **WHEN** `TaskAbandoned(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, node_id=NodeId(7))` is created
- **THEN** `event.node_id == NodeId(7)` (the field is `node_id: NodeId`, NOT `node_ip: str`)

#### Scenario: TaskFailed carries reason

- **WHEN** `TaskFailed(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, reason="unsupported engine")` is created
- **THEN** `event.reason == "unsupported engine"`
### Requirement: MessageBus dispatches events to handlers

`MessageBus` (`yascheduler.application.message_bus`) SHALL expose
`register(event_type, handler)` (multiple handlers per event type; handlers are
async callables accepting a single `DomainEvent`; use `functools.partial` to bind
dependencies) and `async dispatch(events: Sequence[DomainEvent])` which dispatches
each event to all registered handlers for its type. An event with no registered
handlers is silently ignored.

#### Scenario: Multiple handlers for one event
- **WHEN** two handlers are registered for `TaskCompleted`
- **THEN** both are called when a `TaskCompleted` event is dispatched

#### Scenario: Event with no handlers is silently ignored
- **WHEN** `bus.dispatch([TaskCreated(...)])` is called and no handler is registered for `TaskCreated`
- **THEN** no error is raised

### Requirement: Dispatch after commit via UoW

Events SHALL be dispatched in `PostgresUnitOfWork.commit()` after the database
transaction commits, via `collect_events()` / `publish_events()` on the
`AbstractUnitOfWork` Protocol. `collect_events()` pulls events from saved
aggregates; `publish_events()` dispatches them via `MessageBus.dispatch()`. An
exception triggering `rollback()` SHALL discard collected events without
dispatch.

#### Scenario: Events dispatched after commit
- **WHEN** `uow.commit()` is called and aggregates have recorded events
- **THEN** the database commit completes first, then events are collected and dispatched

#### Scenario: Rollback discards events
- **WHEN** an exception triggers `uow.rollback()`
- **THEN** collected events are discarded without dispatch

### Requirement: Events collected from aggregates via immutable tuple

The system SHALL collect events from Task aggregates via `collect_events()`.
Events are stored as `_events: tuple[DomainEvent, ...]` on the Task aggregate
(preserving `frozen=True`). Use cases call `task.record_event(event)` which
returns a new Task instance with the event appended; `pull_events()` returns a
`(Task, tuple[DomainEvent, ...])` pair — a new Task with empty events and the
collected events tuple. `PostgresTaskRepository.save(task)` SHALL append the task
to a `_saved_tasks` list provided by the UoW, enabling `collect_events()` to pull
events from all aggregates touched in the transaction.

#### Scenario: pull_events returns clean task and events
- **WHEN** `pull_events()` is called on a Task with recorded events
- **THEN** it returns `(new_task_with_empty_events, collected_events_tuple)` without mutating the original

#### Scenario: save tracks task for event collection
- **WHEN** `uow.tasks.save(task)` is called
- **THEN** the task is persisted and appended to `_saved_tasks`

### Requirement: Task.with_event event factory

`Task.with_event(event_type, **fields) -> Task` SHALL construct an event of the
given type with `task_id`, `webhook_url`, `webhook_custom_params` populated from
`self.context`, plus the caller-supplied subclass-specific fields, and append it
via `record_event`. Five `@overload` declarations make subclass-specific fields
keyword-only. If a caller passes `task_id` / `webhook_url` /
`webhook_custom_params` in `**fields`, the method silently drops them in favor of
the context values. `record_event(event)` remains the low-level primitive for
pre-constructed events.

For `TaskAllocated` and `TaskAbandoned`, the `node_id` field SHALL be
supplied by the caller (from `task.allocated_node_id` or
`session.machine.node_id`). The prior `node_ip` field is gone; callers
updated accordingly.

#### Scenario: with_event populates base fields from context

- **WHEN** `task.with_event(TaskAllocated, node_id=NodeId(7), engine_name="fleur")` is called on a Task whose `context.webhook_url` is set
- **THEN** the recorded `TaskAllocated` carries the `webhook_url` from context, plus `node_id` and `engine_name`

#### Scenario: with_event silently drops base-field collisions

- **WHEN** `task.with_event(TaskCreated, engine_name="fleur", webhook_url="https://other")` is called on a Task with a different `context.webhook_url`
- **THEN** the recorded event carries the context `webhook_url` (the caller-supplied value is dropped)
### Requirement: Use-case-to-event mapping

Use cases SHALL record events via `task.with_event(EventType,
**subclass_specific_fields)`, which populates `task_id`, `webhook_url`,
`webhook_custom_params` from `task.context`:

| Use case | Event | `with_event` call | Trigger |
|---|---|---|---|
| `submit_task` | `TaskCreated` | `task.with_event(TaskCreated, engine_name=task.context.engine)` | New task submission |
| `allocate_task._try_start_on_machine` | `TaskAllocated` | `task.with_event(TaskAllocated, node_id=node.node_id, engine_name=task.context.engine)` | After task allocated |
| `allocate_task._validate_engine` | `TaskFailed` | `task.with_event(TaskFailed, reason="unsupported engine")` | Engine not found (no separate `TaskRejected` type) |
| `consume_task._record_finalization_event` | `TaskCompleted` | `task.with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)` | Successful completion |
| `consume_task._record_finalization_event` | `TaskFailed` | `task.with_event(TaskFailed, reason=error_msg)` | Task failure |
| `orchestrator._task_consumer_consumer` | `TaskAbandoned` | `task.with_event(TaskAbandoned, node_id=task.allocated_node_id)` | After `task.fail("node is gone")` |

#### Scenario: submit_task records TaskCreated

- **WHEN** a task is submitted via `submit_task`
- **THEN** `task.with_event(TaskCreated, engine_name=task.context.engine)` is called

#### Scenario: allocate_task records TaskAllocated with node_id

- **WHEN** `_try_start_on_machine` allocates a task to a `Node` with `node_id=NodeId(7)`
- **THEN** `task.with_event(TaskAllocated, node_id=NodeId(7), engine_name=task.context.engine)` is called; the event carries `node_id=NodeId(7)`

#### Scenario: orchestrator records TaskAbandoned with node_id when node disappears

- **WHEN** `_task_consumer_consumer` detects the machine is gone and calls `task.fail("node is gone")`
- **THEN** `task.with_event(TaskAbandoned, node_id=task.allocated_node_id)` is called; the event carries the context webhook fields (preserved through `fail()`)
### Requirement: Webhook handler — the registered side-effect handler

`webhook_handler` (`yascheduler.infra.notifier.webhook`) SHALL be an async
function that processes `TaskCreated`, `TaskAllocated`, `TaskCompleted`,
`TaskFailed`, and `TaskAbandoned` events by sending webhook notifications. It
SHALL build `WebhookPayload(task_id=event.task_id.value, status=<status>.value,
custom_params=event.webhook_custom_params)` and serialize it via
`dataclasses.asdict(payload)` into the HTTP POST body. The `.value` extraction
at the `WebhookPayload` construction site is REQUIRED: `dataclasses.asdict`
recurses into nested dataclasses, so passing `task_id=event.task_id` (a `TaskId`)
would produce `{"task_id": {"value": 42}, ...}` instead of `{"task_id": 42,
...}`. `WebhookPayload.task_id` SHALL be typed `int`.

When `webhook_url` is `None`, the event is skipped (no HTTP request). Webhook
HTTP failures SHALL be logged and the exception suppressed so they never
propagate back into the use-case layer. Delivery SHALL use fibonacci-backoff
retry (`backoff.fibo`, `max_time=60`) with a semaphore for rate limiting.

`WebhookPayload` (`task_id`, `status`, `custom_params`; default `custom_params =
{}`) is the wire shape `{"task_id": int, "status": int, "custom_params": ...}`.

#### Scenario: TaskCreated sends TO_DO webhook
- **WHEN** `webhook_handler(TaskCreated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, engine_name="fleur"), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 0, "custom_params": {}}` (status=0 is TO_DO; `task_id` is the bare int `.value`)

#### Scenario: TaskCompleted sends DONE webhook
- **WHEN** `webhook_handler(TaskCompleted(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, local_folder="/data/...", has_errors=False), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 2, "custom_params": {}}`

#### Scenario: WebhookPayload task_id is the bare int
- **WHEN** `webhook_handler` builds `WebhookPayload` from an event with `task_id=TaskId(42)`
- **THEN** `payload.task_id == 42` (a bare `int`); `dataclasses.asdict(payload)` produces `{"task_id": 42, ...}`, NOT `{"task_id": {"value": 42}, ...}`

#### Scenario: No webhook URL — event skipped
- **WHEN** `webhook_handler` is called with an event whose `webhook_url is None`
- **THEN** no HTTP request is made

#### Scenario: Webhook failure is logged, not raised
- **WHEN** the webhook HTTP request fails
- **THEN** the error is logged; the exception is NOT propagated back into the use-case layer

#### Scenario: Retry on transient failure
- **WHEN** the webhook endpoint returns 503
- **THEN** the request is retried with fibonacci backoff up to `max_time=60` seconds
