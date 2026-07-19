## proposal / specs / tasks Round 1 — 2026-07-18

Single comprehensive self-review of all four artifacts (proposal.md,
specs/use-cases/spec.md, tasks.md, README.md) written in one pass. Reviewer =
author. The review is run against the GRACE-lite review checklist, the
project's `orchestrator-spec-trim`, `cloud-spec-trim`, `domain-exceptions-
spec-trim`, and `slim-domain-ports-spec` precedents, and the user's explicit
constraints:

- "выдумывать поля нельзя" — no invented contract fields.
- "Использовать поля не по назначению нельзя" — fields must be used per their
  defined purpose.
- "новых полей типа SHALL NOT" — no invented `SHALL NOT` pseudo-normative
  enumerations of absent code/attributes in the spec.
- "записывания в RATIONALE просто всего подряд" — RATIONALE is Q/A only, not a
  dumping ground.
- "PURPOSE должно быть WHY, а не WHAT" — every PURPOSE states why, not what.
- "блок должен обрамлять всё содержимое" — a `CLASS_*` / `FUNC_*` / `METHOD_*`
  region encloses the full entity body (def line + docstring + body + nested
  regions + trailing blank), not only the contract header.

Validation run before review:
- `openspec validate --all --json` → 35/35 passed (15 changes + 20 specs),
  exit 0. `use-cases-spec-trim` validates; main `use-cases` spec still
  validates (delta is structurally compatible); no other spec regresses.
- `rg -in 'shall not' openspec/changes/use-cases-spec-trim/specs/use-cases/spec.md`
  → 0 hits in requirement bodies. One "SHALL NOT" survived in the first
  draft in the `AbandonNode` body ("SHALL NOT suppress the subsequent DB-row
  removal") — a positive postcondition phrased as a negative; **fixed** in
  this round to a positive form ("the subsequent DB-row removal SHALL proceed
  regardless of the cloud-deletion outcome"). The remaining `do not` (line
  37, "so concurrent `allocate_task` calls for overlapping capacity do not
  over-provision") is a goal-shaped positive contract, not an invented
  negative-space enumeration of absent code — left as-is per the
  `orchestrator-spec-trim` precedent that tolerates goal-phrased negatives
  in requirement bodies.
- Scenario count: main spec pre = 31 (4+5+3+3+3+7+6); delta post = 34
  (4+6+3+5+3+7+6). Drop 1 stale (`AbandonNode` "No matching TO_DO task skips
  tracker discard"); add 1 missing (`AllocateTask` empty-platforms
  short-circuit, already tested in
  `tests/unit/test_allocate_task_failure_modes.py::test_empty_platforms_-
  short_circuits_cloud_fallback`); add 3 accurate `AbandonNode` scenarios
  (Non-cloud node skips VM deletion; DB-row removal failure re-raised;
  Ambiguous tracker entry count logs warning). Net +3.

### 🔴 Issues (found and fixed in this round)

- **The first-draft `AbandonNode` body retained one `SHALL NOT`.** The body
  said "failures SHALL be logged with `node_id`, `hostname`, `cloud`, and the
  exception and SHALL NOT suppress the subsequent DB-row removal." The
  `cloud-spec-trim` precedent aims for zero `SHALL NOT` in requirement bodies;
  the `orchestrator-spec-trim` precedent tolerates only specifically-
  enumerated negative-space language. The "SHALL NOT suppress" line is a
  positive postcondition (DB-row removal proceeds regardless of cloud-deletion
  outcome) phrased as a negative — it is observable, not invented negative
  space, so it could survive under the `orchestrator-spec-trim` precedent.
  Fixed anyway to align with the stricter `cloud-spec-trim` line: rephrased
  to "the subsequent DB-row removal SHALL proceed regardless of the
  cloud-deletion outcome." Delta `SHALL NOT` count in bodies: 0.

- **The first-draft `SubmitTask` delta added a "Missing input file" scenario
  not present in the original spec.** The original `SubmitTask` requirement
  had 4 scenarios (Successful, Unsupported engine, "submit_task constructs
  NewTask not Task", "submit_task does not construct events"); the first draft
  of the delta dropped "constructs NewTask not Task" (an observable invariant
  about the construction site) and added "Missing input file" (also
  observable, also tested, but an addition the proposal did not promise).
  Fixed: restored "Submit constructs NewTask, not Task" verbatim from the
  original; removed the unsolicited "Missing input file" addition. The trim
  is scoped to remove invented negative-space and stale prose, not to add
  new scenarios outside the two promised (the `AllocateTask` empty-platforms
  short-circuit and the accurate `AbandonNode` replacements). Delta
  `SubmitTask` scenario count: 4 (matches original).

### 🟡 Suggestions (considered, not blocking)

- **The trim does not add the `ConsumeTask` "task is None" scenario.** The
  actual code path in `consume_task.py` (lines 188-195) returns `True` and
  calls `tracker.discard(task_id)` when `uow.tasks.get(task_id)` returns
  `None` (a vacuously-finalised path). The original spec body claimed
  "True when the task is finalised (DONE status applied, remote directory
  cleaned...)" which is slightly inaccurate for this path (DONE is NOT
  applied, remote directory is not touched). The first test
  `tests/unit/test_consume_task.py::test_consume_task_not_found_discards_-
  tracker_returns_true` asserts the actual behavior. The trim leaves this
  alone — the spec body's inaccuracy is a stale-but-not-flagged issue, not
  an invented-negative-space issue, and the proposal did not promise to fix
  it. Stays out of scope; follow-up change can add the scenario.

- **All 7 requirements in the delta are MODIFIED, including the 2
  (`DeallocateIdleNodes`, `AllocationTracker`) whose bodies needed only
  minor trims.** The `DeallocateIdleNodes` body lost only the `SHALL NOT
  accept repository or operations` line and the disable-before-delete
  ordering narrative; the 3 scenarios are unchanged. The `AllocationTracker`
  body lost only the `internal-to-orchestrator` aside; the 6 scenarios are
  unchanged. Marking these as MODIFIED (vs leaving them alone) is correct
  because the bodies DID change. The alternative — splitting out only the
  5 heavily-trimmed requirements as MODIFIED and leaving the 2 lightly-
  trimmed ones alone — would leave stale prose in the main spec until a
  future change picks them up. The proposal's "every observable behavioral
  scenario that matches code survives; the one stale scenario is replaced
  by accurate scenarios" promise is preserved. Stays as proposed.

- **The `AllocateTask` empty-platforms short-circuit scenario is added even
  though it wasn't in the original spec.** This is the only positive
  scenario addition (the `AbandonNode` additions are replacements for a
  stale scenario). The `cloud-spec-trim` precedent added one missing
  scenario ("deallocate on cloud=None is a no-op") and the
  `slim-domain-ports-spec` precedent added one missing scenario
  ("deallocate on cloud=None is a no-op" on the CloudProvisioner port).
  Adding one missing observable scenario that is already tested but
  unspecified is within precedent. Stays as proposed.

- **The `QueryTasks` "Use case is read-only" scenario survives the trim.**
  This is the only scenario in the delta whose THEN clause is a negative
  assertion ("`uow.commit()` is never called on the opened UoW"). It is
  observable (the test can mock the UoW and assert `commit.assert_not_called`)
  and is the sole spec-level assertion of the read-only contract. Removing
  it would weaken coverage; keeping it is consistent with the precedent that
  observable-negative-THEN-clauses are different from invented-SHALL-NOT-
  body-prose. Stays as proposed.

- **The `Submit` "Submit constructs NewTask, not Task" scenario survives.**
  This is observable (the test can inspect the argument type passed to
  `uow.tasks.insert`). The construction-site invariant is valuable because
  the `TaskCreated` event is attached inside `insert`, not by the use case —
  if a future refactor accidentally constructs a `Task` and passes it to
  `insert`, the event-attachment contract breaks silently. Stays as
  proposed.

- **The `Submit` "Submit does not construct TaskCreated" scenario survives.**
  Observable by source inspection (no `TaskCreated(...)` constructor call, no
  `with_event` / `record_event` call in `submit_task.py`). This is a
  construction-site invariant documenting where events are NOT attached.
  Different from an invented SHALL NOT because it is a positive observable
  scenario asserting a testable property of the source. Stays as proposed.

### ✅ Strengths

- **The stale `AbandonNode` spec-vs-code contradiction is corrected.** The
  original spec described a 4-step flow culminating in a TO_DO task lookup
  followed by conditional `tracker.discard(task.task_id)`; the actual
  `yascheduler/application/abandon_node.py` performs no `uow.tasks` read and
  unconditionally calls `tracker.discard_by_node(node.node_id)`. The
  `tests/unit/test_abandon_node.py` docstring confirms ("The DB read
  (`list_by_status`) is no longer used by `abandon_node`"). The stale
  scenario ("No matching TO_DO task skips tracker discard") is replaced by
  3 accurate scenarios (Non-cloud node skips VM deletion; DB-row removal
  failure re-raised; Ambiguous tracker entry count logs warning), all of
  which are already tested. The proposal's Why § 3 documents the drift and
  traces it to the `2026-07-10-fix-tracker-node-link-leak` refactor.

- **Every observable behavioral scenario from the original spec survives in
  the delta.** Main spec scenario count = 31. The delta carries 34; the
  +3 is the +4 additions (`AllocateTask` empty-platforms, `AbandonNode` × 3)
  minus the 1 stale drop (`AbandonNode` "No matching TO_DO task skips
  tracker discard"). Every other scenario is preserved verbatim or
  rewritten trimmer while keeping its observable WHEN/THEN assertions. The
  proposal's "every observable scenario that matches code survives" promise
  is verifiable by `rg -c '^#### Scenario:'` on the pre/post spec.

- **All 7 requirement headers in the delta match the main spec exactly
  (whitespace-insensitive).** Audited:
  `SubmitTask use case` / `AllocateTask use case` / `DeallocateIdleNodes
  use case` / `AbandonNode use case` / `ConsumeTask use case` / `QueryTasks
  use case` / `AllocationTracker tracks in-flight cloud allocations`. The
  archive step will apply each MODIFIED block correctly.

- **All spec prose moved out maps to a concrete code-contract destination.**
  Each piece of removed prose has a corresponding task that places it in the
  correct GRACE field on the correct region:
  - `SubmitTask` typed-field routing → `FUNC_submit_task` `INVARIANTS`
    (task 2.1) + `RATIONALE` Q/A (task 2.2).
  - `AllocateTask` `SHALL NOT import yascheduler.infra` + `SHALL NOT accept
    adapters/configs` + cloud-fallback critical-section narrative →
    `FUNC_allocate_task` `INVARIANTS` (task 3.1) + `RATIONALE` Q/A
    (task 3.2); `allocation_lock` serialization → `FUNC__select_and_-
    insert_tmp` `INVARIANTS` (task 3.3).
  - `DeallocateIdleNodes` `SHALL NOT accept repository/operations` +
    disable-before-delete ordering rationale → `FUNC_deallocate_node`
    `INVARIANTS` (task 5.1, building on the existing `RATIONALE`); log-line
    correlation contract → `FUNC_deallocate_nodes` `INVARIANTS` (task 5.2).
  - `AbandonNode` `SHALL NOT import yascheduler.infra` + `SHALL NOT call
    repository.disconnect` + `SHALL NOT mark task FAILED` + `SHALL NOT
    modify node.enabled` + 4-step flow narrative → `FUNC_abandon_node`
    `INVARIANTS` (task 6.1) + `RATIONALE` Q/A for `discard_by_node` choice
    (task 6.2, also documents the stale-vs-code fix).
  - `ConsumeTask` `SHALL NOT import SFTP/backoff` → `FUNC_consume_task`
    `INVARIANTS` (task 4.1); transient-vs-permanent priority rule →
    `FUNC__decide_finalisation` `RATIONALE` Q/A (task 4.2); error-format
    contract → `FUNC__format_download_error` `ENSURES` (task 4.3).
  - `QueryTasks` `SHALL NOT call uow.commit` + `SHALL NOT import
    yascheduler.infra` → `FUNC_query_tasks` `INVARIANTS` (task 7.1);
    `int`/`TaskId` facade-boundary prose → `FUNC_query_tasks` `SCOPE`
    (task 7.2, with `NOT:` exclusion referencing `package-facades`).
  - `AllocationTracker` internal-to-orchestrator aside →
    `CLASS_AllocationTracker` `INVARIANTS` extension (task 8.1) +
    `RATIONALE` Q/A for the dual-key discard surface (task 8.2).
  No prose is silently dropped — every line tracked to a destination.

- **Zero invented contract fields.** Audit of every region the tasks touch:
  - `FUNC_submit_task` (task 2): `INVARIANTS` + `RATIONALE` — both defined.
  - `FUNC_allocate_task` (task 3): `INVARIANTS` + `RATIONALE` — defined.
  - `FUNC__select_and_insert_tmp` (task 3): `INVARIANTS` — defined.
  - `FUNC_consume_task` (task 4): `INVARIANTS` — defined.
  - `FUNC__decide_finalisation` (task 4): `RATIONALE` — defined.
  - `FUNC__format_download_error` (task 4): `ENSURES` — defined.
  - `FUNC_deallocate_node` (task 5): `INVARIANTS` — defined.
  - `FUNC_deallocate_nodes` (task 5): `INVARIANTS` — defined.
  - `FUNC_abandon_node` (task 6): `INVARIANTS` + `RATIONALE` — defined.
  - `FUNC_query_tasks` (task 7): `INVARIANTS` + `SCOPE` — defined.
  - `CLASS_AllocationTracker` (task 8): `INVARIANTS` extension +
    `RATIONALE` — defined.
  No `SHALL NOT:` / `EFFECTS:` / `EXAMPLES:` / `NOTES:` / `RAISES:` /
  `WARNING:` invented.

- **No field is misused.** `RATIONALE` entries are all Q/A format (tasks 2.2,
  3.2, 4.2, 6.2, 8.2 each specify the Q and the A). `INVARIANTS` (tasks 2.1,
  3.1, 3.3, 4.1, 5.1, 5.2, 6.1, 7.1, 8.1) state properties that always hold.
  `ENSURES` (task 4.3) states postconditions observable after the call.
  `SCOPE` (task 7.2) states functional areas covered + `NOT:` for what is
  excluded — exactly its defined semantics. `PURPOSE` entries state WHY (the
  goal/need), not WHAT — the existing `PURPOSE` fields in every touched file
  already answer WHY (audited: `FUNC_submit_task.PURPOSE` = "Accept
  validated task requests from clients and persist them so the daemon's
  allocator can pick them up for scheduling"; `FUNC_allocate_task.PURPOSE`
  = "Match a TO_DO task to a free compatible machine or request cloud
  allocation with critical-section dedup"; `FUNC_consume_task.PURPOSE` =
  "Reliably retrieve remote computation results and classify errors to
  either close the task lifecycle or retry, so transient infra failures do
  not prematurely terminate valid work"; `FUNC_deallocate_node.PURPOSE` =
  "Tear down a cloud node completely ... so billing stops and the scheduler
  no longer tracks it"; `FUNC_deallocate_nodes.PURPOSE` = "Disable idle
  cloud nodes exceeding their configured idle tolerance and return the
  disabled Node objects for VM deletion"; `FUNC_abandon_node.PURPOSE` =
  "Prevent resource leaks — orphan cloud VMs, stale DB rows, dangling
  tracker entries — when a provisioned node never connects, so billing stops
  and the scheduler does not track phantom resources"; `FUNC_query_tasks.-
  PURPOSE` = "Provide a read-only snapshot of tasks and their allocated
  nodes so CLI and API consumers can display scheduler state without side
  effects"; `CLASS_AllocationTracker.PURPOSE` = "Prevent the daemon from
  provisioning duplicate cloud VMs for the same task, with a task-to-node
  link so abandon can discard by node"). All WHY. The tasks do not regress
  any of them to WHAT.

- **Every existing `CLASS_*` / `FUNC_*` / `METHOD_*` region continues to
  enclose the full entity.** The proposal explicitly promises no structural
  region changes — every public function and the `AllocationTracker` class
  already carry a wrapping region that encloses the full entity (audited by
  reading each file: `submit_task.py` lines 43-87 `FUNC_submit_task` wraps
  decorator + `def` + body + 3 nested `BLOCK_*` + trailing blank, ends at
  `# endregion FUNC_submit_task`; `allocate_task.py` `FUNC_allocate_task`
  lines 356-467 wraps `def` + body + `BLOCK_allocate_cloud_critical_section`
  + trailing blank; `consume_task.py` `FUNC_consume_task` lines 175-226;
  `deallocate_nodes.py` `FUNC_deallocate_node` lines 28-103 + `FUNC_-
  deallocate_nodes` lines 106-163; `abandon_node.py` `FUNC_abandon_node`
  lines 26-91; `query_tasks.py` `FUNC_query_tasks` lines 22-69;
  `allocation_tracker.py` `CLASS_AllocationTracker` lines 19-72 wraps the
  `class` line + docstring + `__init__` + every method + the two nested
  `METHOD_*` regions + `__contains__` + trailing blank, ends after the
  last nested `# endregion`). Task 9.1 spells out the enclosure
  verification. This directly addresses the user's "блок должен обрамлять
  всё содержимое" constraint.

