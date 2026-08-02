## Purpose

Define the domain events emitted on task lifecycle transitions, the
in-process post-commit dispatch boundary, and the webhook delivery
contract. A message bus decouples event recording from side-effect
handlers. The webhook handler is the registered handler that turns
events into outbound HTTP calls.
## Requirements
### Requirement: Event roster

The system SHALL emit one event per task lifecycle transition. Events
do not change after they are recorded. Each event carries the task
identity and the webhook delivery metadata. The event types and their
type-specific fields are:

| Event | Trigger | Type-specific fields |
| --- | --- | --- |
| `TaskCreated` | New task inserted | `engine_name` |
| `TaskAllocated` | Task bound to a node and started | `node_id`, `engine_name` |
| `TaskCompleted` | Task finished successfully | `local_folder` |
| `TaskFailed` | Task rejected or run failed | `reason` |
| `TaskAbandoned` | Task node disappeared | `node_id` |

#### Scenario: each transition emits its mapped event

- **WHEN** any task lifecycle transition runs
- **THEN** the event listed above for that transition is emitted with its listed type-specific fields

### Requirement: Use-case-to-event mapping

Each task use case SHALL emit the event that matches its transition:

| Use case | Event emitted | Trigger |
| --- | --- | --- |
| Task submission | `TaskCreated` | New task inserted |
| Allocation | `TaskAllocated` | Task started on a free node |
| Allocation, engine not found | `TaskFailed` | Engine not found |
| Consume success | `TaskCompleted` | Successful completion |
| Consume failure | `TaskFailed` | Download failure |
| Orchestrator | `TaskAbandoned` | Node disappeared |

The orchestrator emits `TaskAbandoned` when a node disappears under a
RUNNING task. The disappeared node always has an identity, because a
RUNNING task keeps its node binding until it transitions to DONE.

#### Scenario: each use case emits its mapped event

- **WHEN** any use case above performs its transition
- **THEN** the event listed for that use case is emitted

### Requirement: In-process post-commit dispatch

Events recorded by saved aggregates SHALL be collected inside the unit
of work and dispatched after the database transaction commits. A
rollback SHALL discard the collected events without dispatch. A
dispatch failure SHALL NOT roll back the committed transaction. The
dispatch mechanism is chosen in ADR-0003.

#### Scenario: events dispatched after a successful commit

- **WHEN** the unit of work commits with aggregates that recorded events
- **THEN** the database commit completes first, then the events are dispatched

#### Scenario: events contained on rollback or dispatch failure

- **WHEN** a rollback is triggered, or a handler raises during dispatch after commit
- **THEN** events are discarded without dispatch on rollback, and a dispatch failure leaves the committed transaction in place

### Requirement: Webhook delivery contract

The webhook handler SHALL deliver each event as an HTTP POST to the
configured webhook URL. The body SHALL carry the task identity and the
`TaskStatus` value that matches the event type:

| Event | `TaskStatus` |
| --- | --- |
| `TaskCreated` | `TO_DO` |
| `TaskAllocated` | `RUNNING` |
| `TaskCompleted`, `TaskFailed`, `TaskAbandoned` | `DONE` |

Delivery SHALL be skipped when no URL is configured. Transient delivery
failures SHALL be retried. Final delivery failures SHALL be logged and
suppressed; they SHALL NOT propagate into the use-case layer.

#### Scenario: webhook payload status matches the event type

- **WHEN** an event is delivered to a configured webhook URL
- **THEN** the POST body carries the `TaskStatus` value listed above for that event type

#### Scenario: delivery skips, retries, and suppresses failures

- **WHEN** no URL is configured, the endpoint fails transiently, or the endpoint fails permanently
- **THEN** delivery is skipped when no URL is set, retried on transient failure, and on final failure logged without raising into the use-case layer

