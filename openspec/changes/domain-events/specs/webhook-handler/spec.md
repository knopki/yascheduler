## ADDED Requirements

### Requirement: Webhook handler processes all task events

The system SHALL provide a `webhook_handler` async function that processes
`TaskCreated`, `TaskAllocated`, `TaskCompleted`, `TaskFailed`, and
`TaskAbandoned` events by sending webhook notifications.

#### Scenario: TaskCreated sends TO_DO webhook
- **WHEN** `webhook_handler(TaskCreated(task_id=42, webhook_url="https://...", ...), http)` is called
- **THEN** an HTTP POST is sent to the webhook_url with status=0 (TO_DO)

#### Scenario: TaskAllocated sends RUNNING webhook
- **WHEN** `webhook_handler(TaskAllocated(task_id=42, ...), http)` is called
- **THEN** an HTTP POST is sent with status=1 (RUNNING)

#### Scenario: TaskCompleted sends DONE webhook
- **WHEN** `webhook_handler(TaskCompleted(task_id=42, ...), http)` is called
- **THEN** an HTTP POST is sent with status=2 (DONE)

#### Scenario: Webhook failure is logged, not raised
- **WHEN** the webhook HTTP request fails
- **THEN** the error is logged; the exception is NOT propagated

#### Scenario: No webhook URL — event skipped
- **WHEN** `webhook_handler(TaskCreated(task_id=42, webhook_url=None, ...), http)` is called
- **THEN** no HTTP request is made

### Requirement: Webhook handler uses aiohttp with retry

The system SHALL implement webhook delivery with exponential backoff retry
(using the existing `backoff` library) and a semaphore for rate limiting.

#### Scenario: Retry on transient failure
- **WHEN** the webhook endpoint returns 503
- **THEN** the request is retried with backoff up to 60 seconds

### Requirement: Handler importable from adapters

The system SHALL expose the webhook handler from
`yascheduler.adapters.notifier.webhook`.

#### Scenario: Import handler
- **WHEN** `from yascheduler.adapters.notifier.webhook import webhook_handler` is executed
- **THEN** the function is available
