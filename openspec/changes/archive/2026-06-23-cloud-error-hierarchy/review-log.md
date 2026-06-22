# Review Log: cloud-error-hierarchy

## proposal Round 1 — 2026-06-23

### 🔴 Fixed
(none)

### 🟡 Addressed
(none)

### 🔴 Outstanding
(none — APPROVED, frozen)

### 🟢 Notes
- Positive scope additions ratified: `CloudError` disambiguating docstring (operationalizes OQ1=a); negative test guard `CloudError` is NOT `SchedulingError` (locks OQ1=a).
- Concrete raise/catch site enumeration (9 raise, 2 except in manager.py) deferred to design.md/tasks.md.
- Optional: design/tasks should note "no `except DomainError` in source today" to make non-breaking argument airtight.

## design Round 1 — 2026-06-23

### 🟡 Addressed
- Raise-site count was 9 (CloudSetupError x6); actual is 10 (x7, missed manager.py:354). Corrected to 10 / x3+x7. Verified via `rg -c`: CloudAllocateError=3, CloudSetupError=7.

### 🟢 Addressed
- Orchestrator catcher wording: it narrows on `MachineConnectionError` before bare `except Exception`; reworded.

### 🔴 Outstanding
(none)

## design Round 2 — 2026-06-23

### 🔴 Fixed
(none)

### 🔴 Outstanding
(none — k-reviewer-fast subagent errored; main agent verified fix directly via `rg -c` against manager.py: 3+7=10 confirmed. design.md frozen.)

## specs Round 1 — 2026-06-23

### 🟡 Addressed
- D3 adapter NON-re-export invariant was not pinned in spec. Added requirement "CloudError is not re-exported from yascheduler.adapters.cloud" with ImportError scenario + leaf-classes-still-re-exported scenario (declarative, locks existing D3 decision). `openspec validate` passes.

### 🔴 Outstanding
(none — specs frozen)

## tasks Round 1 — 2026-06-23

### 🟡 Addressed
- Task 1.2 was self-contradictory (biased toward deleting an accurate graph note) → rewritten to deterministically append `(subclass of CloudError)` and KEEP `(re-exported for backwards compat)`.
- Task 4.5 omitted the "no custom __init__" AND-clause of the spec scenario → added `"__init__" not in CloudAllocateError.__dict__` assertion for both leaf classes.
- Task 4.4 didn't acknowledge unchanged MODIFIED-requirement scenarios → added confirmation of existing NoCompatibleNodeError/CloudCapacityExhaustedError field coverage.

### 🔴 Outstanding
(none)

## tasks Round 2 — 2026-06-23

### 🔴 Fixed
(none)

### 🔴 Outstanding
(none — k-reviewer-fast subagent errored; main agent verified all three fixes directly in tasks.md (1.2, 4.4, 4.5). tasks.md frozen.)
