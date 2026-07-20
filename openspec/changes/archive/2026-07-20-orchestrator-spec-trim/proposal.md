## Why

`openspec/specs/orchestrator/spec.md` (284 lines, 11 requirements, 34 scenarios)
interleaves actual SHALL requirements with content kinds that GRACE assigns to
code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 4 distinct
   instances in requirement bodies and scenario THEN clauses enumerating absent
   code or non-behavior as normative requirements:
   - Requirement body: "the orchestrator SHALL NOT read `clouds.configs` or
     hold `adapters`/`configs` dicts" (provider selection is already delegated
     to `clouds.select_provider`; the negative space restates the absence).
   - Scenario THEN: "never touches `get_sftp`, `get_path`, or `get_quote`
     directly, never keys a session lookup by `ip`" (the deployer boundary is
     already asserted by the positive `task_deployer.start_task_on_machine(...)`
     call shape).
   - Scenario THEN: "no `log=` keyword argument is passed" (already enforced by
     the static guard test `tests/unit/test_log_scope_discipline.py`).
   - Requirement body: "The consumer SHALL NOT perform its own SSH teardown —
     teardown is owned by `deallocate_node`" (the teardown-ownership contract
     already lives in `FUNC_deallocate_node` REQUIRES in
     `deallocate_nodes.py`).
   Every one is either already asserted by a positive scenario / static guard
   test or describes a non-existent code path dressed up as a normative
   requirement. The prose is drift bait.
2. **Design rationale living in the spec** — the "The composition root passes
   `local_settings=` and `remote_defaults=` keyword arguments (not a `Config`
   aggregate)" framing (answers *why the constructor shape is unpacked settings
   vs a Config aggregate*), and the "All connection identity comes from the
   `Node` itself; `repository.connect` reads `node.jump_host` /
   `node.jump_port` / `node.jump_username` directly" aside (a layering
   invariant that is already present verbatim in
   `METHOD_connect_machine_consumer` INVARIANTS in `orchestrator.py`). These
   answer *why the code is shaped this way* — they belong in `RATIONALE` /
   `INVARIANTS` on the owning entity, not in spec.
