## Why

The `domain-exceptions` spec (187 lines, 7 requirements) interleaves observable
behavioral contracts with four content kinds that the GRACE methodology assigns
to code-local contracts, not to spec text:

1. **Negative-space regression guards framed as invented normative language** —
   "The exception SHALL NOT carry a `hostname` attribute", "`CloudCapacity-
   ExhaustedError` ... SHALL NOT be a subclass of `CloudError`", "`TaskAlread-
   yAllocatedError` and `TaskNotAllocatedError` are not part of the hierarchy".
   These are the exact "SHALL NOT" / negative-enumeration-of-absent-code
   pattern that was called out as bloat. In every case the Gherkin scenario
   already asserts the observable property (`not hasattr(exc, "hostname")`,
   `issubclass(CloudCapacityExhaustedError, CloudError)` is false); the prose
   is redundant drift bait.
2. **Design rationale living in the spec** — the `MachineBusyError` "why no
   `hostname`" paragraph (with its `MachineConnectionError` contrast), the
   `TaskError` "why no allocated/not-allocated errors" paragraph, and the
   `CloudError` "what it covers / capacity is NOT part" paragraph. These
   answer *why the code is shaped this way* — RATIONALE / SCOPE on the class
   that owns the decision, not spec text.

This duplicates what `# region` contract markup already states (or, for every
public exception class in this capability, *should* state but currently does
not — see Impact): `yascheduler/domain/exceptions.py` declares 15 public
classes under a single `MODULE_CONTRACT` and not one of them is wrapped in a
`CLASS_*` region, violating the GRACE Python rule ("if an entity is annotated
by markup, it must always be wrapped in a region").

## What Changes

- **MODIFIED `domain-exceptions`**: rewrite four of the seven requirements
  (`TaskError hierarchy`, `MachineBusyError`, `SchedulingError hierarchy`,
  `CloudError hierarchy`) to carry only behavioral contracts (requirements +
  Gherkin scenarios). Remove the invented `SHALL NOT` enumerations of absent
  attributes/classes, the negative-space "not part of the hierarchy"
  paragraph, and the design-rationale prose — these belong in code contract
  regions, not the spec. The three unchanged requirements (`DomainError base
  class`, `ValidationError hierarchy`, `MachineConnectionError`) are already
  pure observable contracts and are not touched. Every observable behavioral
  scenario (23) survives unchanged.

- Add the missing `CLASS_*` regions required by the GRACE Python rule to all
  15 public exception classes in `yascheduler/domain/exceptions.py`, and
  extend the regions with the rationale/invariants/scope that leaves the spec,
  each in its correct contract field per its defined purpose:
  - `CLASS_DomainError` — `PURPOSE` (WHY the typed root exists) +
    `INVARIANTS` (base of every domain exception; stable human-readable
    message; catchable as `Exception`).
  - `CLASS_ValidationError`, `CLASS_UnsupportedEngineError`,
    `CLASS_MissingInputFileError`, `CLASS_TaskNotTodoError`,
    `CLASS_TaskNotRunningError`, `CLASS_SchedulingError`,
    `CLASS_NoCompatibleNodeError`, `CLASS_CloudCapacityExhaustedError`,
    `CLASS_CloudAllocateError`, `CLASS_CloudSetupError` — each a `PURPOSE`
    stating WHY (so callers can branch on this failure family / surface a
    specific value), no other field.
  - `CLASS_TaskError` — `PURPOSE` + `RATIONALE` Q/A absorbing the "why no
    `TaskAlreadyAllocatedError`/`TaskNotAllocatedError`" paragraph (the
    `TO_DO→RUNNING` transition is atomic inside `task.run()`, guarded by
    `TaskNotTodoError`, so neither guard arises).
  - `CLASS_MachineBusyError` — `PURPOSE` + `ENSURES` (stores `node_id`, sets
    no `hostname` attribute, message format) + `RATIONALE` Q/A absorbing the
    "why no `hostname`" + `MachineConnectionError` contrast paragraph.
  - `CLASS_MachineConnectionError` — `PURPOSE` + `ENSURES` (stores
    `node_id`/`hostname`/`reason`, message format) + `RATIONALE` Q/A absorbing
    the "why it keeps `hostname`" half of the contrast.
  - `CLASS_CloudError` — `PURPOSE` + `SCOPE` (operational cloud-provider
    failures; `NOT:` cloud capacity planning, which lives under
    `SchedulingError`). The existing multi-line `CloudError` docstring is
    shortened to a one-line brief; its content relocates to the `SCOPE` field.
  - Each `CLASS_*` region encloses the FULL class body — the `class` line (and
    `__init__` where present, plus the docstring and all attributes) through
    the trailing blank line before the next region marker. No region closes
    before the class body ends.

- No behavioral change. No code logic change. No test change. Every observable
  scenario in the trimmed spec remains covered by the existing unit tests in
  `tests/unit/test_domain_exceptions.py` (which already assert
  `not hasattr(exc, "hostname")`, `not issubclass(CloudCapacityExhaustedError,
  CloudError)`, and the `ImportError` for `CloudError` from `infra.cloud`).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `domain-exceptions`: relocate invented `SHALL NOT` enumerations of absent
  attributes/classes and design-rationale prose out of the spec text and into
  the GRACE code contracts of `exceptions.py`. Slim four of seven requirements
  to observable behavior + acceptance scenarios. Add the missing `CLASS_*`
  regions required by the GRACE Python rule to all 15 public exception
  classes. No behavioral change; every existing scenario (23) survives
  unchanged.

## Impact

- **Specs**: `openspec/specs/domain-exceptions/spec.md` rewritten (4 of 7
  requirements trimmed). `openspec validate --all --json` must still pass
  after the change. Scenario count pre/post: 23 → 23.
- **Code (markup only, no logic)**: `yascheduler/domain/exceptions.py` — 15
  new `CLASS_*` regions (full-block enclosure per the Python rule), each with
  `PURPOSE` and per-class `INVARIANTS` / `ENSURES` / `RATIONALE` / `SCOPE` as
  specified above. `CloudError` docstring shortened. No `__init__` body, field,
  or `super().__init__` call changes.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing tests already assert them. A passing
  `uv run pytest -m unit tests/unit/test_domain_exceptions.py` run after the
  change is the regression guard.
- **Public surface**: none. No CLI, public API, INI config, DB schema, or
  log-format change in the diff. The diff is `# region`/`# endregion` markup +
  comment-field enrichment + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `domain-exceptions` spec.
  Other specs are explicitly out of scope. Follows the pattern set by
  `2026-07-17-domain-entities-spec-trim` and
  `2026-07-17-domain-events-spec-trim`.
- **Non-goals**:
  - No change to exception field types, constructor signatures, messages, or
    the hierarchy shape — the spec describes the observable behavior, the code
    defines the fields; the two already agree.
  - No spec split; all 7 requirements remain in this capability.
  - No markup added to `tests/unit/test_domain_exceptions.py` (it already
    carries a `MODULE_CONTRACT` and is out of the trim scope).
