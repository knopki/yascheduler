# review-log — client-query-uow

## proposal Round 1 (k-reviewer-fast) — 2026-06-23

### Verdict: PASS

### 🟢 Minor findings (both addressed before full review)
- **Decision 8 not explicitly mentioned** — brief's locked Decision 8
  (`queue_get_task_async` keeps delegating to `queue_get_tasks_async`) was
  absent from proposal.md. Added explicit bullet stating the full method
  family is covered and that `queue_get_task_async` keeps its delegation
  pattern.
- **Sync wrappers not mentioned** — brief's goal names
  `queue_get_tasks` / `queue_get_task` (sync) but proposal omitted them. The
  added bullet also clarifies sync wrappers keep delegating via `to_sync`.

### 🔴 Outstanding
None.

### Brief coverage
All 20 checklist items pass post-edit (Decision 8 + sync wrappers now
explicit). No contradictions, no scope creep, no new capability declared.

---

## proposal Round 2 (k-reviewer) — 2026-06-23

### Verdict: PASS — FROZEN

### 🟢 Minor findings (one addressed, one deferred by reviewer's call)
- **"verified: no current caller populates it"** too loose — restored the
  explicit `get_tasks_with_cloud_by_id_status` method name from the brief
  for auditability.
- **Cross-class IntEnum rationale omitted** — reviewer marked "No action
  required"; rationale belongs in design.md.

### 🔴 Outstanding
None.

### Verification spot-checks (all confirmed by reviewer)
- `CLIDeps.query` at `di.py:105-108`, only caller `tests/unit/test_di.py:139`.
- `grep backoff yascheduler/adapters/persistence/` empty; legacy `db.py:219`
  still has backoff — matches cross-cutting-gap framing.
- 6-key dict shape (cloud always None today) confirmed via `_task_to_model`.
- `DB.create` single production caller: `client.py:149`.
- TaskStatus IntEnum values identical (0/1/2) across `db.py` and
  `domain/model.py`.
- ARCHITECTURE.md §2.9 stale claim + §6.4 deferred marker both real.
- All 6 target spec dirs exist under `openspec/specs/`.

### Freeze
proposal.md is the frozen baseline for all downstream artifacts. Declarative
additions only from here; decision-level changes require full-chain unfreeze.

---

## design Round 1 (k-reviewer-fast) — 2026-06-23

### Verdict: PASS (with fixes applied)

### 🟡 Significant suggestion (addressed)
- **D5 narrative contradicted Migration Plan on α test timing.** D5 claimed
  the constructor change lands "in the same commit as the characterization
  tests, ahead of the body swap"; the Migration Plan had constructor as
  step 2 and α tests landing with the swap in step 4. Resolved by reframing
  D5: γ is the strict characterization-first golden master (lands and passes
  against current DB-backed code *before* the swap, then passes unchanged
  after); α is unit verification of the post-swap implementation (lands
  with the swap; the seam provides forward-looking stability for future
  refactors, not historical characterization).

### 🟢 Minor (both addressed)
- **"Characterization-first" overstatement for α.** Softened: D5 now
  distinguishes γ (strict characterization) from α (unit verification). α
  cannot characterize pre-swap behavior because the dispatch logic only
  exists post-swap.
- **Migration Plan step 3 organizational oddity.** Plan restructured:
  γ now lands as step 3 (passes against current code), swap + α merged as
  step 4, renumbered subsequent steps. Added a Bisectability note.

### 🔴 Outstanding
None.

### Coverage
All 11 checklist items pass post-edit. D1–D7 each have alternatives; risks
honest; migration plan now internally consistent and ordered for true
characterization-first discipline; no contradiction with frozen proposal.md.

---

## design Round 2 (k-reviewer) — 2026-06-23

### Verdict: PASS — FROZEN

### 🟢 Polish (three applied, one deferred)
- **D6.2 expanded** to "connection/executor leak" — the legacy path also
  leaks `DB.create`'s `ThreadPoolExecutor(max_workers=1)`, not just the
  pg8000 connection. UoW `__aexit__` reclaims both.
- **D2 cache-rejection wording** corrected: `CLIDeps` doesn't "own" the
  `MessageBus`; the bus lives in `make_cli_deps`'s stack and is captured by
  the `_uow_factory` closure (`di.py:230-233`). Effect unchanged; phrasing
  now precise.
- **D5 γ status-assertion strategy** added: γ must assert `status` by
  `int(value)` / `==` / `.name`, never `isinstance(..., db.TaskStatus)`,
  otherwise it would falsely fail post-swap when the enum class becomes
  `domain.TaskStatus`.
