# Explore Brief: cloud-error-hierarchy

## Problem

`CloudAllocateError` and `CloudSetupError` (`yascheduler/domain/exceptions.py:136,140`)
inherit directly from `Exception`, bypassing the `DomainError` hierarchy that
every other class in the module belongs to. Result: the module's own contract
(`DomainError - Base class for all domain exceptions`) is violated, and a
caller writing `except DomainError` will not catch cloud failures.

Not a regression — preserved from the old `adapters/cloud/manager.py` location
per the frozen `cloud-provisioner-pure` design.md task 2.3 ("preserve
inheritance: Exception subclass"). Now that they live in the domain module,
the inconsistency is louder and worth a deliberate decision rather than a
stealth fix snuck into the previous hardening pass.

## Rejected Alternatives

### R1: Reparent directly to `DomainError`

```python
class CloudAllocateError(DomainError): ...
class CloudSetupError(DomainError): ...
```

**Rejected because:** flattens the hierarchy; the module already uses
intermediate roots (`ValidationError`, `TaskError`, `SchedulingError`) to
group sibling classes. Two cloud classes hanging directly off `DomainError`
breaks that pattern.

### R2: Keep `Exception` parent, document the carve-out

Leave inheritance as-is; rewrite `DomainError` docstring to "Base class for
all **rule-violation** domain exceptions (operational cloud failures excepted)".

**Rejected because:** the carve-out leaks an implementation detail into the
public contract; callers must remember which classes are "real" `DomainError`
and which aren't. Worst of both worlds.

### R3: Move them back to `adapters/cloud/`

Argue they're adapter-side operational failures, not domain rules, and
relocate out of `domain/exceptions.py`.

**Rejected because:** the application layer (`allocate_task.py`) imports them
from `domain.exceptions` to avoid `lint-imports` layering violations
(application must not import from `adapters`). Returning them to adapters
re-introduces the very layering violation the `cloud-provisioner-pure` change
just removed.

## Final Approach — introduce `CloudError` sub-root

Single decision-level change: add `CloudError(DomainError)` as a new
intermediate root, parallel to `SchedulingError` / `TaskError` /
`ValidationError`, and reparent both cloud classes under it.

### Class hierarchy after change

```
Exception
└── DomainError
    ├── ValidationError
    ├── TaskError
    ├── MachineBusyError
    ├── MachineConnectionError
    ├── SchedulingError
    │   ├── NoCompatibleNodeError
    │   └── CloudCapacityExhaustedError
    └── CloudError                  ← NEW
        ├── CloudAllocateError      ← reparented (Exception → CloudError)
        └── CloudSetupError         ← reparented (Exception → CloudError)
```

### Mapping table — exact changes

| File:Line                          | Before                                 | After                                  |
| ---------------------------------- | -------------------------------------- | -------------------------------------- |
| `domain/exceptions.py:136`         | `class CloudAllocateError(Exception):` | `class CloudError(DomainError):` (new, inserted) |
| `domain/exceptions.py:136` (was)   | `class CloudAllocateError(Exception):` | `class CloudAllocateError(CloudError):` |
| `domain/exceptions.py:140`         | `class CloudSetupError(Exception):`    | `class CloudSetupError(CloudError):`   |
| `domain/exceptions.py` MODULE_MAP  | (no `CloudError` entry)                | Add `CloudError - Cloud provider operational errors` |
| `domain/__init__.py`               | `__all__` has no `CloudError`           | Add `CloudError` to `__all__` + import |
| `domain/__init__.py` MODULE_MAP    | (no `CloudError` entry)                | Add `CloudError` line                  |
| `docs/knowledge-graph.xml` M-DOMAIN-EXCEPTIONS annotations | no `class-CloudError` | Add `<class-CloudError PURPOSE="Cloud provider operational errors (base for CloudAllocateError/CloudSetupError)" />` |
| `adapters/cloud/manager.py` MODULE_MAP | (no change — re-exports unchanged) | unchanged                              |
| `adapters/cloud/__init__.py`       | re-exports `CloudAllocateError`, `CloudSetupError` | unchanged (do NOT re-export `CloudError` — adapter-internal callers don't need the new root) |
| Public re-exports elsewhere        | n/a                                    | unchanged — no other file imports these by base class |

### `__init__` / constructor signatures

Both classes keep no custom `__init__` — they take a free-form `str` message
(`Exception.__init__`). No call-site signature changes. The 9 raise sites
(`manager.py:155,158,175,194,325,332,342,349,407`) and 2 internal `except
CloudSetupError` cleanup sites (`manager.py:181,329`) are byte-for-byte
unchanged.

## Cross-module data flows

No new data flow. The change is purely structural — base class substitution.

**Catchability matrix** (what changes for callers):

| Catch clause                              | Before | After |
| ----------------------------------------- | ------ | ----- |
| `except CloudAllocateError`               | ✓      | ✓     |
| `except CloudSetupError`                  | ✓      | ✓     |
| `except CloudError`                       | ✗ (no such class) | ✓ NEW |
| `except DomainError`                      | ✗ **misses** | ✓ NEW |
| `except SchedulingError`                  | ✗      | ✗     |
| `except Exception` (current pattern in `_allocator_consumer`, `allocate_task._provision_and_persist`) | ✓ | ✓ |

**Today's catchers (verified via `rg`):**

- `yascheduler/application/allocate_task.py` `_provision_and_persist` — bare `except Exception`, no type narrowing. Unaffected.
- `yascheduler/application/orchestrator.py` `_allocator_consumer` — bare `except Exception`. Unaffected.
- `yascheduler/adapters/cloud/manager.py:181,329` — `except CloudSetupError` for VM cleanup-on-setup-failure. Unaffected.
- No `except DomainError` exists in source today.

So the change is **non-breaking for current callers** and **adds catchability**
(`except DomainError`, `except CloudError`) for future use.

## Open Questions

1. **Should `CloudCapacityExhaustedError` move too?** It currently lives under
   `SchedulingError` (a sibling of the proposed `CloudError`). Semantically
   it's also cloud-related. Options:
   - (a) Leave it under `SchedulingError` (it's raised from allocator logic,
       not from cloud SDK ops — distinct failure mode).
   - (b) Move it under `CloudError` (consistency: "all cloud errors under
       one root").
   - (c) Make `CloudError` itself inherit from `SchedulingError` so it nests
       under scheduling too (`CloudError(SchedulingError)`) — gives catchers
       both granularities.
   Lean: **(a)** — the proposal scope is "fix the inconsistency", not
   "redraw the cloud-error map". `CloudCapacityExhaustedError` is a domain
   rule ("no node fits") raised by the allocator, not by the cloud adapter.
   Confirm in proposal review.

2. **Should `CloudError` get a custom `__init__`** carrying structured fields
   (provider name, ip, reason) like `MachineConnectionError(ip, reason)`?
   Today `CloudAllocateError`/`CloudSetupError` take a free-form `str` only.
   Lean: **no** in this change — adding fields would touch all 9 raise sites
   and break callers that pass plain strings. Separate enhancement.

3. **`CloudError` re-export from `yascheduler.adapters.cloud`?** The adapter
   module currently re-exports `CloudAllocateError`/`CloudSetupError` (back-compat
   for adapter-internal callers). Should it also re-export `CloudError`?
   Lean: **no** — no adapter-internal caller uses a base-class catch today;
   keep the adapter re-export surface minimal. Revisit if a future adapter
   helper wants `except CloudError`.

4. **Update frozen `cloud-provisioner-pure` design.md task 2.3 retroactively,
   or treat this as a forward-only fix?**
   Lean: **forward-only** — `cloud-provisioner-pure` is implemented and about
   to archive; this new change supersedes the "Exception subclass" clause by
   explicit decision. Reference the archived design in the new proposal's
   "Why" but don't mutate archived artifacts.

## Scope Boundaries

**In scope:**
- `domain/exceptions.py` — new `CloudError` class, reparent 2 classes, MODULE_MAP
- `domain/__init__.py` — add `CloudError` to `__all__` + import + MODULE_MAP
- `docs/knowledge-graph.xml` — 1 new annotation on M-DOMAIN-EXCEPTIONS
- Unit tests — add `test_cloud_error_hierarchy` (subclass-of assertions)

**Out of scope:**
- Any raise-site change (9 sites in `manager.py`)
- Any catcher rewrite
- `CloudCapacityExhaustedError` relocation (open question 1)
- Structured fields on `CloudError` (open question 2)
- Adapter re-export of `CloudError` (open question 3)
- Touching the archived `cloud-provisioner-pure` artifacts
