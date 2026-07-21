## MODIFIED Requirements

### Requirement: DomainEvent base type with webhook fields

The system SHALL define a `DomainEvent` frozen dataclass base in
`yascheduler.domain.events` with fields `task_id: TaskId`, `webhook_url: str |
None`, `webhook_custom_params: dict[str, object]`. An `Event` type alias SHALL be
defined as a union of all domain event subclasses.

`task_id` is a `TaskId` (the Task-side analog of `NodeId`), not a bare `int`.
Events are constructed only inside `Task` transition methods (`run`, `reject`,
`complete`, `fail`, `abandon`) and inside `materialize_task` (for `TaskCreated`);
each constructs the event with `task_id=self.task_id` (already a `TaskId` — no
`.value` extraction at construction). At the webhook boundary,
`infra/notifier/webhook.py` extracts `.value`.

The prior `Task.with_event` factory and `Task.record_event` primitive are
REMOVED. Events are no longer constructed at use-case call sites; the transition
methods own event construction.

#### Scenario: All events carry webhook fields and TaskId
- **WHEN** any event type is constructed inside a `Task` transition method or `materialize_task`
- **THEN** it is a frozen dataclass with `webhook_url`, `webhook_custom_params`, and `event.task_id` is a `TaskId` instance (not a bare `int`)

### Requirement: Concrete event types

The system SHALL provide the following events (each a frozen dataclass subclass
of `DomainEvent`), importable from `yascheduler.domain.events`:

- `TaskCreated` — `engine_name: str`
- `TaskAllocated` — `node_id: NodeId`, `engine_name: str`
- `TaskCompleted` — `local_folder: str`
- `TaskFailed` — `reason: str`
- `TaskAbandoned` — `node_id: NodeId`

`TaskAllocated` and `TaskAbandoned` carry `node_id: NodeId` (was
`node_ip: str`). `TaskAbandoned` is emitted by `Task.abandon(node_id)` only
when `node_id is not None`; the `node_id` field type is `NodeId` (not
`NodeId | None`) because the event is only constructed when a node exists.

`TaskCompleted` no longer carries `has_errors` (the field was unused; every
`complete` path was a success, and errors go through `fail` → `TaskFailed`).
The webhook wire format is unaffected because `webhook_handler` builds
`WebhookPayload(task_id, status, custom_params)` and does not read
`has_errors`.

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

#### Scenario: TaskCompleted carries local_folder and no has_errors

- **WHEN** `TaskCompleted(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, local_folder="/data/out")` is created
- **THEN** `event.local_folder == "/data/out"` and the event has NO `has_errors` field (the field is removed)

### Requirement: Events collected from aggregates via public events field

The system SHALL collect events from Task aggregates via `collect_events()`.
Events are stored as `events: tuple[DomainEvent, ...]` on the Task aggregate
(preserving `frozen=True`; the field is public with `repr=True`). Use cases
call `Task` transition methods (`run`, `reject`, `complete`, `fail`,
`abandon`) which each append the matching event to `events` inline via
`replace`. `PostgresTaskRepository.save(task)` SHALL append the task to a
`_saved_tasks` list provided by the UoW, enabling `collect_events()` to read
`task.events` from all aggregates touched in the transaction.

`collect_events()` SHALL read `task.events` directly and clear `_saved_tasks`;
it SHALL NOT call a `pull_events()` method (no such method exists) and SHALL
NOT re-append clean tasks to `_saved_tasks` (the prior clean-task re-append
was dead code — `publish_events` cleared the list immediately after).

#### Scenario: collect_events reads events field directly
- **WHEN** `collect_events()` is called on a UoW with saved tasks carrying events
- **THEN** it returns a flat list of all events from `task.events` across saved tasks, and `_saved_tasks` is cleared

#### Scenario: save tracks task for event collection
- **WHEN** `uow.tasks.save(task)` is called
- **THEN** the task is persisted and appended to `_saved_tasks`