- **Test-fakery maintenance cost** (deferred) — reviewer noted α introduces
  fakes that must track the Protocols as they evolve; accepted as-is, since
  it's a general property of unit-test fakes, not specific to this design.

### 🔴 Outstanding
None.

### Verification spot-checks (all confirmed)
- `PostgresTaskRepository.list_by_status(statuses: set[TaskStatus], limit)`
  at `postgres.py:174`; `.list_by_jobs(job_ids: list[int])` at `:192`.
  Design's `set(statuses)` / `list(jobs)` coercion matches.
- `make_cli_deps` is sync (`di.py:228`); `self._deps_factory(...)` is sync.
- Planned `ValueError` matches `client.py:143-144` exactly.
- `queue_get_task_async` delegation (`for ... return task_dict`) confirmed
  at `client.py:182`.

### Decision scrutiny
D1 SOUND · D2 SOUND · D3 SOUND · D4 SOUND · D5 SOUND (post-R1) ·
D6 SOUND · D7 SOUND.

### Freeze
design.md is the frozen baseline alongside proposal.md. specs/ and tasks.md
must conform to both. Declarative additions only; decision-level changes
require unfreezing design and re-reviewing from there.

---

## specs Round 1 (k-reviewer-fast) — 2026-06-23

### Verdict: PASS (with polish applied)

### 🟢 Polish (two applied, one deferred-as-acceptable)
- **package-facades return-type imprecision** — "Each query method SHALL
  return a Mapping" was imprecise for list variants. Tightened to
  "return Mappings (a `Sequence[Mapping]` for list variants,
  `Optional[Mapping]` for single-task variants)".
