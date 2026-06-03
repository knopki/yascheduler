## Why

The codebase has no formal domain layer — business rules are scattered across
`scheduler.py`, `db.py`, and CLI utilities, mixed with infrastructure calls
(DB queries, SSH, webhooks). This makes the system hard to test, hard to
reason about, and resistant to change. Introducing a domain layer is the
first step of the Hexagonal + DDD migration (see `docs/ARCHITECTURE.md`).

## What Changes

- Create `yascheduler/domain/` with pure Python dataclasses, Protocols, and
  domain services — zero external dependencies, zero infrastructure coupling.
- Define domain entities: `Task`, `Node`, `ConnectedMachine`, value objects:
  `Engine`, `TaskContext`, `ProcessResult`, and enums: `TaskStatus`, `MachineState`.
- Define port interfaces: `TaskRepository`, `NodeRepository`,
  `MachineGateway`, `CloudProvisioner` as `typing.Protocol` classes.
- Define a domain exception hierarchy under `DomainError`.
- Implement one domain service: `match_task_to_node()`.
- No existing code is modified. The new domain code is purely additive —
  it is not wired into the running system yet (that happens in subsequent
  phases).

## Capabilities

### New Capabilities
- `domain-entities`: Task lifecycle, node records, connected machine state,
  engine specs, typed task context — all as frozen dataclasses with
  encapsulated business rules (rich domain model, not anemic).
- `domain-ports`: Abstract interfaces for persistence, machine operations,
  and cloud provisioning — defining the contracts adapters will implement.
- `domain-exceptions`: DomainError hierarchy for business-level error handling.
- `domain-services`: Cross-entity domain logic (allocation policy).

### Modified Capabilities
<!-- No existing specs are affected — this is a purely additive change. -->

## Impact

- New directory: `yascheduler/domain/` (4 files: `model.py`, `ports.py`,
  `exceptions.py`, `services.py`).
- No existing files modified. No API changes. No dependency changes.
- `docs/ARCHITECTURE.md` already documents the target model — this proposal
  implements it.
- `docs/knowledge-graph.xml` must be updated with M-* entries for new modules
  after implementation.
