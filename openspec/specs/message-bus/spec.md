## Purpose

Defines the in-process message bus that decouples domain event recording (in aggregates and use cases) from side-effect handlers (webhook delivery). Events are recorded on the Task aggregate via an immutable tuple, collected by the Unit of Work after a successful database commit, and dispatched to registered handlers.

## Requirements

### Requirement: MessageBus class dispatches events to handlers

The system SHALL provide a `MessageBus` class with a `dispatch(events:
Sequence[DomainEvent])` async method that dispatches each event to all
registered handlers for its type.

#### Scenario: Single event dispatched to matching handler
- **WHEN** `bus.dispatch([TaskCreated(...)])` is called and a handler is registered for `TaskCreated`
- **THEN** the handler is called with the event

#### Scenario: Event with no handlers is silently ignored
- **WHEN** `bus.dispatch([TaskCreated(...)])` is called and no handler is registered for `TaskCreated`
- **THEN** no error is raised

### Requirement: Handler registration via register method

The system SHALL support registering handlers for event types via
`MessageBus.register(event_type, handler)`. Multiple handlers per event type
are supported. Handlers SHALL be async callables accepting a single `DomainEvent`
argument (use `functools.partial` to bind additional dependencies).

#### Scenario: Multiple handlers for one event
- **WHEN** two handlers are registered for `TaskCompleted` via `bus.register(TaskCompleted, handler_a)` and `bus.register(TaskCompleted, handler_b)`
- **THEN** both are called when a `TaskCompleted` event is dispatched

#### Scenario: Handler registered via functools.partial
- **WHEN** DI factory wires the message bus
- **THEN** `bus.register(TaskCreated, functools.partial(webhook_handler, http=session))` registers a handler that receives only the event at dispatch time

### Requirement: Dispatch after commit via UoW

The system SHALL dispatch events in `PostgresUnitOfWork.commit()` after the
database transaction is committed, via `collect_events()` and
`publish_events()` methods defined on the `AbstractUnitOfWork` Protocol.

#### Scenario: Events dispatched after commit
- **WHEN** `uow.commit()` is called and aggregates have recorded events
- **THEN** the database commit completes first, then `collect_events()` pulls events from saved aggregates, and `publish_events()` dispatches them via `MessageBus.dispatch()`

#### Scenario: Events from multiple aggregates dispatched in one commit
- **WHEN** two tasks are saved in one UoW and both have recorded events
- **THEN** `collect_events()` pulls events from both aggregates and all events are dispatched in order

#### Scenario: Rollback discards events
- **WHEN** an exception triggers `uow.rollback()`
- **THEN** saved aggregates are cleared, collected events are discarded without dispatch

### Requirement: Events collected from aggregates via immutable tuple

The system SHALL collect events from Task aggregates via `collect_events()`.
Events are stored as `_events: tuple[DomainEvent, ...]` on the Task aggregate
(preserving `frozen=True`). Use cases call `task.record_event(event)` which
returns a new Task instance with the event appended. `pull_events()` returns
a `(Task, tuple[DomainEvent, ...])` pair — a new Task with empty events and
the collected events tuple.

#### Scenario: Use case records event on aggregate
- **WHEN** a use case does `task = task.record_event(TaskAllocated(...))`
- **THEN** a new Task instance is returned with the event in `_events` and `uow.commit()` dispatches it

#### Scenario: pull_events returns clean task and events
- **WHEN** `pull_events()` is called on a Task with recorded events
- **THEN** it returns `(new_task_with_empty_events, collected_events_tuple)` without mutating the original

#### Scenario: pull_events on Task with no events
- **WHEN** `pull_events()` is called on a Task with `_events=()` (default)
- **THEN** it returns `(new_task_with_empty_events, ())` — empty events tuple, no dispatch occurs

### Requirement: Task repository tracks saved aggregates

`PostgresTaskRepository.save(task)` SHALL append the task to a `_saved_tasks`
list provided by the UoW, enabling `collect_events()` to pull events from all
aggregates touched in the transaction.

