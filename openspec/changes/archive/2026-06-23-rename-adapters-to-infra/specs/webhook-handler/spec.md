## MODIFIED Requirements

### Requirement: Handler importable from adapters

The system SHALL expose the webhook handler from
`yascheduler.infra.notifier.webhook`.

#### Scenario: Import handler
- **WHEN** `from yascheduler.infra.notifier.webhook import webhook_handler` is executed
- **THEN** the function is available
