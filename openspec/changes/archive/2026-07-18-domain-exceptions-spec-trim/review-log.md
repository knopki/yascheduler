## proposal / specs / tasks Round 1 — 2026-07-17

Single comprehensive self-review of all three artifacts (proposal.md,
specs/domain-exceptions/spec.md, tasks.md) written in one pass. Reviewer =
author. The review is run against the GRACE-lite review checklist, the
project's `domain-entities-spec-trim` and `domain-events-spec-trim` precedents,
and the user's explicit constraints:

- "выдумывать поля нельзя" — no invented contract fields.
- "Использовать поля не по назначению нельзя" — fields must be used per their
  defined purpose.
- "новых полей типа SHALL NOT" — no invented `SHALL NOT` pseudo-normative
  enumerations of absent code/attributes in the spec.
- "записывания в RATIONALE просто всего подряд" — RATIONALE is Q/A only, not a
  dumping ground.
- "PURPOSE должно быть WHY, а не WHAT" — every PURPOSE states why, not what.
- "блок должен обрамлять всё содержимое" — a `CLASS_*` region encloses the full
  class body (class line + docstring + `__init__` + every attribute), not only
  the contract header.

Validation run before review:
- `openspec validate --all --json` → 22/22 passed (2 changes + 20 specs), exit 0.
- `rg -n 'SHALL NOT'` on the spec delta → 0 hits (all invented negative-normative
  prose removed; observable negative assertions now live only in Gherkin
  `THEN` clauses: "the exception does NOT have a `hostname` attribute",
  "`issubclass(CloudCapacityExhaustedError, CloudError)` is false", "the import
  raises `ImportError`").
- Scenario count: main spec 23; delta carries 18 (the 4 MODIFIED requirements);
  the 3 untouched requirements (`DomainError base class` = 1, `ValidationError
  hierarchy` = 2, `MachineConnectionError` = 2) carry the remaining 5. 18 + 5
  = 23. No scenario deleted, no scenario reworded destructively.

### 🔴 Issues (found and fixed in this round)

- **The delta's `CloudError hierarchy` requirement dropped the `Import domain
  exceptions` scenario.** In the main spec that scenario is attached to the
  `CloudError hierarchy` requirement (it is the last scenario in the file, with
  no intervening requirement header). The first draft of the delta reproduced
  only the 9 cloud-specific scenarios and omitted the 10th (`from
  yascheduler.domain.exceptions import DomainError, ValidationError`). Because
  `CloudError hierarchy` is a MODIFIED requirement, the archive step would have
  replaced the whole block and silently deleted that scenario — breaking the
  "every observable scenario survives" promise. Fixed by appending the scenario
  verbatim to the delta's `CloudError hierarchy` block; delta scenario count
  went 17 → 18, preserving the full 23 after archive.

### 🟡 Suggestions (considered, not blocking)

- **All 15 public exception classes get a `CLASS_*` region, including the four
  empty grouping bases (`DomainError`, `ValidationError`, `TaskError`,
  `SchedulingError`).** The GRACE rule says "Do not mark up trivial code", and
  these bases are 2-line `class X(Parent): """doc"""` stubs. They could
  arguably be skipped under the trivial-code exemption. The proposal marks
  them anyway because (a) they are PUBLIC types exported via
  `yascheduler.domain.exceptions.__all__`, (b) two of them carry non-trivial
  `RATIONALE` that absorbs spec content (`CLASS_TaskError`), (c) the hierarchy
  IS the point of this file — the bases are the navigational anchors, and (d)
  the existing `MODULE_CONTRACT` already establishes markup for this file, so
  the "if an entity is annotated by markup, it must always be wrapped in a
  region" clause triggers. This mirrors the `domain-events-spec-trim` decision
  to mark all 6 event subclasses for consistency. Stays as proposed.

- **`CLASS_MachineBusyError` carries `ENSURES` + `RATIONALE` for the
  no-`hostname` property.** The "sets no `hostname` attribute" postcondition is
  partly redundant with the existing test
  (`assert not hasattr(exc, "hostname")`) and the Gherkin scenario
  ("the exception does NOT have a `hostname` attribute"). Three places assert
  the same fact. The redundancy is acceptable: the test verifies, the scenario
  is the spec's acceptance criterion, and `ENSURES` documents the
  postcondition the constructor guarantees — three distinct roles. The
  `RATIONALE` carries the *why* (stable identity; `MachineConnectionError`
  contrast), which neither the test nor the scenario states. Stays as proposed.

- **`CLASS_CloudCapacityExhaustedError` gets `PURPOSE` only, no `RATIONALE`.**
  The "why under `SchedulingError` and not `CloudError`" design rationale is
  already present in `MODULE_CONTRACT RATIONALE` ("Q: Why is
  `CloudCapacityExhaustedError` under `SchedulingError`, not `CloudError`?
  A: ..."). Duplicating it onto the class would be drift bait. The
  module-level Q/A is the correct home for a cross-cutting hierarchy decision;
  the class gets a `PURPOSE` that states its own WHY (allocator stops
  provisioning). Stays as proposed.

- **The `MachineBusyError` and `MachineConnectionError` message-format lines
  (`f"machine ({node_id}) is busy"`, `f"cannot connect to machine ({node_id})
  at {hostname}: {reason}"`) stay in the spec.** These are operator-facing
  stable strings parsed from logs; they are observable contracts, not
  implementation mechanics. The f-string notation is readable shorthand for the
  canonical format. The scenarios assert the rendered result. This is the same
  line the `domain-events-spec-trim` drew: wire shapes and operator-facing
  strings stay; construction-site flow and absent-code enumerations leave.

- **Trim is modest (4 prose paragraphs removed across 4 of 7 requirements).**
  This is intentional. Most of the spec was already behavioral scenarios; the
  bloat the user called out was concentrated in four specific paragraphs (the
  `TaskAlreadyAllocated` enumeration, the `MachineBusyError` `SHALL NOT
  hostname` + contrast, the `CloudCapacityExhaustedError` `SHALL NOT subclass`,
  the `CloudError` covers/capacity). Those are gone, and their rationale lands
  in code. A larger trim would require dropping message-format contracts or
  behavioral scenarios, which the proposal explicitly forbids.

### ✅ Strengths

- **Every observable behavioral scenario from the original spec survives in
  the delta.** Main spec scenario count = 23. The delta's 4 MODIFIED
  requirements carry 18; the 3 untouched requirements carry 5. 18 + 5 = 23.
  No scenario deleted, no scenario reworded destructively. The proposal's "no
  behavioral change" promise is verifiable by `rg -c '^#### Scenario:'` on the
  pre/post spec.

- **All spec prose moved out maps to a concrete code-contract destination.**
  Each piece of removed prose has a corresponding task that places it in the
  correct GRACE field:
  - "no `TaskAlreadyAllocatedError`/`TaskNotAllocatedError`" →
    `CLASS_TaskError RATIONALE` (task 1.5).
  - "`MachineBusyError` ... no `hostname`; contrast with
    `MachineConnectionError`" → `CLASS_MachineBusyError ENSURES` +
    `RATIONALE` (task 1.8) + `CLASS_MachineConnectionError RATIONALE`
    (task 1.9).
  - "`CloudCapacityExhaustedError` ... not a subclass of `CloudError`" →
    already in `MODULE_CONTRACT RATIONALE`; scenario
    `CloudCapacityExhaustedError stays under SchedulingError` is the sole
    spec assertion (no new code content needed; noted in task 1.12).
  - "`CloudError` covers operational failures; capacity NOT part" →
    `CLASS_CloudError SCOPE` (task 1.13).
  No prose is silently dropped — every line tracked to a destination.

- **Zero invented contract fields.** Audit of every region the tasks touch:
  - `CLASS_DomainError` (task 1.1): `PURPOSE` + `INVARIANTS` — both defined.
  - `CLASS_ValidationError` / `CLASS_UnsupportedEngineError` /
    `CLASS_MissingInputFileError` / `CLASS_TaskNotTodoError` /
    `CLASS_TaskNotRunningError` / `CLASS_SchedulingError` /
    `CLASS_NoCompatibleNodeError` / `CLASS_CloudCapacityExhaustedError` /
    `CLASS_CloudAllocateError` / `CLASS_CloudSetupError` (tasks 1.2–1.4, 1.6,
    1.7, 1.10–1.12, 1.14, 1.15): `PURPOSE` only — defined.
  - `CLASS_TaskError` (task 1.5): `PURPOSE` + `RATIONALE` — defined.
  - `CLASS_MachineBusyError` (task 1.8): `PURPOSE` + `ENSURES` + `RATIONALE`
    — all defined.
  - `CLASS_MachineConnectionError` (task 1.9): `PURPOSE` + `ENSURES` +
    `RATIONALE` — all defined.
  - `CLASS_CloudError` (task 1.13): `PURPOSE` + `SCOPE` — both defined.
  No `EXAMPLE` / `NOTE` / `WARNING` / `SEE` / `SHALL NOT` invented.

- **No field is misused.** `RATIONALE` entries are all Q/A format (tasks 1.5,
  1.8, 1.9 each specify the Q and the A). `INVARIANTS` (task 1.1) states
  properties that always hold (base of every domain exception; stable message;
  catchable as Exception). `ENSURES` (tasks 1.8, 1.9) states postconditions
  observable after construction (attributes stored; no `hostname` attribute;
  message format). `SCOPE` (task 1.13) states functional areas covered + `NOT:`
  for what is excluded — exactly its defined semantics. `PURPOSE` entries state
  WHY (the goal/need), not WHAT — audited per task: e.g. task 1.8
  `MachineBusyError.PURPOSE` is "stop a second task from occupying an
  already-busy machine so allocation respects the per-machine occupancy
  invariant" (WHY: so the invariant holds), not "exception raised on busy
  machine with node_id" (WHAT).

- **Every `CLASS_*` region task specifies full-block enclosure.** Tasks 1.1,
  1.3, 1.4, 1.6, 1.7, 1.8, 1.9, 1.11, 1.12 each enumerate the exact lines that
  must sit inside the region: the `class` line, the docstring, the `__init__`,
  every `self.<attr> = ...` assignment, and the `super().__init__(...)` call,
  through the trailing blank line. Task 1.16 spells out the enclosure rule and
  the "no invented fields / PURPOSE is WHY" rules as a verification step. This
  directly addresses the user's "блок должен обрамлять всё содержимое"
  constraint.

- **The placement rationale for `CloudCapacityExhaustedError` is not
  duplicated.** It lives once, in `MODULE_CONTRACT RATIONALE`, where it already
  exists. The spec paragraph that restated it is removed; no class-level
  duplicate is added. This avoids the two-sources-drift problem the proposal
  exists to fix.

- **`CloudError` docstring shortening is explicit and lossless.** Task 1.13
  shortens the multi-line docstring to a one-line brief and relocates its
  content to the `SCOPE` field, where GRACE semantics place "functional areas
  covered + NOT:". No information is lost; the docstring stops duplicating both
  the spec prose and the new `SCOPE` field.

- **All referenced test files exist.** `tests/unit/test_domain_exceptions.py`
  is present and already asserts every observable negative property the
  removed prose described (`not hasattr(exc, "hostname")`, `not issubclass(
  CloudCapacityExhaustedError, CloudError)`, `ImportError` for `CloudError`
  from `infra.cloud`). The trim cannot weaken coverage.

- **Spec delta validates cleanly.** `openspec validate domain-exceptions-
  spec-trim --json` → valid, 0 issues. The MODIFIED-Requirements headers match
  the existing main spec requirement names exactly (whitespace-insensitive):
  `TaskError hierarchy`, `MachineBusyError`, `SchedulingError hierarchy`,
  `CloudError hierarchy`. The archive step will apply correctly.

- **Follows the established precedent.** The proposal structure (Why / What
  Changes / Capabilities [Modified only, no New] / Impact / Non-Goals), the
  "markup-only, no behavioral change" framing, the tasks.md per-file grouping
  + final apply-and-verify section, and the review-log structure all mirror
  `2026-07-17-domain-events-spec-trim` row-for-row.

### Verdict: PASS

All 🔴 issues found in the round were fixed before the round closed (the
dropped `Import domain exceptions` scenario restored to the delta's
`CloudError hierarchy` block). All 🟡 suggestions are deliberate design
choices documented inline. No outstanding 🔴. The change is ready for
implementation.

The implementation phase (apply tasks 1.1 – 2.7) is the next step — separate
from this proposal/specs/tasks review. The apply-phase reviewer should
re-verify, after implementation, that: (a) every `# region CLASS_*` block in
`yascheduler/domain/exceptions.py` encloses the full class body (class line +
docstring + `__init__` + every `self.*` assignment + `super().__init__` +
trailing blank), (b) no contract field is invented, (c) every `PURPOSE` is a
WHY, (d) `openspec validate --all --json` still passes 22/22, and (e) the
scenario count in `openspec/specs/domain-exceptions/spec.md` after archive
equals the pre-change count (23).