3. **Duplicated layering rule** — "The gate SHALL live in the use case, not in
   `MachineRepository`" restates the architectural rationale already present in
   `FUNC__find_free_machines` RATIONALE and `FUNC_allocate_task` RATIONALE in
   `allocate_task.py` ("`MachineRepository` is an infrastructure-layer
   SSH-collection port that SHALL NOT be coupled to `NodeRepository`; joining
   the two data sources is the use case's responsibility").

In parallel, `yascheduler/application/orchestrator.py` has two non-trivial
private helpers that are currently unwrapped under the `MODULE_CONTRACT` and
the enclosing `CLASS_Orchestrator` region — `_connect_grace_for` (prefix →
`connect_grace` lookup with a 120 s default) and `_allocator_producer` (cloud
capacity + free-machine count → dynamic TO_DO task limit). The GRACE Python
rule ("if an entity is annotated by markup, it must always be wrapped in a
region") requires them to carry their own `METHOD_*` region. Where regions
exist (`CLASS_Orchestrator`, `METHOD_start_task_on_machine`,
`METHOD_deallocator_consumer`), they hold `PURPOSE` only — the INVARIANTS /
RATIONALE that should accompany the code is missing because the corresponding
content currently sits in the spec.

## What Changes

- **MODIFIED `orchestrator`**: rewrite all 11 requirements to carry only
  behavioral contracts (SHALL statements + Gherkin scenarios). Remove the 4
  invented `SHALL NOT` enumerations of absent code listed above, the
  composition-root "not a `Config` aggregate" rationale, the duplicated "All
  connection identity comes from the `Node`" invariant (already in code), and
  the duplicated "gate lives in the use case" layering rule (already in code).
  Every observable behavioral scenario (34) survives (two THEN clauses shed
  their trailing negative-space tail; the remaining 32 scenarios are
  unchanged). No requirement is added, removed, merged, or split; the 11
  requirement headers stay identical so OpenSpec recognizes the MODIFIED
  operation.
- Wrap the 2 currently-unwrapped non-trivial private methods on
  `CLASS_Orchestrator` required by the GRACE Python rule: `_connect_grace_for`
  (prefix → grace lookup) and `_allocator_producer` (cloud capacity → TO_DO
  limit). The trivial `_shutdown_barrier` one-liner is skipped per the GRACE
  proportional rule.
- Enrich existing `CLASS_Orchestrator`, `METHOD_start_task_on_machine`, and
  `METHOD_deallocator_consumer` regions with the INVARIANTS / RATIONALE that
  leaves the spec, each in its correct GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
    `CLASS_Orchestrator` never accepts a `log=` parameter, never accepts a
    `Config` aggregate, never reads `clouds.configs`, never holds
    `adapters`/`configs` dicts; `METHOD_start_task_on_machine` never touches
    `get_sftp`/`get_path`/`get_quote` directly and never keys a session lookup
    by `ip`; `METHOD_deallocator_consumer` never calls
    `repository.contains`/`repository.disconnect` directly — SSH teardown is
    owned by `deallocate_node`).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why the constructor takes `local_settings=` + `remote_defaults=` keyword
    arguments instead of a `Config` aggregate: `Config` is a composition-root
    aggregate owned by `yascheduler.entrypoints`; `LocalSettings` and
    `RemoteDefaults` are the application-layer projections).
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  free-form labels. The spec's removed `SHALL NOT` sentences do NOT become a
  `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating the
  positive contract, or a `RATIONALE` Q/A if the rationale is the valuable
  part.
- Every `CLASS_*` region encloses the FULL class body — the `class` line, the
  docstring, every field, every `__init__` line, every `self.<attr>`
  assignment, every nested `METHOD_*` / `BLOCK_*` region — through the
  trailing blank line before the next region marker. Every `METHOD_*` /
  `FUNC_*` region encloses the decorator (if any), the `def`/`async def` line,
  the body, every nested `BLOCK_*` region, and the trailing blank line. No
  region closes before its entity ends; nested `METHOD_*` / `BLOCK_*` regions
  live INSIDE their enclosing `CLASS_*`; the `CLASS_*` `# endregion` comes
  after the last nested `# endregion`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `orchestrator`: requirements slimmed to SHALL statements and behavior
  scenarios; invented `SHALL NOT` negative-space language (4 instances),
  composition-root constructor-shape rationale, the duplicated "all connection
  identity from the Node" invariant, and the duplicated "gate lives in the use
  case" layering rule relocated out of the spec text and into GRACE code
  contracts on `yascheduler/application/orchestrator.py`. No orchestrator
  behavior, signature, scenario, INI key, DB schema, public API, log format,
  or import path is added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/orchestrator/spec.md` rewritten — every
  requirement trimmed to behavioral SHALL + scenarios; pre/post scenario
  count compared and MUST remain 34 → 34 (2 scenarios shed trailing
  negative-space tails in their THEN clauses; the scenario headers, WHEN
  clauses, and positive observable assertions are unchanged). `openspec
  validate --all --json` must still pass after the change.
- **Code (markup only, no logic)**:
  `yascheduler/application/orchestrator.py` — existing `MODULE_CONTRACT`,
  `CLASS_Orchestrator`, `METHOD_start_task_on_machine`, and
  `METHOD_deallocator_consumer` regions enriched with `INVARIANTS` /
  `RATIONALE`; new `METHOD__connect_grace_for` and `METHOD__allocator_producer`
  regions added for the 2 currently-unwrapped non-trivial private helpers.
  No code logic, signature, decorator, docstring semantics, or import
  changes. Code contracts absorb what leaves the spec, comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing orchestrator unit tests
  (`tests/unit/test_application_orchestrator.py`,
  `test_orchestrator_start_task_on_machine.py`,
  `test_orchestrator_consumer_resilience.py`,
  `test_orchestrator_producer_resilience.py`,
  `test_orchestrator_stop_idempotent.py`,
  `test_connect_machine_consumer.py`,
  `test_connect_grace.py`,
  `test_application_no_adapter_imports.py`,
  `test_log_scope_discipline.py`,
  `test_di_no_casts.py`,
  `test_allocate_task_node_pairing.py`,
  `test_allocate_task_failure_modes.py`,
  `test_consume_task.py`,
  `test_abandon_node.py`) already assert them. A passing
  `uv run pytest -m unit` run after the change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config key,
  DB schema, public API, or log-format change in the diff. The diff is
  `# region`/`# endregion` markup + comment-field enrichment + spec text trim
  only.
- **Pilot scope**: this change ONLY dehydrates the `orchestrator` spec. Other
  specs (`cloud` is handled by `cloud-spec-trim`; `cli` by `cli-spec-trim`;
  `use-cases`, `ssh-infrastructure`, etc.) are explicitly out of scope.
  Follows the pattern set by
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, `cloud-spec-trim`, and `cli-spec-trim`.
- **Non-goals**:
  - No change to any orchestrator behavior, loop scheduling, queue dedup key,
    concurrency limit, log marker, sleep interval, exception-handling order,
    or shutdown drain sequence.
  - No spec split; all trimmed requirements remain in the `orchestrator`
    capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No rewrite of `yascheduler/application/allocate_task.py`,
    `consume_task.py`, `deallocate_nodes.py`, or `abandon_node.py` — those
    files already carry the `INVARIANTS` / `RATIONALE` / `REQUIRES` that
    absorbs the spec's layering and ownership prose. Only
    `orchestrator.py` and the `orchestrator` capability spec are touched.
  - No markup additions to non-orchestrator regions of the application layer
    (`message_bus.py`, `queue.py`, `submit_task.py`, `query_tasks.py`,
    `allocation_tracker.py`, `uow.py` are out of capability scope).
