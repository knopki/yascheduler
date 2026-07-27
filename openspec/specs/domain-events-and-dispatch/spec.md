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

The system SHALL define a `DomainEvent` frozen dataclass base with fields
`task_id: TaskId`, `webhook_url: str | None`,
`webhook_custom_params: dict[str, object]`. An `Event` type alias SHALL be
defined as a union of all domain event subclasses.

#### Scenario: All events carry webhook fields and TaskId
- **WHEN** any event type is constructed
- **THEN** it is a frozen dataclass with `webhook_url`, `webhook_custom_params`, and `event.task_id` is a `TaskId` instance (not a bare `int`)

### Requirement: Concrete event types

The system SHALL provide the following events (each a frozen dataclass subclass
of `DomainEvent`), exposed via `yascheduler.domain`:

- `TaskCreated` — `engine_name: str`
- `TaskAllocated` — `node_id: NodeId`, `engine_name: str`
- `TaskCompleted` — `local_folder: str`
- `TaskFailed` — `reason: str`
- `TaskAbandoned` — `node_id: NodeId`

#### Scenario: TaskCreated carries engine_name

- **WHEN** `TaskCreated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, engine_name="fleur")` is created
- **THEN** `event.engine_name == "fleur"` and `event.task_id == TaskId(42)`

#### Scenario: TaskAllocated carries node_id

- **WHEN** `TaskAllocated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, node_id=NodeId(7), engine_name="fleur")` is created
- **THEN** `event.node_id == NodeId(7)` and `event.engine_name == "fleur"`

#### Scenario: TaskAbandoned carries node_id

- **WHEN** `TaskAbandoned(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, node_id=NodeId(7))` is created
- **THEN** `event.node_id == NodeId(7)`

#### Scenario: TaskFailed carries reason

- **WHEN** `TaskFailed(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, reason="unsupported engine")` is created
- **THEN** `event.reason == "unsupported engine"`

#### Scenario: TaskCompleted carries local_folder and no has_errors

- **WHEN** `TaskCompleted(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, local_folder="/data/out")` is created
- **THEN** `event.local_folder == "/data/out"` and the event has NO `has_errors` field

### Requirement: MessageBus dispatches events to handlers

`MessageBus` SHALL expose `register(event_type, handler)` (multiple handlers per
event type are supported) and `async dispatch(events: Sequence[DomainEvent])`
which dispatches each event to all registered handlers for its type. An event
with no registered handlers is silently ignored.

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

### Requirement: Events collected from aggregates via public events field

The system SHALL collect events from Task aggregates via `collect_events()`.
Events are stored as `events: tuple[DomainEvent, ...]` on the Task aggregate
(preserving `frozen=True`; the field is public with `repr=True`).
`PostgresTaskRepository.save(task)` SHALL track the task for event collection,
enabling `collect_events()` to read `task.events` from all aggregates touched in
the transaction.

#### Scenario: collect_events reads events field directly
- **WHEN** `collect_events()` is called on a UoW with saved tasks carrying events
- **THEN** it returns a flat list of all events from `task.events` across saved tasks, and the tracking is cleared

#### Scenario: save tracks task for event collection
- **WHEN** `uow.tasks.save(task)` is called
- **THEN** the task is persisted and tracked for event collection

### Requirement: Use-case-to-event mapping

The system SHALL emit the matching domain event for each task lifecycle
transition. The mapping is:

| Use case | Transition method | Event emitted | Trigger |
|---|---|---|---|
| `TaskRepository.insert` (via `materialize_task`) | — (not a Task method) | `TaskCreated` | New task insertion |
| `allocate_task` | `task.run(node_id, remote_folder)` | `TaskAllocated` | Task started on a free machine |
| `allocate_task` | `task.reject("unsupported engine")` | `TaskFailed` | Engine not found |
| `consume_task` (success) | `task.complete(local_folder, remote_folder)` | `TaskCompleted` | Successful completion |
| `consume_task` (failure) | `task.fail(error_msg, local_folder, remote_folder)` | `TaskFailed` | Download failure |
| `orchestrator` | `task.abandon(node_id)` | `TaskAbandoned` (only when `node_id is not None`) | Node disappeared |

