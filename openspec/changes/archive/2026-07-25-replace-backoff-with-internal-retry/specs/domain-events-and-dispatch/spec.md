## MODIFIED Requirements

### Requirement: Webhook handler — the registered side-effect handler

**Reason**: Replace `backoff` library with internal async retry utility. Fibonacci → exponential backoff. Retry semantics unchanged.

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
