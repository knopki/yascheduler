# ADR-0010: Config types live in the layer that owns their concern

- **Status:** Accepted
- **Date:** 2026-06-26
- **Supersedes:**
- **Superseded by:**

## Context

Configuration was originally bundled in a residual `config/` package that
sat outside the layer contract. The package mixed concerns: domain-shaped
settings consumed across layers, persistence-specific connection
parameters, INI-parsing helpers, provider-specific DTOs, and a root
aggregate tying them together.

This produced two structural problems:

- **Layer ambiguity.** Configuration types had no architectural home, so
  consumers in any layer could (and did) reach into `config/`, bypassing
  the layer contract enforced everywhere else.
- **Aggregate coupling.** The orchestrator took the whole `Config`
  aggregate, pulling in entrypoints-shaped concerns (INI parsing, the
  composition root) through an `application → entrypoints` edge that the
  contract forbids.

## Decision

1. **No residual `config/` package.** Every configuration type lives in
  the layer that matches its concern:

<!---->

- Cross-layer domain settings (paths, defaults, limits consumed by
  both application and entrypoints) live in `domain/`.
- Persistence-specific configuration (database connection) lives in
  `infra/`.
- Provider-specific DTOs live in `infra/` and explicitly inherit the
  domain `CloudConfig` Protocol — via runtime import, since Python
  requires base classes at class-definition time.
- The aggregate that wires these together for a running process lives
  in `entrypoints/`, next to the composition root.
- INI-parsing helpers live in `entrypoints/`; domain types do not
  import `ConfigParser`.

1. **The orchestrator takes unpacked domain settings**, not the
  aggregate. It depends only on the application-layer edge to domain,
  never on entrypoints.

## Alternatives Considered

### Keep a residual `config/` package outside the layer contract

Rejected — the exemption is the defect. Every config type has a natural
architectural home; declaring it removes the ambiguity permanently.

### Pass the aggregate to the orchestrator

Rejected — the aggregate is a composition-root concept. Passing it
through the application layer would force `application → entrypoints`,
breaking the layer contract established in ADR-0001.

### Parse INI in domain types (as classmethods on value objects)

Rejected — domain may not import `ConfigParser`. Parsing is a
composition-root concern.

### Provider DTOs inheriting `CloudConfig` only under `TYPE_CHECKING`

Rejected — Python evaluates base classes at class-definition time.
A `TYPE_CHECKING`-only import leaves the base undefined at runtime.
The runtime import is required.

## Consequences

- **Positive:** The layer contract is enforced uniformly — no exempted
  package, no special case.
- **Positive:** The orchestrator's signature is honest about its
  dependencies: it consumes domain settings, not a composition-root
  aggregate.
- **Positive:** Domain types stay free of INI-parsing concerns.
- **Negative / trade-offs:** INI parsing lives away from the value
  objects it produces. The parser module documents the accepted INI
  keys so the indirection is discoverable.
- **Accepted risks:** Provider DTOs carry fields the domain Protocol
  hides from application consumers. This is interface segregation by
  design, not drift.
