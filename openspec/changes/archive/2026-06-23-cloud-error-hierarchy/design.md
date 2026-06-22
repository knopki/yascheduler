## Context

`yascheduler/domain/exceptions.py` defines a `DomainError(Exception)` hierarchy.
Every business exception descends from `DomainError` except two:
`CloudAllocateError` and `CloudSetupError`, which inherit directly from
`Exception`. They were relocated from `adapters/cloud/manager.py` during the
`cloud-provisioner-pure` change, which deliberately preserved their `Exception`
parentage ("preserve inheritance: Exception subclass") to keep that relocation
behavior-neutral. The result is a contract violation: the module claims
`DomainError` is the "base class for all domain exceptions", yet `except
DomainError` does not catch cloud failures.

Current call surface (verified against source):
- Raise sites: 10 in `manager.py` (`raise CloudAllocateError(...)` x3,
  `raise CloudSetupError(...)` x7).
- Catch sites: 2 `except CloudSetupError:` in `manager.py` (VM cleanup on
  setup failure).
- No `except DomainError`, `except CloudError`, or `except CloudAllocateError`
  exists anywhere in source today.
- Application-layer catchers (`allocate_task._provision_and_persist`,
  `orchestrator._allocator_consumer`) use broad `except Exception` (the
  orchestrator also narrows on `MachineConnectionError` first); none catch by
  a cloud base class.

Constraint: the application layer imports these exceptions from
`domain.exceptions` (not `adapters.cloud`) to satisfy `lint-imports` layering
rules. They must remain in the domain module.

## Goals / Non-Goals

**Goals:**
- Restore the `DomainError` contract: every domain exception (including cloud
  ones) is catchable via `except DomainError`.
- Group the two cloud operational exceptions under a single intermediate root,
  matching the existing pattern (`ValidationError`, `TaskError`,
  `SchedulingError` group their siblings).
- Keep the change non-breaking: no raise-site, catch-site, or constructor
  signature changes; existing catchers behave identically.

**Non-Goals:**
- Relocating `CloudCapacityExhaustedError` (stays under `SchedulingError`).
- Adding structured fields (provider, ip, reason) to the cloud exceptions.
- Re-exporting `CloudError` from `yascheduler.adapters.cloud`.
- Mutating the archived `cloud-provisioner-pure` artifacts.
- Redrawing the broader cloud-error taxonomy.

## Decisions

### D1: Introduce `CloudError(DomainError)` as a new intermediate root

Add a new class and reparent both cloud classes under it.

**Target hierarchy:**
```
Exception
└── DomainError
    ├── ValidationError
    │   ├── UnsupportedEngineError
    │   └── MissingInputFileError
    ├── TaskError
    │   ├── TaskAlreadyAllocatedError
    │   ├── TaskNotAllocatedError
    │   ├── TaskNotTodoError
    │   └── TaskNotRunningError
    ├── MachineBusyError
    ├── MachineConnectionError
    ├── SchedulingError
    │   ├── NoCompatibleNodeError
    │   └── CloudCapacityExhaustedError
    └── CloudError                  ← NEW
        ├── CloudAllocateError      ← reparented (Exception → CloudError)
        └── CloudSetupError         ← reparented (Exception → CloudError)
```

**Exact source changes (`domain/exceptions.py`):**

| Location | Before | After |
| --- | --- | --- |
| new class (insert before `CloudAllocateError`) | — | `class CloudError(DomainError):` with disambiguating docstring |
| `class CloudAllocateError(Exception):` | `Exception` | `CloudError` |
| `class CloudSetupError(Exception):` | `Exception` | `CloudError` |
| MODULE_MAP | no `CloudError` line | add `CloudError - Cloud provider operational errors` |

Both classes keep no custom `__init__` (free-form `str` via `Exception.__init__`).

**Alternatives considered (rejected during explore):**
- **R1 — reparent both directly to `DomainError`.** Rejected: flattens the
  hierarchy; the module uses intermediate roots to group siblings. Two cloud
  classes hanging off `DomainError` breaks that pattern.
