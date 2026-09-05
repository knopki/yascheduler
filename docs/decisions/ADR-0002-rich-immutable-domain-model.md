# ADR-0002: Rich immutable domain model with zero external dependencies

- **Status:** Accepted
- **Date:** 2026-05-29
- **Supersedes:**
- **Superseded by:**

## Context

The codebase had no formal domain layer — business rules were scattered across
`scheduler.py`, `db.py`, and CLI utilities, mixed with infrastructure calls (DB
queries, SSH, webhooks). This made the system hard to test, hard to reason
about, and resistant to change.

A domain layer is the foundation of the Hexagonal + DDD migration
(`docs/ARCHITECTURE.md`). The design had five core trade-offs to resolve:

1. **attrs vs frozen dataclasses** — attrs provides richer field options but
  introduces a third-party dependency. Frozen dataclasses are stdlib-only.
2. **ABC vs Protocol** — ABCs enforce explicit inheritance but couple adapters
  to port class hierarchy. `typing.Protocol` uses structural subtyping (PEP 1)
  so any object with matching methods satisfies the contract.
3. **Anemic vs rich domain model** — anemic entities are plain data carriers
  with business rules in services. The Cosmic Python school places rules on
  entities as methods.
4. **Mutable vs immutable entities** — mutable entities are conventional OOP.
  Immutable entities enforce explicit state transitions via `replace()`.
5. **Sync vs async port signatures** — sync signatures are simpler but require
  adapters to bridge async infrastructure.

## Decision

The domain layer uses stdlib-only frozen dataclasses for entities, `typing.Protocol`
for ports, rich entity methods for business rules, `dataclasses.replace()` for
state transitions, and `async def` signatures on port methods.

## Alternatives Considered

### attrs instead of frozen dataclasses

Rejected because the domain must have zero external dependencies (`design.md`
D1). Frozen dataclasses provide immutability, hashing, field defaults, and
`replace()` without third-party libraries.

### ABC instead of Protocol

Rejected because structural subtyping lets adapters implement the port contract
without inheriting from domain classes, reducing coupling (`design.md` D2).

### Anemic domain model (entities as data carriers)

Rejected per Cosmic Python. Business rules live on entities as methods
(`Task.allocate_to()` validates status; `ConnectedMachine.occupy()` validates
FREE state). Domain services handle cross-entity coordination only (`design.md`
D3).

### Mutable entities

Rejected because immutable entities make state transitions explicit and pure —
no hidden mutation, safe to share across async boundaries (`design.md` D4).

### Sync port signatures

Rejected because the ports only *declare* signatures; the domain never `await`s
anything. `async def` on ports lets adapters use async infrastructure without
wrapping (`design.md` D5).

## Consequences

- **Positive:** Domain layer is independently testable with no mocks of external
  services — entity behavior is pure function composition.
- **Positive:** Ports are structurally decoupled from adapters — a new adapter
  needs only matching method signatures, not an import from domain.
- **Positive:** Immutable entities are safe to share across async boundaries
  without locks.
- **Negative / trade-offs:** `frozen=True` prevents `__post_init__` mutation
  — all initialization must use `field(default_factory=...)`.
- **Accepted risks:** Protocol mismatch is caught late (no define-time
  enforcement). Mitigated by conformance tests with `@runtime_checkable`.