#### Scenario: save() tracks task for event collection
- **WHEN** `uow.tasks.save(task)` is called
- **THEN** the task is persisted to DB and appended to `_saved_tasks`

### Requirement: MessageBus importable from application

The system SHALL expose the `MessageBus` class from
`yascheduler.application.message_bus`.

#### Scenario: Import message bus
- **WHEN** `from yascheduler.application.message_bus import MessageBus` is executed
- **THEN** the class is available

### Requirement: Use-case-to-event mapping

The system SHALL record specific event types in each use case as follows:

| Use case | Event | Trigger |
|---|---|---|
| `submit_task` | `TaskCreated` | Always on new task submission |
| `allocate_task._allocate_free_machine` | `TaskAllocated` | After task allocated to a node |
| `allocate_task._validate_engine` | `TaskFailed(reason="unsupported engine")` | When engine not found |
| `consume_task` | `TaskCompleted` | On successful task completion |
| `consume_task` | `TaskFailed` | On task failure |
| `orchestrator._task_consumer_consumer` | `TaskAbandoned` | After `task.fail("node is gone")` when node disappeared |

All events populate `webhook_url` and `webhook_custom_params` from `task.context`.

#### Scenario: submit_task records TaskCreated
- **WHEN** a task is submitted via `submit_task`
- **THEN** `task = task.record_event(TaskCreated(...))` is called with `engine_name=task.context.engine`, `webhook_url=task.context.webhook_url`, `webhook_custom_params=task.context.webhook_custom_params`

#### Scenario: allocate_task records TaskAllocated on successful allocation
- **WHEN** a task is allocated to a free machine in `_allocate_free_machine`
- **THEN** `task = task.record_event(TaskAllocated(...))` is called with `node_ip`, `engine_name`, `webhook_url`, `webhook_custom_params`

#### Scenario: _validate_engine records TaskFailed on unsupported engine
- **WHEN** `_validate_engine` finds no matching engine
- **THEN** `task = task.record_event(TaskFailed(task_id=..., webhook_url=..., webhook_custom_params=..., reason="unsupported engine"))` is called. No separate `TaskRejected` event type SHALL exist — rejection during validation is a failure.

#### Scenario: consume_task records TaskCompleted on success
- **WHEN** a task completes successfully in `consume_task`
- **THEN** `task = task.record_event(TaskCompleted(...))` is called with `local_folder`, `has_errors=False`, `webhook_url`, `webhook_custom_params`

#### Scenario: consume_task records TaskFailed on failure
- **WHEN** a task fails in `consume_task`
- **THEN** `task = task.record_event(TaskFailed(...))` is called with `reason`, `webhook_url`, `webhook_custom_params`

#### Scenario: orchestrator records TaskAbandoned when node disappears
- **WHEN** `_task_consumer_consumer` detects the machine is gone and calls `task.fail("node is gone")`
- **THEN** `task = task.record_event(TaskAbandoned(task_id=..., webhook_url=..., webhook_custom_params=..., node_ip=...))` is called

### Requirement: Use case and orchestrator cleanup

The system SHALL remove all direct webhook calls from use cases and orchestrator.

#### Scenario: do_task_webhook parameter removed from use cases
- **WHEN** `allocate_task()` and `consume_task()` are called
- **THEN** they accept no `do_task_webhook` parameter; event recording replaces webhook calls

#### Scenario: _do_task_webhook removed from orchestrator
- **WHEN** `Orchestrator` is initialized
- **THEN** no `_do_task_webhook()` method exists; no `do_task_webhook` parameter is passed to `_allocator_consumer` or `_task_consumer_consumer`

#### Scenario: submit_task gains TaskCreated event recording
- **WHEN** `submit_task` creates a new task
- **THEN** a `TaskCreated` event is recorded (additive behavioural change: webhook now fires on task creation where it didn't before)