- **R2 — keep `Exception` parent, document a carve-out** in the `DomainError`
  docstring ("base for all rule-violation exceptions, cloud excepted").
  Rejected: leaks an implementation detail into the public contract; callers
  must memorize which classes are "real" `DomainError`.
- **R3 — move both classes back to `adapters/cloud/`.** Rejected: re-introduces
  the `lint-imports` layering violation that `cloud-provisioner-pure` removed
  (application must not import from adapters).

### D2: `CloudCapacityExhaustedError` stays under `SchedulingError`

Despite its "Cloud" name, it is a domain scheduling rule ("cloud capacity
exhausted for task N") raised by the allocator, not by the cloud SDK adapter.
It is a distinct failure mode from operational provider/VM failures.

To prevent future confusion from the naming overlap, the `CloudError` docstring
explicitly states it covers **operational** cloud-provider failures and points
to `CloudCapacityExhaustedError` under `SchedulingError` for capacity planning.

**Alternatives considered:**
- (b) Move it under `CloudError` — rejected: conflates a scheduling rule with
  an SDK operational failure.
- (c) Make `CloudError(SchedulingError)` so cloud ops also catch under
  `except SchedulingError` — rejected: claims every cloud SDK failure is a
  scheduling error, which is false (setup/SSH failures occur after scheduling
  already succeeded).

### D3: Export surface

- `yascheduler.domain.__init__`: add `CloudError` to `__all__`, add it to the
  import from `.exceptions`, add a MODULE_MAP line.
- `yascheduler.adapters.cloud.__init__`: **unchanged.** It re-exports
  `CloudAllocateError`/`CloudSetupError` for adapter-internal back-compat; no
  adapter caller uses a base-class catch, so `CloudError` is not re-exported.

### D4: Knowledge graph

Add one annotation to `M-DOMAIN-EXCEPTIONS`:
`<class-CloudError PURPOSE="Cloud provider operational errors (base for CloudAllocateError/CloudSetupError)" />`.
No new module, no dependency/CrossLink change (purely an internal addition to
an existing module's class set).

### D5: Catchability matrix (caller-visible effect)

| Catch clause | Before | After |
| --- | --- | --- |
| `except CloudAllocateError` | ✓ | ✓ |
| `except CloudSetupError` | ✓ | ✓ |
| `except CloudError` | ✗ (no class) | ✓ NEW |
| `except DomainError` | ✗ **misses** | ✓ FIXED |
| `except SchedulingError` | ✗ | ✗ |
| `except Exception` (current app-layer + adapter cleanup) | ✓ | ✓ |

## Risks / Trade-offs

- **[Naming overlap: `CloudError` does not contain `CloudCapacityExhaustedError`]**
  → Mitigated by the `CloudError` docstring disambiguation (D2) and a negative
  test asserting `CloudError` is NOT a `SchedulingError`, which freezes the
  decision against a future "tidy-up".
- **[Silent re-flattening of the hierarchy by a later edit]** → Mitigated by
  positive subclass tests (`issubclass(CloudAllocateError, CloudError)`,
  `issubclass(CloudError, DomainError)`).
- **[MRO / behavior change for existing `except CloudSetupError` cleanup]** →
  None: a subclass still satisfies its own `except`; adding a parent above it
  does not affect catches that name the leaf class.
- **[Keeping `CloudError` name vs `CloudProviderError`]** → Kept `CloudError`
  for consistency with terse sibling roots (`TaskError`, `SchedulingError`) and
  the `Cloud*Error` child naming. Trade-off accepted; mitigated by docstring.

## Migration Plan

No data migration. Source-only base-class substitution.
- Deploy: ship the new class + reparented bases + export + graph annotation +
  tests together.
- Rollback: revert the commit; no persisted state, no schema, no wire format
  affected.

## Open Questions

None. The four explore-phase open questions are resolved:
1. `CloudCapacityExhaustedError` relocation → (a) stays under `SchedulingError`.
2. Structured `__init__` fields on `CloudError` → no (free-form `str` only).
3. Re-export `CloudError` from `adapters.cloud` → no.
4. Mutate frozen `cloud-provisioner-pure` design → no (forward-only).
