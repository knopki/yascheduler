## MODIFIED Requirements

### Requirement: Webhook handler processes all task events

The system SHALL provide a `webhook_handler` async function that processes
`TaskCreated`, `TaskAllocated`, `TaskCompleted`, `TaskFailed`, and
`TaskAbandoned` events by sending webhook notifications. The handler SHALL
access `webhook_url` and `webhook_custom_params` from the `DomainEvent` base
class fields. The `task_id` field on each event is a `TaskId` (see the
`domain-events` capability).

The handler SHALL build a `WebhookPayload(task_id=event.task_id.value,
status=<status>.value, custom_params=event.webhook_custom_params)` and
serialize it via `dataclasses.asdict(payload)` into the HTTP POST body. The
`.value` extraction at the `WebhookPayload` construction site is REQUIRED:
`dataclasses.asdict` recurses into nested dataclasses, so passing
`task_id=event.task_id` (a `TaskId`) would produce a body of
`{"task_id": {"value": 42}, ...}` instead of `{"task_id": 42, ...}` — a silent
wire-shape break. `WebhookPayload.task_id` SHALL be typed `int` (the correct
target type); the `.value` extraction is the domain→transport boundary unwrap.
The wire payload shape `{"task_id": int, "status": int, "custom_params": ...}`
is thus preserved across the `TaskId` introduction.

#### Scenario: TaskCreated sends TO_DO webhook
- **WHEN** `webhook_handler(TaskCreated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, engine_name="fleur"), http)` is called
- **THEN** an HTTP POST is sent to the webhook_url with a body of `{"task_id": 42, "status": 0, "custom_params": {}}` (status=0 is TO_DO; `task_id` is the bare int `.value` of the `TaskId`)

#### Scenario: TaskAllocated sends RUNNING webhook
- **WHEN** `webhook_handler(TaskAllocated(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, node_ip="10.0.0.1", engine_name="fleur"), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 1, "custom_params": {}}` (status=1 is RUNNING)

#### Scenario: TaskCompleted sends DONE webhook
- **WHEN** `webhook_handler(TaskCompleted(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, local_folder="/data/...", has_errors=False), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 2, "custom_params": {}}` (status=2 is DONE)

#### Scenario: TaskFailed sends DONE webhook with error
- **WHEN** `webhook_handler(TaskFailed(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, reason="unsupported engine"), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 2, "custom_params": {}}` (status=2 is DONE — failure is reported as DONE+error)

#### Scenario: TaskAbandoned sends DONE webhook with error
- **WHEN** `webhook_handler(TaskAbandoned(task_id=TaskId(42), webhook_url="https://...", webhook_custom_params={}, node_ip="10.0.0.1"), http)` is called
- **THEN** an HTTP POST is sent with `{"task_id": 42, "status": 2, "custom_params": {}}` (status=2 is DONE — abandonment is reported as DONE+error)

#### Scenario: WebhookPayload task_id is the bare int from TaskId.value
- **WHEN** `webhook_handler` builds `WebhookPayload` from an event with `task_id=TaskId(42)`
- **THEN** `payload.task_id == 42` (a bare `int`, the `.value` of the `TaskId`); `dataclasses.asdict(payload)` produces `{"task_id": 42, ...}`, NOT `{"task_id": {"value": 42}, ...}`

#### Scenario: Webhook failure is logged, not raised
- **WHEN** the webhook HTTP request fails
- **THEN** the error is logged; the exception is NOT propagated

#### Scenario: No webhook URL — event skipped
- **WHEN** `webhook_handler(TaskCreated(task_id=TaskId(42), webhook_url=None, webhook_custom_params={}, engine_name="fleur"), http)` is called
- **THEN** no HTTP request is made