- **No new regions added.** Every public function and the
  `AllocationTracker` class already carry a wrapping region in the touched
  files. Unlike `cloud-spec-trim` (which had to add 5 missing `CLASS_*`
  regions for unwrapped dataclasses) and `domain-exceptions-spec-trim`
  (which had to add 15 missing `CLASS_*` regions for unwrapped exception
  classes), this change is purely contract-field enrichment inside existing
  regions. No `# region` / `# endregion` markers are inserted or moved.

- **All referenced test files exist.** Audited:
  `tests/unit/test_abandon_node.py` (asserts the actual `discard_by_node`
  behavior, including the docstring "The DB read (list_by_status) is no
  longer used by abandon_node"),
  `tests/unit/test_allocate_task_failure_modes.py` (asserts the
  empty-platforms short-circuit),
  `tests/unit/test_allocate_task_node_pairing.py`,
  `tests/unit/test_allocation_tracker.py`,
  `tests/unit/test_application_no_adapter_imports.py` (enforces the
  `yascheduler.infra` import-hygiene contract for `abandon_node`,
  `consume_task`, `allocate_task`, `deallocate_nodes`, `orchestrator`,
  `submit_task` — covers 5 of the 6 touched files; `query_tasks` and
  `allocation_tracker` are not in the FORBIDDEN_NAMES list because they
  have no infra imports at all),
  `tests/unit/test_client_query.py`,
  `tests/unit/test_consume_task.py` (asserts the happy path, permanent,
  transient, mixed, AND the not-found vacuously-finalised path),
  `tests/unit/test_query_tasks.py`. The trim cannot weaken coverage.

- **The `yascheduler.infra` import-hygiene contract is enforced by a static
  guard test, not by spec prose.** `tests/unit/test_application_no_-
  adapter_imports.py::test_no_forbidden_adapter_runtime_imports` is
  parametrized over `APPLICATION_MODULES` (which includes
  `abandon_node`, `consume_task`, `allocate_task`, `deallocate_nodes`,
  `orchestrator`, `submit_task`) and asserts none of them expose
  `AllSSHRetryExc` / `SFTPRetryExc` / `SFTPError` / `backoff`. The
  relocated `SHALL NOT import yascheduler.infra at runtime` spec prose
  becomes an `INVARIANTS` entry on each `FUNC_*` region noting that the
  invariant is enforced structurally by this test. Spec prose is not the
  enforcement mechanism — the test is.

- **Spec delta validates cleanly.** `openspec validate --all --json` →
  35/35 passed, exit 0. `openspec validate use-cases-spec-trim --strict` →
  valid, 0 issues. The 7 MODIFIED-Requirements headers match the existing
  main spec requirement names exactly (whitespace-insensitive). The archive
  step will apply correctly.

- **Follows the established precedent.** The proposal structure (Why /
  What Changes / Capabilities [Modified only, no New] / Impact / Non-Goals),
  the "markup-only, no behavioral change" framing, the tasks.md
  common-rules + per-file grouping + final apply-and-verify section, the
  README.md one-line summary, and the review-log.md structure all mirror
  `orchestrator-spec-trim`, `cloud-spec-trim`, `domain-exceptions-spec-
  trim`, and `slim-domain-ports-spec` row-for-row. The common-rules section
  is copied almost verbatim from `orchestrator-spec-trim` (the most recent
  in-flight precedent at the time of writing) with file-specific BLOCK_*
  references adjusted to the use-cases set.

### Verdict: PASS

All 🔴 issues found in the round were fixed before the round closed (the
one surviving `SHALL NOT` in the `AbandonNode` body rephrased to a positive
form; the unsolicited "Missing input file" `SubmitTask` scenario removed
and the original "Submit constructs NewTask, not Task" scenario restored).
All 🟡 suggestions are deliberate design choices documented inline. No
outstanding 🔴. The change is ready for implementation.

The implementation phase (apply tasks 1.1 – 8.3 plus the end-to-end verify
9.1 – 9.6) is the next step — separate from this proposal/specs/tasks
review. The apply-phase reviewer should re-verify, after implementation,
that: (a) every `# region CLASS_*` / `FUNC_*` / `METHOD_*` / `BLOCK_*` /
`MODULE_CONTRACT` in the 7 touched application files still has a paired
`# endregion` and wraps the entire entity (no orphaned trailing code, no
early close, nested regions inside their enclosing regions), (b) no
contract field is invented, (c) every `PURPOSE` is still a WHY (the tasks
do not modify `PURPOSE` but the verify step should confirm the audit
remains true), (d) `openspec validate --all --json` still passes 35/35,
(e) the scenario count in `openspec/specs/use-cases/spec.md` after archive
equals 34, and (f) the relocated `SHALL NOT` prose did not silently
reappear as a `SHALL NOT:` pseudo-field in any region's contract block.
