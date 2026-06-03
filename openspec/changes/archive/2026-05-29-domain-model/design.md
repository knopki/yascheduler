## Context

Phase 1 of the Hexagonal + DDD migration. The codebase currently has no
formal domain layer — business rules are mixed with infrastructure.
`docs/ARCHITECTURE.md` defines the target domain model. This design
implements it as a standalone, additive layer with zero impact on
existing code.

## Goals / Non-Goals

**Goals:**
- Define domain entities as frozen dataclasses with encapsulated business
  rules (rich domain model, not anemic).
- Define port interfaces as `typing.Protocol` classes.
- Define a `DomainError` exception hierarchy.
- Extract `match_task_to_node()` as a pure domain service.
- Zero external dependencies in `domain/` (stdlib only).
- Zero modifications to existing code.

**Non-Goals:**
- No wiring into the running system (Phase 3).
- No persistence adapter (Phase 2).
- No SSH/cloud adapters (Phase 4).
- No migration of existing models (attrs to dataclasses in config, etc.).

## Decisions

### D1: stdlib dataclasses instead of attrs

**Rationale**: Domain layer must have zero external dependencies. Frozen
dataclasses provide immutability, hashing, field defaults, and `replace()`
without third-party libraries.

### D2: typing.Protocol instead of ABC

**Rationale**: Structural subtyping. Adapters don't need to inherit from
port classes — they just implement the same methods. This reduces coupling.

### D3: Rich domain model, not anemic

**Rationale**: Following Cosmic Python. Business rules live on entities as
methods (e.g., `Task.allocate_to()` validates status, `ConnectedMachine.occupy()`
validates FREE state). Domain services (`match_task_to_node()`) handle
cross-entity coordination only.

### D4: Immutable entities with replace()

All domain objects are `frozen=True`. State changes return new instances
via `dataclasses.replace()`. This makes state transitions explicit and
pure — no hidden mutation.

### D5: I/O ports use async def

`TaskRepository`, `MachineGateway`, `CloudProvisioner` declare `async def`
methods. This does NOT couple the domain to asyncio — ports only declare
the contract. The domain never `await`s anything.

### D6: TaskContext for metadata

Replace the current `metadata: dict[str, Any]` (8+ keys with different
semantics) with a typed `TaskContext` value object. Known fields are
explicit; arbitrary extras preserved in `extra: dict[str, object]` for
backward compatibility.

### D7: Node vs ConnectedMachine separation

`Node` is a persistent record (DB row — ip, ncpus, enabled, cloud).
`ConnectedMachine` is a runtime entity (SSH-connected — platform, state,
free_since). They are separate domain types with different lifecycles.

## Risks / Trade-offs

- **Protocol mismatch caught late**: Protocol doesn't enforce implementation
  at define-time. Mitigation: conformance tests with `@runtime_checkable`
  added in Phase 2.
- **frozen=True prevents __post_init__ mutation**: All state transitions go
  through `replace()`. Initialization should use `field(default_factory=...)`
  rather than `object.__setattr__`.
- **TaskContext.extra dict allows untyped data**: Necessary for backward
  compatibility with arbitrary input-file contents. The conversion boundary
  (`from_metadata()`) will be typed when introduced in Phase 2.
