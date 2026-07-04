## MODIFIED Requirements

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