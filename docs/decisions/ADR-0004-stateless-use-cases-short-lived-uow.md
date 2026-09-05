# ADR-0004: Stateless use cases, scalar IDs, short-lived UoW

- **Status:** Accepted
- **Date:** 2026-06-23
- **Supersedes:**
- **Superseded by:**

## Context

After the domain layer was extracted, application logic still held direct
references to the database and to legacy row models. Three of the four use
cases bypassed the `UnitOfWork` abstraction, and the orchestrator kept a
persistent DB connection that was never closed on the read path.

The forces at play:

- **Dual persistence path.** Some use cases went through UoW + domain
  entities; others imported the DB class directly. Same spec, two
  implementations.
- **Transaction ownership ambiguity.** When a producer loads an aggregate
  outside a UoW and a use case saves it inside one, stale reads become
  possible.
- **Connection lifecycle leak.** The orchestrator held a persistent DB
  connection whose lifetime was never explicitly managed.

## Decision

1. **Use cases are stateless `async` functions** that receive their ports
  and a Unit-of-Work factory as arguments. No use-case class, no shared
  mutable state.

2. **Use cases accept scalar IDs (`task_id`, `node_id`), not aggregates.**
  The use case loads the aggregate inside its own UoW transaction,
  acquiring exclusive ownership for the transaction duration.

3. **Producers open a short-lived UoW per poll cycle** (open, query/save,
  close). No persistent DB connection is held by the orchestrator across
  cycles.

4. **`AbstractUnitOfWork` lives in `application/`, not `domain/`.** The
  UoW abstraction coordinates multiple repositories within a transaction
  — that is an application concern. Domain defines repository ports; it
  does not know transactions exist.

Wiring dependencies is a separate concern, handled by per-entry-point
factories in the composition root (see ADR-0001, ADR-0010).

## Alternatives Considered

### Pass loaded aggregates into use cases

Rejected — splits transaction ownership between producer (load) and use
case (save), masking stale reads. The use case cannot guarantee the
aggregate is fresh.

### Persistent DB connection in the orchestrator

Rejected — ties orchestrator lifecycle to connection lifecycle, prevents
short-lived transactions, and removes the test seam (the orchestrator can
no longer be constructed against a fake UoW factory).

### Stateful use case classes holding port references

Rejected — adds object lifecycle boilerplate for no benefit. Stateless
functions compose cleanly, are trivially testable with fakes, and match
the application layer's role as a thin coordinator over domain + ports.

### UnitOfWork in the domain layer

Rejected — the UoW coordinates multiple repository abstractions, which is
an application-level concern. Putting it in `domain/` would force the
domain to know about transactions.

## Consequences

- **Positive:** Single persistence path — every use case goes through UoW
  → repositories → domain entities.
- **Positive:** Clear transaction ownership — load and save happen inside
  the same UoW boundary; no stale reads.
- **Positive:** Producers release connections every cycle; no leaks.
- **Positive:** Use cases are testable in isolation against fake ports and
  a fake UoW factory.
- **Negative / trade-offs:** Use cases cannot run without ports — they
  require fakes or mocks in tests. Inherent to the pattern.
- **Negative / trade-offs:** Each producer poll opens and closes a UoW.
  At default poll intervals the cost is negligible; connection pooling is
  a separate optimisation.
- **Accepted risks:** Side effects that must run after commit (webhooks,
  see ADR-0003) are dispatched from `UoW.commit()`, so the use case itself
  stays side-effect-free. A crash between commit and dispatch loses them.
