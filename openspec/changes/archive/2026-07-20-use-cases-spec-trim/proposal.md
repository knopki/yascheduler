## Why

`openspec/specs/use-cases/spec.md` (362 lines, 7 requirements, 31 scenarios)
interleaves actual SHALL requirements with three content kinds that GRACE
assigns to code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 9 distinct
   instances in requirement bodies enumerating absent code or non-behavior as
   normative requirements:
   - `AllocateTask`: "It SHALL NOT import from `yascheduler.infra` at runtime"
     (already enforced structurally by
     `tests/unit/test_application_no_adapter_imports.py`).
   - `AllocateTask`: "It SHALL NOT accept `adapters` or `configs` parameters —
     provider selection is delegated to the `clouds.select_provider` port
     method" (the positive shape — provider selection via
     `clouds.select_provider` — is already the observable scenario).
   - `DeallocateIdleNodes`: "It SHALL NOT accept `repository` or `operations`
     (the per-node teardown lives in a separate helper)" (the per-node teardown
     helper `deallocate_node` is a separate top-level function — already
     obvious from the code surface).
   - `AbandonNode`: "It SHALL NOT import from `yascheduler.infra` at runtime
     (TYPE_CHECKING only)" (enforced by
     `tests/unit/test_application_no_adapter_imports.py`).
   - `AbandonNode`: "The use case SHALL NOT call `repository.disconnect` — by
     construction the node was never registered in the repository" (the
     why-it-doesn't is the valuable part and belongs in `RATIONALE`, not as a
     normative SHALL NOT).
   - `AbandonNode`: "The use case SHALL NOT mark the task `FAILED` or emit a
     domain event" (negative space; observable scenario already proves the
     happy path returns without raising and without status mutation).
   - `AbandonNode`: "The use case SHALL NOT modify `node.enabled` or call
     `uow.nodes.disable` — the row is removed directly" (same pattern).
   - `ConsumeTask`: "It SHALL NOT import SFTP retry or backoff infrastructure
     from `yascheduler.infra` at runtime" (enforced by
     `tests/unit/test_application_no_adapter_imports.py`).
   - `QueryTasks`: "It SHALL NOT call `uow.commit` (read-only)" + "It SHALL
     NOT import from `yascheduler.infra` at runtime" (the read-only property
     is already an observable scenario; the import hygiene is already enforced
     by `tests/unit/test_application_no_adapter_imports.py`).
   Every one is either already asserted by a positive scenario / static guard
   test or describes a non-existent code path dressed up as a normative
   requirement. The prose is drift bait.
2. **Design rationale and implementation narrative living in the spec** — the
   `SubmitTask` typed-field routing explanation (every key in caller
   `metadata` that is not one of six known typed fields goes into `extra`),
   the `AllocateTask` cloud-fallback critical-section narrative, the
   `DeallocateIdleNodes` disable-before-delete + remove-after-delete ordering
   rationale, the `AbandonNode` 4-step flow narrative (including the
   `ON DELETE SET NULL` FK explanation and the in-memory task-lookup-then-
   `discard(task_id)` recipe), the `ConsumeTask` transient-vs-permanent
   priority rule and the `"Download error: <path>: <msg>, ..."` format
   contract, the `QueryTasks` `int`/`TaskId` facade-boundary prose (which
   belongs in `package-facades`), and the `AllocationTracker`
   internal-to-orchestrator aside. These answer *why the code is shaped this
   way* or *how the code is sequenced* — they belong in `RATIONALE` /
   `INVARIANTS` / `SCOPE` on the owning entity, not in spec.
