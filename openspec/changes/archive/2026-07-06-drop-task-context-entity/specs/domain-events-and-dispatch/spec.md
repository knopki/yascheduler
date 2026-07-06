# Spec Delta: domain-events-and-dispatch

## MODIFIED Requirements

### Requirement: Task.with_event event factory

`Task.with_event(event_type, **fields) -> Task` SHALL construct an event of the
given type with `task_id`, `webhook_url`, `webhook_custom_params` populated from
the task's own typed fields (`self.task_id`, `self.webhook_url`,
`self.webhook_custom_params` — was `self.context.X` before
`drop-task-context-entity`), plus the caller-supplied subclass-specific fields,
and append it via `record_event`. Five `@overload` declarations make
subclass-specific fields keyword-only. If a caller passes `task_id` /
`webhook_url` / `webhook_custom_params` in `**fields`, the method silently drops
them in favor of the task's own values. `record_event(event)` remains the
low-level primitive for pre-constructed events.

For `TaskAllocated` and `TaskAbandoned`, the `node_id` field SHALL be
supplied by the caller (from `task.allocated_node_id` or
`session.machine.node_id`). The prior `node_ip` field is gone; callers
updated accordingly.

No `TaskContext` indirection: the method reads webhook fields directly off
the `Task` instance. The `Task.with_context(...)` mutation helper is removed
per the `domain-entities` delta.

#### Scenario: with_event populates base fields from task typed fields

- **WHEN** `task.with_event(TaskAllocated, node_id=NodeId(7), engine_name="fleur")` is called on a Task whose `webhook_url` field is set
- **THEN** the recorded `TaskAllocated` carries the `webhook_url` from `task.webhook_url` (was `task.context.webhook_url`), plus `node_id` and `engine_name`

#### Scenario: with_event silently drops base-field collisions

- **WHEN** `task.with_event(TaskCreated, engine_name="fleur", webhook_url="https://other")` is called on a Task whose `webhook_url` field is a different value
- **THEN** the recorded event carries the task's own `webhook_url` (the caller-supplied value is dropped)

#### Scenario: with_event reads task.webhook_custom_params not task.context.X
- **WHEN** `task.with_event` is inspected for how it populates the base webhook fields
- **THEN** it reads `self.webhook_url` and `self.webhook_custom_params` (no `self.context` reference); the `TaskContext` indirection is gone

### Requirement: Use-case-to-event mapping

Use cases SHALL record events via `task.with_event(EventType,
**subclass_specific_fields)`, which populates `task_id`, `webhook_url`,
`webhook_custom_params` from the `Task` instance's own typed fields (was
`task.context.X`):

| Use case | Event | `with_event` call | Trigger |
|---|---|---|---|
| `submit_task` | `TaskCreated` | `task.with_event(TaskCreated, engine_name=task.engine)` | New task submission |
| `allocate_task._try_start_on_machine` | `TaskAllocated` | `task.with_event(TaskAllocated, node_id=node.node_id, engine_name=task.engine)` | After task allocated |
| `allocate_task._validate_engine` | `TaskFailed` | `task.with_event(TaskFailed, reason="unsupported engine")` | Engine not found (no separate `TaskRejected` type) |
| `consume_task._decide_finalisation` | `TaskCompleted` | `task.with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)` | Successful completion |
| `consume_task._decide_finalisation` | `TaskFailed` | `task.with_event(TaskFailed, reason=error_msg)` | Task failure |
| `orchestrator._task_consumer_consumer` | `TaskAbandoned` | `task.with_event(TaskAbandoned, node_id=task.allocated_node_id)` | After `task.fail("node is gone")` |

The `engine_name` value is sourced from `task.engine` (was
`task.context.engine`); the webhook base fields are sourced from
`task.webhook_url` / `task.webhook_custom_params` (was `task.context.X`)
inside `with_event`.

#### Scenario: submit_task records TaskCreated

- **WHEN** a task is submitted via `submit_task`
- **THEN** `task.with_event(TaskCreated, engine_name=task.engine)` is called (was `task.context.engine`)

#### Scenario: allocate_task records TaskAllocated with node_id

- **WHEN** `_try_start_on_machine` allocates a task to a `Node` with `node_id=NodeId(7)`
- **THEN** `task.with_event(TaskAllocated, node_id=NodeId(7), engine_name=task.engine)` is called (was `task.context.engine`); the event carries `node_id=NodeId(7)`

#### Scenario: orchestrator records TaskAbandoned with node_id when node disappears

- **WHEN** `_task_consumer_consumer` detects the machine is gone and calls `task.fail("node is gone")`
- **THEN** `task.with_event(TaskAbandoned, node_id=task.allocated_node_id)` is called; the event carries the task's webhook fields (preserved through `fail()`)