The `engine_name` value for `TaskAllocated` is sourced from `task.engine`
inside `run`. The `reason` value for `TaskFailed` is sourced from the `reason`
param of `reject` or `fail`. The `node_id` value for `TaskAbandoned` is
sourced from the `node_id` param of `abandon`.

#### Scenario: submit_task records TaskCreated via materialize_task

- **WHEN** a task is submitted via `submit_task`
- **THEN** `uow.tasks.insert(new_task)` returns a Task with `TaskCreated` already in `events` (attached by `materialize_task` inside `insert`); `submit_task` saves and commits

#### Scenario: allocate_task records TaskAllocated via run

- **WHEN** `allocate_task` starts a task on a `Node` with `node_id=NodeId(7)`
- **THEN** `task.run(node_id=NodeId(7), remote_folder=...)` is called; the returned Task carries a `TaskAllocated(node_id=NodeId(7), engine_name=task.engine)` event in `events`

#### Scenario: consume_task records TaskCompleted via complete

- **WHEN** `consume_task` finalises on full download success
- **THEN** `task.complete(local_folder=str(store_folder), remote_folder=...)` is called; the returned Task carries a `TaskCompleted(local_folder=...)` event in `events`

#### Scenario: orchestrator records TaskAbandoned via abandon

- **WHEN** `orchestrator` detects the machine is gone (and `node_id is not None`)
- **THEN** `task.abandon(node_id)` is called; the returned Task carries a `TaskAbandoned(node_id=node_id)` event in `events`. When `node_id is None` (double-abandon edge), `task.abandon(None)` is called and no `TaskAbandoned` event is emitted.

### Requirement: Webhook handler — the registered side-effect handler

`webhook_handler` SHALL be an async function that processes `TaskCreated`, `TaskAllocated`, `TaskCompleted`, `TaskFailed`, and `TaskAbandoned` events by sending webhook notifications. The HTTP POST body SHALL be the wire shape `{"task_id": int, "status": int, "custom_params": ...}`, where `task_id` is the bare `int` (the `TaskId.value`, not the `TaskId` dataclass) and `status` is the matching `TaskStatus` value for the event type.

When `webhook_url` is `None`, the event SHALL be skipped (no HTTP request). Webhook HTTP failures SHALL be logged and the exception suppressed so they never propagate back into the use-case layer. Delivery SHALL use exponential-backoff retry (`max_time=60`) with a semaphore for rate limiting.

#### Scenario: TaskCreated sends TO_DO webhook
- **WHEN** `webhook_handler(TaskCreated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, engine_name="fleur"), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 0, "custom_params": {}}` (status=0 is TO_DO; `task_id` is the bare int `.value`)

#### Scenario: TaskCompleted sends DONE webhook
- **WHEN** `webhook_handler(TaskCompleted(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, local_folder="/data/..."), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 2, "custom_params": {}}`

#### Scenario: WebhookPayload task_id is the bare int
- **WHEN** `webhook_handler` builds the payload from an event with `task_id=TaskId(42)`
- **THEN** the POST body has `"task_id": 42` (a bare `int`), NOT `{"task_id": {"value": 42}, ...}`

#### Scenario: No webhook URL — event skipped
- **WHEN** `webhook_handler` is called with an event whose `webhook_url is None`
- **THEN** no HTTP request is made

#### Scenario: Webhook failure is logged, not raised
- **WHEN** the webhook HTTP request fails
- **THEN** the error is logged; the exception is NOT propagated back into the use-case layer

#### Scenario: Retry on transient failure
- **WHEN** the webhook endpoint returns 503
- **THEN** the request is retried with exponential backoff up to `max_time=60` seconds
