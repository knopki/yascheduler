# ADR-0003: Domain events decouple side effects from use cases

- **Status:** Accepted
- **Date:** 2026-06-19
- **Supersedes:**
- **Superseded by:**

## Context

Before this decision, use cases called webhooks directly. The same side-effect
coupling that had previously been extracted out of `scheduler.py` was
re-appearing inside use case bodies.

Without intervention, every new notification channel (logging, metrics,
audit) would require modifying each use case, and side-effect logic would
keep mixing with business logic.

Three viable approaches were considered:

1. **Events in the application layer** — would force the Task aggregate to
  depend upward into `application/`, breaking the hexagonal boundary.
2. **External message broker** (Kafka, Redis) — operational complexity
  with no current multi-process consumer.
3. **Persistent outbox table** — survives crashes at the cost of an extra
  table, a dispatcher loop, and retry semantics.

## Decision

Side effects (webhook delivery today; future logging, metrics, audit) are
decoupled from use cases through domain events.

- Events are part of the **domain layer**, not the application layer — they
  express business occurrences (`TaskCreated`, `TaskAllocated`, …) and the
  domain must not depend upward.
- Dispatch is **in-process only**, through a single in-memory registry.
- Dispatch fires **strictly after `UnitOfWork.commit()` succeeds**; a
  rollback discards any collected events without invocation.

The webhook adapter is one consumer of these events; it lives in
`infra/notifier/` like any other driven adapter.

## Alternatives Considered

### Events in the application layer

Would couple the Task aggregate upward into `application/`, breaking the
hexagonal boundary established in ADR-0001.

### External message broker (Kafka / Redis)

Would add operational complexity (a service to run, schema to manage,
delivery semantics to configure) for a single in-process consumer. Deferred
until a real multi-process consumer appears.

### Persistent outbox table

Would survive process crashes between commit and dispatch at the cost of an
extra table, a background dispatcher, and retry/idempotency logic. Webhook
delivery is best-effort; the operational overhead is not justified.

## Consequences

- **Positive:** New side-effect channels (logging, metrics) require one
  handler registration — no use case changes.
- **Positive:** Post-commit dispatch guarantees handlers always observe
  durable state; rollback is enough to undo side effects, no separate
  cleanup path.
- **Positive:** Domain purity preserved — events live where the business
  concepts live, not where the dispatch infrastructure lives.
- **Accepted risks:** In-process dispatch means events are lost if the
  process crashes between commit and dispatch. Acceptable because webhook
  delivery is non-critical and best-effort by design. Re-evaluate if a
  side effect ever needs at-least-once delivery.
