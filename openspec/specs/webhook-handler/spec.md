## Purpose

Defines the webhook notification adapter that translates domain events into outbound HTTP webhook calls. The handler is registered on the message bus as a side-effect handler; webhook delivery failures are logged and suppressed so they never propagate back into the use-case layer.

## Requirements

### Requirement: Webhook handler processes all task events

The system SHALL provide a `webhook_handler` async function that processes
`TaskCreated`, `TaskAllocated`, `TaskCompleted`, `TaskFailed`, and
`TaskAbandoned` events by sending webhook notifications. The handler SHALL
access `webhook_url` and `webhook_custom_params` from the `DomainEvent` base
class fields.

#### Scenario: TaskCreated sends TO_DO webhook
- **WHEN** `webhook_handler(TaskCreated(task_id=42, webhook_url="https://...", webhook_custom_params={}, engine_name="fleur"), http)` is called
- **THEN** an HTTP POST is sent to the webhook_url with status=0 (TO_DO)

#### Scenario: TaskAllocated sends RUNNING webhook
- **WHEN** `webhook_handler(TaskAllocated(task_id=42, webhook_url="https://...", webhook_custom_params={}, node_ip="10.0.0.1", engine_name="fleur"), http)` is called
- **THEN** an HTTP POST is sent with status=1 (RUNNING)

#### Scenario: TaskCompleted sends DONE webhook
- **WHEN** `webhook_handler(TaskCompleted(task_id=42, webhook_url="https://...", webhook_custom_params={}, local_folder="/data/...", has_errors=False), http)` is called
- **THEN** an HTTP POST is sent with status=2 (DONE)

#### Scenario: TaskFailed sends DONE webhook with error
- **WHEN** `webhook_handler(TaskFailed(task_id=42, webhook_url="https://...", webhook_custom_params={}, reason="unsupported engine"), http)` is called
- **THEN** an HTTP POST is sent with status=2 (DONE) — failure is reported as DONE+error

#### Scenario: TaskAbandoned sends DONE webhook with error
- **WHEN** `webhook_handler(TaskAbandoned(task_id=42, webhook_url="https://...", webhook_custom_params={}, node_ip="10.0.0.1"), http)` is called
- **THEN** an HTTP POST is sent with status=2 (DONE) — abandonment is reported as DONE+error

#### Scenario: Webhook failure is logged, not raised
- **WHEN** the webhook HTTP request fails
- **THEN** the error is logged; the exception is NOT propagated

#### Scenario: No webhook URL — event skipped
- **WHEN** `webhook_handler(TaskCreated(task_id=42, webhook_url=None, webhook_custom_params={}, engine_name="fleur"), http)` is called
- **THEN** no HTTP request is made

### Requirement: Webhook handler uses aiohttp with retry

The system SHALL implement webhook delivery with fibonacci backoff retry
(using the existing `backoff` library, `backoff.fibo` strategy) and a semaphore
for rate limiting.

#### Scenario: Retry on transient failure
- **WHEN** the webhook endpoint returns 503
- **THEN** the request is retried with fibonacci backoff up to `max_time=60` seconds

### Requirement: Handler importable from adapters

The system SHALL expose the webhook handler from
`yascheduler.infra.notifier.webhook`.

#### Scenario: Import handler
- **WHEN** `from yascheduler.infra.notifier.webhook import webhook_handler` is executed
- **THEN** the function is available