- **dependency-injection scenarios coupled to `self._deps_factory`** —
  Scenarios 4 and 5 referenced the private attribute. Rewritten behaviorally
  ("the factory callable is invoked twice", "the factory callable returns
  `CLIDeps` directly (NOT awaited)").
- **test-db-integration meta-scenario** (deferred) — "assert status without
  coupling to enum class" describes test code rather than system behavior;
  acceptable because design D5's γ guidance explicitly requires it.

### 🔴 Outstanding
None.

### Per-delta verdict
use-cases PASS · package-facades PASS · dependency-injection PASS ·
testing-unit PASS · test-db-integration PASS · db-wrapper (MODIFIED) PASS
(header `### Requirement: DB provides task and node CRUD` matches existing
spec line 9 exactly; all original methods preserved verbatim; dropped
"Existing client code compiles unchanged" scenario is the one that becomes
false; added "Production code does not instantiate DB" captures new
contract).

### Cross-delta coherence
query_tasks signature ✓ · deps_factory/FakeCLIDeps ✓ · γ enum-class rule
matches design D5 ✓.

### Format compliance
4-hashtag scenarios everywhere ✓ · SHALL/MUST normative ✓ · MODIFIED header
matches existing spec ✓.

`openspec validate "client-query-uow" --json` → valid (1/1 passed, 0 issues).

---

## specs Round 2 (k-reviewer) — 2026-06-23

### Verdict: PASS with notes (two 🟡 applied)

### 🟡 Significant suggestions (both addressed in R3)
- **package-facades overlap with existing "Public API stability"** — the
  existing requirement at `openspec/specs/package-facades/spec.md:302-314`
  said "yascheduler.client remains unchanged", which becomes literally
  false post-change. Resolved by converting package-facades delta to
  MODIFIED + ADDED: MODIFY the existing "Public API stability" requirement
  to permit backward-compatible keyword-only optional additions; keep the
  ADDED "Yascheduler client query method public contract" for the specific
  shape codification.
- **dependency-injection private-attribute leak** — requirement body
  referenced `self._deps_factory` (private). Reworded to behavioral
  wording: "The factory passed via `deps_factory` SHALL be invoked as
  `<factory>(self.config)` exactly once per ... call".

### 🟢 Polish (two applied)
- use-cases "is set" → "is non-empty" (truthiness semantics matching
  existing `client.py:150-155` dispatch).
- test-db-integration transient `yascheduler.client.DB` symbol →
  `yascheduler.db.DB` / `make_cli_deps` / otherwise (stable across swap).

### 🔴 Outstanding
None. Verdict PASS.

### MODIFIED db-wrapper archive-reconciliability (confirmed)
Header `### Requirement: DB provides task and node CRUD` matches existing
spec line 9 byte-for-byte. All 12+12+3 methods preserved verbatim. Dropped
scenario ("Existing client code compiles unchanged") is exactly the one
that becomes false. Added "Production code does not instantiate DB"
captures the new contract; verified `class DB` is defined only in
`yascheduler/db.py:98` and `client.py:35` is the only production import
being removed.

---

## specs Round 3 (k-reviewer-fast confirm) — 2026-06-23

### Verdict: PASS — clean confirmation

### R2 fix verification (all confirmed)
- package-facades MODIFIED header `### Requirement: Public API stability`
  matches existing spec line 302 exactly.
- package-facades MODIFIED block complete (4 bullets, 4 scenarios);
  ADDED `Yascheduler client query method public contract` intact.
- dependency-injection body has zero `self._deps_factory` references;
  purely behavioral wording.
- use-cases truthiness coherence with scenarios confirmed.
- test-db-integration non-transient symbol confirmed (`yascheduler.db.DB`
  is stable; `yascheduler.client.DB` does not exist post-swap).

### 🔴 / 🟡 / 🟢
All empty. No new issues introduced by edits.

`openspec validate "client-query-uow" --json` → still valid.

---

## specs Round 4 (k-reviewer final) — 2026-06-23

### Verdict: PASS — FROZEN — READY

### 🔴 / 🟡
Both empty.

### 🟢 Observations (non-actionable, for future-reviewer awareness)
- use-cases truthiness parenthetical anchors to pre-swap code path
  (accurate; indirect phrasing).
- db-wrapper "after the change lands" temporal anchor (clear, unusual).
- package-facades MODIFIED reframe is a conscious policy broadening
  (kw-only optional additions permitted for ALL future changes); well-bounded.

### MODIFIED archive-reconciliability (confirmed byte-for-byte)
- `### Requirement: Public API stability` matches `openspec/specs/package-facades/spec.md:302`.
- `### Requirement: DB provides task and node CRUD` matches `openspec/specs/db-wrapper/spec.md:9`.
- All preserved content retained with intent; 1 scenario dropped
  (justified), 1 added (new contract) in db-wrapper; 2 scenarios added in
  package-facades MODIFIED, `yascheduler.client` bullet consciously reworded.

### MODIFIED↔ADDED coherence (package-facades)
Coherent, not redundant. MODIFIED grants the general permission (kw-only
optional additions); ADDED specifies the concrete application
(`deps_factory`) + full query contract. Complementary scenarios (positive
callsite-compat vs negative positional-TypeError).

### Cumulative cross-delta coherence
All dimensions pass: query_tasks signature ✓, deps_factory/fakes ✓,
six-key shape ✓, enum-preserve rule ✓, γ enum-class rule ✓, no
frozen-baseline drift ✓.

### Format compliance
4-hashtag ✓ (32 scenarios) · SHALL/MUST ✓ · WHAT not HOW ✓ · testable ✓.

### Freeze
specs/ batch frozen. All downstream work (tasks.md, then implementation)
must conform to proposal + design + these specs. `openspec validate
"client-query-uow" --json` → valid.

---

## tasks Round 1 (k-reviewer) — 2026-06-23

### Verdict: FIX_REQUIRED (two 🟡 applied)

### 🟡 Significant (both addressed)
- **Task 3.1 omitted single-task query variant** — frozen
  `test-db-integration` spec has a "Single-task query returns Optional
  Mapping" scenario; task 3.1 covered only list variants. Extended 3.1 to
  also assert `queue_get_task(task_id)` returns a single six-key Mapping
  and `queue_get_task(<unknown>)` returns `None`.
- **Dependency-injection "Factory invoked once per query call" scenario
  had no test owner** — task 4.3 enumerated only the five `testing-unit`
  scenarios. Added a counting-spy assertion to 4.3 (two
  `queue_get_tasks_async` calls → factory invoked exactly twice).

### 🟢 Minor (all three applied)
- Task 1.1 now reminds the implementer to include GRACE-lite
  `MODULE_CONTRACT`/`MODULE_MAP`/`CHANGE_SUMMARY` headers on the new file
  (otherwise `grace_check.py` in 7.2 fails).
- Task 2.2 wording corrected: "positional fourth-arg" → "positional third
  argument" (factory is the third positional, raises TypeError because
  `deps_factory` is keyword-only).
- Task 6.3 "Trim M-DB annotations if needed" tightened to a concrete
  criterion (remove annotations referencing production callers; only
  test-consumer references remain valid after 7.5).

### 🔴 Outstanding
None.

