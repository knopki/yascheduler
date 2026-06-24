## ADDED Requirements

### Requirement: Task aggregate event factory from context

The system SHALL provide a `Task.with_event(event_type, **fields) -> Task`
method on the `Task` aggregate that constructs an event of the given type
with `task_id`, `webhook_url`, and `webhook_custom_params` populated from
`self.context`, plus the caller-supplied subclass-specific fields, and appends
it to the event tuple via the existing `record_event` primitive. The method
SHALL be the preferred event-recording form in use cases; `record_event(event)`
remains available as the low-level primitive for pre-constructed events.

Five `@overload` declarations — one per concrete event subclass — SHALL make
the subclass-specific fields keyword-only (via `*`) and type-checked at call
sites: `TaskCreated` (`engine_name`), `TaskAllocated` (`node_ip`,
`engine_name`), `TaskCompleted` (`local_folder`, `has_errors`), `TaskFailed`
(`reason`), `TaskAbandoned` (`node_ip`).

If a caller passes `task_id`, `webhook_url`, or `webhook_custom_params` in
`**fields`, the method SHALL silently drop them and use the values from
`self.context` (collision guard; typed call sites get a mypy error via the
overload signatures).

#### Scenario: with_event populates base fields from context
- **WHEN** `task.with_event(TaskAllocated, node_ip="10.0.0.1", engine_name="fleur")` is called on a Task with `context.webhook_url="https://hook"` and `context.webhook_custom_params={"k": "v"}`
- **THEN** a new Task is returned with a `TaskAllocated` event in `_events` whose `task_id`, `webhook_url`, and `webhook_custom_params` come from the task and its context, and `node_ip="10.0.0.1"`, `engine_name="fleur"`

#### Scenario: with_event is keyword-only for subclass fields
- **WHEN** `task.with_event(TaskAllocated, "10.0.0.1", "fleur")` is called positionally
- **THEN** a `TypeError` is raised at the call site (subclass-specific fields are keyword-only via `*`)

#### Scenario: with_event silently drops base-field collisions
- **WHEN** `task.with_event(TaskCreated, engine_name="fleur", webhook_url="https://other")` is called on a Task with `context.webhook_url="https://hook"`
- **THEN** the recorded `TaskCreated` event has `webhook_url="https://hook"` (the caller-supplied `webhook_url` is silently dropped in favor of the context value)

#### Scenario: with_event delegates to record_event
- **WHEN** `task.with_event(TaskCompleted, local_folder="/out", has_errors=False)` is called on a Task with no prior events
- **THEN** `pull_events()` on the returned Task yields a single-element tuple containing the `TaskCompleted` event, and the returned Task has `_events=()`

#### Scenario: with_event reads preserved webhook fields after fail
- **WHEN** `task = task.fail("node is gone")` is followed by `task = task.with_event(TaskAbandoned, node_ip=ip)` on a Task whose original `context.webhook_url` was set
- **THEN** the recorded `TaskAbandoned` event carries the original `webhook_url` and `webhook_custom_params` (fail preserves them in context)

#### Scenario: record_event remains the low-level primitive
- **WHEN** a caller constructs an event directly and calls `task.record_event(event)`
- **THEN** the event is appended to `_events` as before; `with_event` and `record_event` coexist

## MODIFIED Requirements

### Requirement: Use-case-to-event mapping

The system SHALL record specific event types in each use case via
`task.with_event(EventType, **subclass_specific_fields)`, which populates
`task_id`, `webhook_url`, and `webhook_custom_params` from `task.context`:

| Use case | Event | `with_event` call | Trigger |
|---|---|---|---|
| `submit_task` | `TaskCreated` | `task.with_event(TaskCreated, engine_name=task.context.engine)` | Always on new task submission |
| `allocate_task._try_start_on_machine` | `TaskAllocated` | `task.with_event(TaskAllocated, node_ip=machine.ip, engine_name=task.context.engine)` | After task allocated to a node |
| `allocate_task._validate_engine` | `TaskFailed` | `task.with_event(TaskFailed, reason="unsupported engine")` | When engine not found |
| `consume_task._record_finalization_event` | `TaskCompleted` | `task.with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)` | On successful task completion |
| `consume_task._record_finalization_event` | `TaskFailed` | `task.with_event(TaskFailed, reason=error_msg)` | On task failure |
| `orchestrator._task_consumer_consumer` | `TaskAbandoned` | `task.with_event(TaskAbandoned, node_ip=ip)` | After `task.fail("node is gone")` when node disappeared |

`record_event(event)` remains available as the low-level primitive for
pre-constructed events; `with_event` is the preferred form in use cases.

#### Scenario: submit_task records TaskCreated
- **WHEN** a task is submitted via `submit_task`
- **THEN** `task = task.with_event(TaskCreated, engine_name=task.context.engine)` is called; the recorded event carries `task_id`, `webhook_url`, and `webhook_custom_params` from `task.context`

#### Scenario: allocate_task records TaskAllocated on successful allocation
- **WHEN** a task is allocated to a free machine in `_try_start_on_machine`
- **THEN** `task = task.with_event(TaskAllocated, node_ip=machine.ip, engine_name=task.context.engine)` is called; the recorded event carries `task_id`, `webhook_url`, and `webhook_custom_params` from `task.context`

#### Scenario: _validate_engine records TaskFailed on unsupported engine
- **WHEN** `_validate_engine` finds no matching engine
- **THEN** `task = task.with_event(TaskFailed, reason="unsupported engine")` is called. No separate `TaskRejected` event type SHALL exist — rejection during validation is a failure.

#### Scenario: consume_task records TaskCompleted on success
- **WHEN** a task completes successfully in `consume_task._record_finalization_event`
- **THEN** `task = task.with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)` is called; the recorded event carries `task_id`, `webhook_url`, and `webhook_custom_params` from `task.context`

#### Scenario: consume_task records TaskFailed on failure
- **WHEN** a task fails in `consume_task._record_finalization_event`
- **THEN** `task = task.with_event(TaskFailed, reason=error_msg)` is called; the recorded event carries `task_id`, `webhook_url`, and `webhook_custom_params` from `task.context`

#### Scenario: orchestrator records TaskAbandoned when node disappears
- **WHEN** `_task_consumer_consumer` detects the machine is gone and calls `task.fail("node is gone")`
- **THEN** `task = task.with_event(TaskAbandoned, node_ip=ip)` is called; the recorded event carries `task_id`, `webhook_url`, and `webhook_custom_params` from `task.context` (preserved through `fail()`)