### Requirement: Use-case-to-event mapping

Use cases SHALL trigger event emission by calling `Task` transition methods,
which construct and append the matching event inline. No use case constructs
`DomainEvent` subclasses directly or calls `record_event`/`with_event` (those
methods are removed).

| Use case | Transition method | Event emitted | Trigger |
|---|---|---|---|
| `TaskRepository.insert` (via `materialize_task`) | — (not a Task method) | `TaskCreated` | New task insertion |
| `allocate_task._try_start_on_machine` | `task.run(node_id, remote_folder)` | `TaskAllocated` | Task started on a free machine |
| `allocate_task._validate_engine` | `task.reject("unsupported engine")` | `TaskFailed` | Engine not found |
| `consume_task._decide_finalisation` (success) | `task.complete(local_folder, remote_folder)` | `TaskCompleted` | Successful completion |
| `consume_task._decide_finalisation` (failure) | `task.fail(error_msg, local_folder, remote_folder)` | `TaskFailed` | Download failure |
| `orchestrator._task_consumer_consumer` | `task.abandon(node_id)` | `TaskAbandoned` (only when `node_id is not None`) | Node disappeared |

The `engine_name` value for `TaskAllocated` is sourced from `task.engine`
inside `run`. The `reason` value for `TaskFailed` is sourced from the `reason`
param of `reject` or `fail` (no duplication — the transition owns the payload).
The `node_id` value for `TaskAbandoned` is sourced from the `node_id` param of
`abandon`.

#### Scenario: submit_task records TaskCreated via materialize_task

- **WHEN** a task is submitted via `submit_task`
- **THEN** `uow.tasks.insert(new_task)` returns a Task with `TaskCreated` already in `events` (attached by `materialize_task` inside `insert`); `submit_task` saves and commits

#### Scenario: allocate_task records TaskAllocated via run

- **WHEN** `_try_start_on_machine` starts a task on a `Node` with `node_id=NodeId(7)`
- **THEN** `task.run(node_id=NodeId(7), remote_folder=...)` is called; the returned Task carries a `TaskAllocated(node_id=NodeId(7), engine_name=task.engine)` event in `events`

#### Scenario: consume_task records TaskCompleted via complete

- **WHEN** `_decide_finalisation` finalises on full download success
- **THEN** `task.complete(local_folder=str(store_folder), remote_folder=...)` is called; the returned Task carries a `TaskCompleted(local_folder=...)` event in `events`

#### Scenario: orchestrator records TaskAbandoned via abandon

- **WHEN** `_task_consumer_consumer` detects the machine is gone (and `node_id is not None`)
- **THEN** `task.abandon(node_id)` is called; the returned Task carries a `TaskAbandoned(node_id=node_id)` event in `events`. When `node_id is None` (double-abandon edge), `task.abandon(None)` is called and no `TaskAbandoned` event is emitted.

## REMOVED Requirements

### Requirement: Task.with_event event factory
**Reason**: Events are now constructed and appended inline by `Task` transition methods (`run`, `reject`, `complete`, `fail`, `abandon`) and by `materialize_task` (for `TaskCreated`). The `with_event` factory and the `record_event` primitive are no longer needed — every emission site is a transition. Keeping `with_event` would preserve a primitive that bypasses the transition encapsulation.
**Migration**: Replace `task.with_event(EventType, **fields)` calls with the matching transition method. `task.with_event(TaskAllocated, node_id=..., engine_name=...)` → `task.run(node_id, remote_folder)`. `task.with_event(TaskFailed, reason=...)` after `reject`/`fail` → call `reject(reason)` or `fail(reason, ...)` alone. `task.with_event(TaskCreated, ...)` → handled by `materialize_task` inside `insert`. `task.with_event(TaskAbandoned, node_id=...)` after `fail` → `task.abandon(node_id)`. `record_event(event)` callers → use the transition methods.