### Coverage (post-fix)
proposal "What Changes"/Impact/FIXMEs ✓ · design D1–D7 ✓ · Migration Plan
steps 1–7 mapped to tasks ✓ · 6 spec deltas each have impl tasks
(use-cases→1.1/1.3, package-facades→2.1/2.2/4.1/4.3, dependency-injection
→2.1/4.3, testing-unit→4.3, test-db-integration→3.1, db-wrapper→7.5) ✓ ·
FIXMEs at correct locations ✓ · GRACE-lite obligations in 6.3 ✓.

### Characterization-first ordering
Confirmed: §3 (γ green vs current `DB` path) → §4 swap → 4.4 re-runs γ
unchanged. Bisectable.

### Format / scope
`## N.` headings ✓ · checkbox format ✓ (22 tasks) · ≤2h sizing ✓ · no
out-of-scope work ✓ (submit path preserved per 2.1; no test-fixture
migration; `db.py` not removed — 7.5 explicitly expects test imports to
remain).

`openspec validate "client-query-uow" --json` → valid.

---

## tasks Round 2 (k-reviewer confirm) — 2026-06-23

### Verdict: PASS — FROZEN — READY

### 🔴 / 🟡
Both empty.

### 🟢 Non-actionable
- R1 task count was 22; post-fix count is 23 (task 7.6 bookkeeping item was
  present but not enumerated in R1's fix list). Non-issue — 7.6 is
  legitimate and in-scope.

### R1 fix verification (all five confirmed)
- Task 3.1 single-task variant + non-existent-id None return — aligned
  with frozen `test-db-integration` "Single-task query returns Optional
  Mapping" scenario.
- Task 4.3 counting-spy (two calls → factory invoked twice) — aligned with
  frozen `dependency-injection` "Factory is invoked once per query call".
- Task 1.1 GRACE-lite headers reminder + forward link to 7.2.
- Task 2.2 "positional third argument" wording.
- Task 6.3 concrete M-DB trim criterion (no "if needed" hedge).

### No regressions
Edits were strictly additive clarifications within existing task lines.
Cross-task consistency preserved (3.1 forbids `isinstance(db.TaskStatus)`
for γ; 4.3 uses `isinstance(domain.TaskStatus)` for α — correctly divergent
per design D5). Coverage still complete; characterization-first ordering
intact (§3 γ → §4 swap → 4.4 γ re-run).

### Freeze
tasks.md frozen. All 4 artifacts now frozen:
  • proposal.md (R2)
  • design.md (R2)
  • specs/ 6 deltas (R4)
  • tasks.md (R2)

Change `client-query-uow` is apply-ready. Implementation via `/opsx-apply`
is a separate flow not covered by this proposal-authoring session.

---

## apply — 2026-06-23

### Scope of this entry

Tasks 1–14 were implemented in prior apply sessions (use case, seam,
characterization integration test, body swap, query-path unit tests,
FIXMEs). This session landed the remaining §6 (documentation) and §7
(final verification) tasks: 15–23.

### Completed this session

- 6.1 `docs/ARCHITECTURE.md` §2.9 — dropped the stale "Consumed by
  `client.py` and `CloudProvisionerImpl`" claim; recast the `client.py`
  bullet to state query methods route via the `query_tasks` use case
  over a UoW (no `DB` construction) and the `db.py` bullet to state it
  is test-only pending a separate removal proposal.
- 6.2 `docs/ARCHITECTURE.md` §6.4 — marked the query-methods migration
  **resolved** by this change with a cross-reference to
  `openspec/changes/client-query-uow/`. Also updated the §7
  open-questions table row that referenced §6.4 (declarative status
  update; the prior "no active proposal" wording now contradicted §6.4).
- 6.3 `docs/knowledge-graph.xml`:
  - Added `M-APPLICATION-QUERY-TASKS` (`TYPE="CORE_LOGIC"`,
    `STATUS="implemented"`, `<fn-query_tasks>` annotation).
  - Updated `M-APPLICATION` facade depends + annotations to include
    `M-APPLICATION-QUERY-TASKS` and `export-query_tasks` (matches the
    file's frozen `MODULE_CONTRACT`).
  - Updated `M-CLIENT` depends (dropped `M-DB`; added `M-DOMAIN-MODEL`
    + `M-APPLICATION-QUERY-TASKS`) and added `fn-_task_to_dict` +
    `const-_deps_factory` annotations.
  - Removed the stale `M-CLIENT → M-DB` CrossLink ("submits tasks and
    queries status" — both halves now false).
  - Added `M-CLIENT → M-APPLICATION-QUERY-TASKS` (relation: "delegates
    task queries") and `M-APPLICATION-QUERY-TASKS → M-PERSISTENCE-UOW`
    (relation: "reads via UoW").
- 7.1 `openspec validate "client-query-uow" --json` → valid, 0 issues.
- 7.2 `python3 scripts/grace_check.py` → exit 0; 0 errors, 27 warnings
  (all pre-existing soft-limit/func-size warnings; none introduced here).
- 7.3 Static checks clean: `uv run zuban check` (0 issues / 135 files),
  `uv run ruff check .` (all passed), `uv run ruff format --check .`
  (134 files already formatted), `uv run lint-imports` (clean, 1 kept).
- 7.4 `uv run pytest -m unit` → 409 passed; `uv run pytest -m
  integration` → 69 passed (including
  `tests/integration/test_client_query_integration.py` 3 tests green
  against the swapped implementation).
- 7.5 `grep -rn "from yascheduler.db import" yascheduler/` → zero
  matches.
- 7.6 This entry.

### Deviations from task wording (6.3 annotation prefix + depends IDs)

1. **Annotation prefix.** Task 6.3 asked for `param-deps_factory` on
   `M-CLIENT`. `param-` is not in `grace_check.py`'s
   `VALID_ANNOTATION_PREFIXES` (`fn-`, `class-`, `type-`, `export-`,
   `const-`); adding it would have produced an `annotation-prefix`
   error and failed 7.2. Used `const-_deps_factory` instead, matching
   the precedent set by `M-APPLICATION-ORCHESTRATOR`'s
   `const-allocation_tracker` for instance attributes set in `__init__`.
2. **M-APPLICATION-QUERY-TASKS depends.** Task 6.3 said
   `M-DOMAIN-PORTS, M-PERSISTENCE-UOW`. Used `M-DOMAIN-MODEL,
   M-APPLICATION-UOW` to (a) match the file's frozen
   `START_MODULE_CONTRACT` `DEPENDS:` line exactly, and (b) match the
   convention used by every sibling application use case module
   (`M-APPLICATION-SUBMIT`, `M-APPLICATION-ALLOCATE`,
   `M-APPLICATION-CONSUME`, `M-APPLICATION-DEALLOCATE` all depend on
   `M-APPLICATION-UOW` — the abstract port — not `M-PERSISTENCE-UOW`).
   The spec's literal IDs named the eventual concrete/runtime targets;
   the graph convention is to record direct code-level imports.
3. **M-CLIENT depends.** Not explicitly requested by 6.3, but the
   frozen GRACE-lite rule is "dependencies changed → `<depends>` +
   `<CrossLink>`." `client.py` dropped `from .db import` and gained
   `from .application import query_tasks` + `from .domain import Task,
   TaskStatus`, so the depends edge was updated to keep the graph
   truthful (otherwise `grace_check`'s M-CLIENT depends would have
   listed `M-DB` which is no longer imported).

### Deviations from task wording (7.3 — pre-existing ruff errors fixed)

Tasks 1.1 and 1.3 (marked done in prior sessions) left 3 ruff errors
that surfaced when 7.3 ran the gate for the first time. Fixed as part
of 7.3 (the task explicitly requires "all clean"):

- `yascheduler/application/query_tasks.py` — 2× `TC001`: moved
  `Task, TaskStatus` from a runtime `yascheduler.domain` import into
  the existing `TYPE_CHECKING` block (file already has
  `from __future__ import annotations`, so annotations stay string
  literals). No runtime behavior change.
- `tests/unit/test_query_tasks.py:75` — `ANN202`: added the return
  type `Callable[[], AbstractUnitOfWork]` to the `_factory` helper and
  the corresponding `from collections.abc import Callable` import.

### Verification summary

| Gate                                 | Result                                            |
| ------------------------------------ | ------------------------------------------------- |
| `openspec validate` (7.1)            | valid, 0 issues                                   |
| `scripts/grace_check.py` (7.2)       | exit 0; 0 errors, 27 pre-existing warnings        |
| `zuban check` (7.3)                  | 0 issues / 135 files                              |
| `ruff check .` (7.3)                 | all passed                                        |
| `ruff format --check .` (7.3)        | 134 files already formatted                       |
| `lint-imports` (7.3)                 | clean; 1 contract kept                            |
| `pytest -m unit` (7.4)               | 409 passed                                        |
| `pytest -m integration` (7.4)        | 69 passed (incl. characterization integration test unchanged) |
| grep `from yascheduler.db import` (7.5) | 0 matches in `yascheduler/`                    |

No review rounds were run during apply (the task wording for 7.6 only
asked for "implementation-time entries (any review rounds during
apply)"). Change is ready for `/opsx-verify`.