3. **One stale spec vs. code contradiction** — the `AbandonNode` requirement
   body describes a 4-step flow culminating in a TO_DO task lookup followed by
   conditional `tracker.discard(task.task_id)`; the actual
   `yascheduler/application/abandon_node.py` performs no `uow.tasks` read at
   all and unconditionally calls `tracker.discard_by_node(node.node_id)` (the
   task naturally re-allocates on the next cycle because
   `allocated_node_id` FK is `ON DELETE SET NULL`). The
   `tests/unit/test_abandon_node.py` docstring confirms: "The DB read
   (`list_by_status`) is no longer used by `abandon_node`". The spec scenario
   "No matching TO_DO task skips tracker discard" therefore asserts a
   behavior the code does not implement; the corresponding test
   (`test_abandon_node_no_matching_tracker_entry_no_discard`) instead asserts
   "`discard_by_node` returns 0 → no warning logged". The spec is stale from
   the `2026-07-10-fix-tracker-node-link-leak` refactor.

In parallel, the code under `yascheduler/application/` is well-marked-up at
the entity level (every public function and the `AllocationTracker` class
already carry a `FUNC_*` / `CLASS_*` region with a WHY-shaped `PURPOSE`), but
the `INVARIANTS` / `RATIONALE` / `ENSURES` fields that should accompany the
code is missing on most regions because that content currently sits in the
spec. The trim relocates the spec's rationale and invariant content into the
correct GRACE fields on the regions that already wrap the entities.

## What Changes

- **MODIFIED `use-cases`**: rewrite all 7 requirements to carry only
  behavioral contracts (SHALL statements + Gherkin scenarios). Remove the 9
  invented `SHALL NOT` enumerations of absent code, the implementation-
  narrative paragraphs (typed-field routing, cloud-fallback sequencing,
  disable-before-delete ordering, abandon 4-step flow, transient-vs-permanent
  priority, facade-boundary int/TaskId prose, internal-to-orchestrator
  aside), and the stale `AbandonNode` 4-step flow narrative. Every observable
  behavioral scenario that matches code survives; the one stale scenario
  ("No matching TO_DO task skips tracker discard") is replaced by accurate
  scenarios reflecting the actual `discard_by_node` behavior. One missing
  observable scenario is added (`AllocateTask` empty-platforms short-circuit,
  already tested in `test_allocate_task_failure_modes.py`). Pre/post
  scenario count: 31 → 34 (drop 1 stale, add 1 missing AllocateTask
  short-circuit, add 3 accurate AbandonNode scenarios). No requirement is
  added, removed, merged, or split; the 7 requirement headers stay identical
  so OpenSpec recognizes the MODIFIED operation.
