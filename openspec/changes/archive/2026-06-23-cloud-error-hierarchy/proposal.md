## Why

`CloudAllocateError` and `CloudSetupError` (`yascheduler/domain/exceptions.py`)
inherit directly from `Exception`, bypassing the `DomainError` hierarchy that
every other class in the module belongs to. This violates the module's own
contract ("Base class for all domain exceptions") and means a caller writing
`except DomainError` silently misses cloud failures. The inconsistency was
preserved during the `cloud-provisioner-pure` relocation; now that these
classes live in the domain module it is a deliberate decision to fix rather
than carry forward.

## What Changes

- Add a new intermediate root `CloudError(DomainError)`, parallel to the
  existing `SchedulingError` / `TaskError` / `ValidationError` roots.
- Reparent `CloudAllocateError` and `CloudSetupError` from `Exception` to
  `CloudError`.
- `CloudCapacityExhaustedError` stays under `SchedulingError` (it is a domain
  scheduling rule raised by the allocator, not an operational cloud-provider
  failure). The `CloudError` docstring disambiguates this explicitly.
- Export `CloudError` from `yascheduler.domain` (`__all__` + import).
- No raise-site, catch-site, or constructor-signature changes. Both classes
  keep the free-form `str` message contract (no structured fields).
- The adapter module (`yascheduler.adapters.cloud`) re-export surface is
  unchanged — `CloudError` is NOT re-exported there.
- Non-breaking: all existing catchers (`except CloudSetupError`,
  `except Exception`) are unaffected; `except DomainError` and
  `except CloudError` gain catchability.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `domain-exceptions`: Add a `CloudError(DomainError)` intermediate root
  requirement; add a requirement that `CloudAllocateError` and
  `CloudSetupError` subclass `CloudError` (and therefore `DomainError`);
  document that `CloudCapacityExhaustedError` deliberately remains under
  `SchedulingError`.

## Impact

- **Code**: `yascheduler/domain/exceptions.py` (new class + 2 reparents,
  MODULE_MAP), `yascheduler/domain/__init__.py` (`__all__` + import +
  MODULE_MAP).
- **Knowledge graph**: `docs/knowledge-graph.xml` — one new `class-CloudError`
  annotation on `M-DOMAIN-EXCEPTIONS`.
- **Tests**: new `domain-exceptions` unit tests asserting the subclass
  relationships, including a negative guard that `CloudError` is NOT a
  `SchedulingError`.
- **APIs / callers**: no breaking change. Public exception names and messages
  unchanged; only base classes change.
- **Dependencies**: none added.