- Enrich existing `MODULE_CONTRACT`, `FUNC_*`, `CLASS_*`, and `METHOD_*`
  regions on
  `yascheduler/application/{submit_task,allocate_task,consume_task,
  deallocate_nodes,abandon_node,query_tasks,allocation_tracker}.py` with the
  `INVARIANTS` / `RATIONALE` / `ENSURES` / `SCOPE` content that leaves the
  spec, each in its correct GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
    The existing `PURPOSE` fields already answer WHY — keep them, do not
    regress to WHAT.
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
    `FUNC_submit_task` constructs `NewTask` without `task_id` / `remote_folder`
    / `error`; `FUNC_allocate_task` imports `yascheduler.infra` only under
    `TYPE_CHECKING`; `FUNC_abandon_node` never calls `repository.disconnect`;
    `FUNC_consume_task` imports SFTP/backoff infrastructure only under
    `TYPE_CHECKING`; `FUNC_query_tasks` is read-only — no `uow.commit`).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why every non-typed key in caller `metadata` is routed to `extra`; why
    `abandon_node` uses `discard_by_node` instead of a task lookup; why
    permanent errors take priority over transient errors in
    `_decide_finalisation`; why the disable+remove bracket protects the
    allocator in `deallocate_node`).
  - `ENSURES` carries postconditions (e.g. `FUNC__format_download_error`
    format contract; `FUNC_allocate_task` return-value semantics).
  - `SCOPE` declares the entity's functional boundaries with explicit `NOT:`
    exclusion where useful (e.g. `FUNC_query_tasks` does NOT project a nested
    `node` field — that is the facade's responsibility).
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  free-form labels. The spec's removed `SHALL NOT` sentences do NOT become a
  `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating the
  positive contract, or a `RATIONALE` Q/A if the rationale is the valuable
  part.
- Every existing `CLASS_*` / `FUNC_*` / `METHOD_*` region continues to
  enclose the FULL entity per the GRACE Python rule (this is already the
  case in the touched files; the change makes no structural region changes,
  only enriches the contract comment block inside the existing region
  between `PURPOSE` and the `def`/`class` line). No new regions are added —
  every public function and the `AllocationTracker` class already carry a
  wrapping region.
- Comment-only diff on the code side. No code logic, signature, decorator,
  docstring semantics, or import changes. Edits are contract-field
  enrichment inside existing marker blocks.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `use-cases`: requirements slimmed to SHALL statements and behavior
  scenarios; invented `SHALL NOT` negative-space language (9 instances),
  implementation-narrative paragraphs, the `int`/`TaskId` facade-boundary
  prose, and the stale `AbandonNode` 4-step flow / `discard(task_id)` recipe
  relocated out of the spec text and into GRACE code contracts across
  `yascheduler/application/*.py`. One stale scenario
  ("No matching TO_DO task skips tracker discard") is replaced by accurate
  `discard_by_node`-based scenarios. One missing observable scenario
  (`AllocateTask` empty-platforms short-circuit) is added. No use-case
  behavior, signature, scenario acceptance criteria (other than the stale
  one), public API, INI key, DB schema, or import path is added, removed, or
  changed.

## Impact

- **Specs**: `openspec/specs/use-cases/spec.md` rewritten — every requirement
  trimmed to behavioral SHALL + scenarios; pre/post scenario count compared
  and MUST remain documented (pre 31 → post 34; drop 1 stale, add 1 missing
  AllocateTask short-circuit, add 3 accurate AbandonNode scenarios). `openspec
  validate --all --json` must still pass after the change.
- **Code (markup only, no logic)**:
  `yascheduler/application/submit_task.py`,
  `allocate_task.py`,
  `consume_task.py`,
  `deallocate_nodes.py`,
  `abandon_node.py`,
  `query_tasks.py`,
  `allocation_tracker.py` — existing `MODULE_CONTRACT`, `FUNC_*`,
  `CLASS_AllocationTracker`, and the two `METHOD_*` regions on
  `AllocationTracker` enriched with `INVARIANTS` / `RATIONALE` / `ENSURES` /
  `SCOPE`. No code logic, signature, decorator, docstring semantics, or
  import changes. Code contracts absorb what leaves the spec, comment-only
  diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing application unit tests already assert them
  (including the `discard_by_node` behavior and the empty-platforms
  short-circuit). A passing `uv run pytest -m unit` run after the change is
  the regression guard. The `test_abandon_node_no_matching_tracker_entry_-
  no_discard` test already asserts the actual behavior (`discard_by_node`
  returns 0 → no warning, no raise) rather than the stale spec text.
- **Public surface**: none. No CLI command, console_script, INI config key,
  DB schema, public API, or log-format change in the diff. The diff is
  `# region`/`# endregion` contract-field enrichment + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `use-cases` spec. Other
  specs (`orchestrator` is handled by `orchestrator-spec-trim`; `cloud` by
  `cloud-spec-trim`; `cli` by the in-flight `cli-spec-trim`; `package-facades`
  by `package-facades-spec-trim`; etc.) are explicitly out of scope. Follows
  the pattern set by
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, `cloud-spec-trim`, `cli-spec-trim`,
  and the in-flight `orchestrator-spec-trim`.
- **Non-goals**:
  - No change to any use-case behavior, signature, scenario acceptance
    criteria (other than the one stale `AbandonNode` scenario being replaced
    by accurate ones), public API, INI key, DB schema, log marker, or import
    path.
  - No spec split; all 7 trimmed requirements remain in the `use-cases`
    capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No structural region changes — every public function and the
    `AllocationTracker` class already carry a wrapping region; only contract
    fields inside those regions are enriched.
  - No rewrite of `yascheduler/application/orchestrator.py`,
    `message_bus.py`, `queue.py`, or `uow.py` — those files are out of
    capability scope.
