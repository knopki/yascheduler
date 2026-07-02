## proposal Round 1 — 2026-07-02

### 🔴 Fixed
- (none — no blocking issues found)

### 🟡 Addressed

- **Invariant `ip == '' IFF enabled=FALSE AND tmp/pending` not fully stated.** The proposal says "enabled rows never have ip=''" (one direction) and implies the converse through the `ip <> ''` filter in `list_disabled`, but never states the bidirectional invariant formally. This invariant is load-bearing: it justifies removing the `"." in ip` filter from `list_enabled` (only need one direction there) AND adding `ip <> ''` to `list_disabled` (the other direction — disabled-tmp rows have `ip=''`, so they're excluded by `ip <> ''`). The brief establishes it explicitly. Without the full IFF at the proposal level, a future reader might not understand why `ip <> ''` in `list_disabled` is safe (real-disabled VMs keep real IPs) vs. why it's not a format check. Recommendation: add the invariant sentence verbatim from the brief (e.g., right after the `list_enabled`/`list_disabled` bullet in What Changes, or in the Why section).

- **NULL sentinel rejected alternative rationale is implicit.** The proposal picks `""` over NULL but doesn't explain why (the brief gives specific reasoning: 44 sites would need `str | None`, mypy guards, `None == None` false-matches). The rationale is embedded in the choice but not stated. Consider adding a brief note (one sentence) in the Why or non-goals section. Not blocking — the choice is correct and the outcome is clear.

- **`deallocate_nodes.py` `"." in node.ip` filter not mentioned.** The `deallocate_nodes` use case (`yascheduler/application/deallocate_nodes.py:159`) has its own `"." in node.ip` post-filter on `list_disabled()` return values. After this change, `list_disabled` SQL already excludes `ip=''` rows, so the caller-side dot-filter is still correct (redundant for ip='' rows, but still filters non-dot hostnames). This is not a bug — the proposal correctly scopes the filter removal to `PostgresNodeRepository` only. But the brief's allocate_task focus could give the impression that all `"." in ip` filters are being removed. Worth a brief clarification sentence in the proposal (e.g., "Callers of `list_disabled` outside `allocate_task` (e.g. `deallocate_nodes.py`) retain their own `"." in ip` filters; those are out of scope.") to prevent confusion during implementation.

### 🔴 Outstanding
(empty — batch passes)

### Brief coverage checklist
- [x] Rejected alternatives (5) — all rationales present (NULL sentinel implicit, others explicit)
- [x] Mapping tables (4: NodeRepository surface, NewNode defaults, _TmpSelection, Migration 003) — all rows covered
- [x] Cross-module data flows (2: cloud alloc, cleanup) — described at WHAT level
- [x] allocate_task.py call-site changes (7) — all listed (some grouped in same sentence)
- [x] Spec capabilities (6 modified) — names match openspec/specs/
- [x] Invariant `ip == '' IFF enabled=FALSE AND tmp/pending` — half-stated (only "enabled rows never have ip=''" direction); full IFF missing
- [x] Idempotent-DELETE rationale — stated
- [x] Non-goals (5: VARCHAR widening, t.allocated_ip, SSH rekey, lookup rekey, deallocate rekey) — explicit

## proposal Round 1 — declarative additions applied 2026-07-02

The three 🟡 items were addressed via declarative (non-decision-level) edits
to `proposal.md`, allowed under the soft-freeze rule:

- Full bidirectional invariant `ip == '' IFF enabled=FALSE AND tmp/pending`
  added verbatim under the `list_enabled`/`list_disabled` SQL bullet, with
  explicit rationale for why it justifies both filter changes (one direction
  for list_enabled, the converse for list_disabled).
- NULL-vs-empty-string rationale added as a paragraph in the Why section
  (the 44-site Optional ripple + None==None footgun + NULL's only advantage
  being moot once UNIQUE drops).
- `deallocate_nodes.py`'s own `"." in node.ip` caller-side filter called out
  explicitly as out-of-scope (stays as-is; redundant for ip='' rows now
  excluded by SQL, still filters non-ipv4 hostnames).

Proposal batch frozen. Proceeding to design.md.

## design Round 1 — 2026-07-02

### 🔴 Fixed
- (none — no blocking issues found)

### 🟡 Addressed
- (none — all clarity and completeness concerns are resolved)

### 🔴 Outstanding
(empty — batch passes)

### Proposal-consistency checklist
- [x] NewNode defaults — consistent (Decision 4 + Risk item reference `ip=""`, `ncpus=0`)
- [x] add_tmp REMOVED (Protocol + impl + insert_tmp.sql) — consistent (Decision 4)
- [x] list_enabled/list_disabled filter changes — consistent (Decision 2, invariant formally stated IFF)
- [x] Migration 003 contents — consistent (Decision 6, exact SQL verbatim)
- [x] schema.sql edits (CONSTANT bump + drop UNIQUE) — consistent (Migration Plan steps 2-3)
- [x] _TmpSelection + 5 helper signatures — consistent (Decision 5 lists all 4 named helpers + outer body)
- [x] get(tmp_ip) lookups removed; remove(tmp_node_id) direct — consistent (Decision 5, idempotency rationale present)
- [x] Invariant stated — consistent (Decision 2, bidirectional IFF)
- [x] deallocate_nodes filter out-of-scope — consistent (Non-Goals item + Risk item)
- [x] 5 non-goals — consistent (all 5 listed in Non-Goals, plus the 6th caller-side dot-filter non-goal)

Design batch frozen (single-round pass per 4a). Proceeding to specs/.

## specs Round 1 — 2026-07-02

### 🔴 Fixed
- (none — no blocking issues found)

### 🟡 Addressed
- (none — all issues from earlier rounds resolved; no new issues in specs)

### 🔴 Outstanding
(empty — batch passes)

### Spec-compliance checklist
- [x] domain-entities: MODIFIED header, requirement name matches main spec, NewNode defaults correct, scenarios testable
- [x] domain-ports: MODIFIED header, "NodeRepository port" name matches, add_tmp removed from method list, insert-serves-tmp scenario, no-add_tmp scenario present
- [x] postgres-persistence: MODIFIED header, "PostgresNodeRepository implements NodeRepository" name matches, add_tmp removed, list_enabled no-python-filter, list_disabled SQL `ip <> ''`, _row_to_node handles "", scenarios testable
- [x] use-cases: MODIFIED header, "AllocateTask use case" name matches, _TmpSelection.node_id, insert-not-add_tmp, remove-by-node_id-direct (no get, no None-branch), idempotent rationale, scenarios testable
- [x] Cross-spec consistency: NewNode defaults, insert call shape, node_id cleanup handle all agree across the 4 specs
- [x] No decision-level drift from frozen proposal/design

Specs batch frozen (single-round pass per 4a). Proceeding to tasks.md.

## tasks Round 1 — 2026-07-02

### 🔴 Fixed
- (none — no blocking issues found)

### 🟡 Addressed

- **`NodeId` import not mentioned in allocate_task.py tasks (6.2–6.8).** The `_TmpSelection` NamedTuple and all 5 helper signatures gain `node_id: NodeId`. With `from __future__ import annotations` active, function annotations are strings (no runtime import needed), but `NamedTuple` metaclass processes `__annotations__` at class-creation time and resolves `'NodeId'` via `typing.get_type_hints()`, which requires `NodeId` to be importable at the module top level. Currently `NodeId` is NOT imported in `allocate_task.py` at all (not even under `TYPE_CHECKING`). `NodeId` IS re-exported from `yascheduler.domain` (visible in `__init__.py:88`), so adding it to the existing `from yascheduler.domain import ...` line is a one-import addition. No task explicitly mentions this. The implementer will hit a runtime error or zuban failure and fix it, but it's worth calling out so it's not an afterthought. Recommendation: add a note to task 6.2 or 6.3 to ensure `NodeId` is imported at the module top level.

- **Task 1.4 "update its expected value" wording is misleading for the existing test.** The existing `test_schema_sql_last_migration_constant_matches_latest_migration` in `tests/unit/test_migration_runner.py` auto-detects the constant by parsing `schema.sql` and comparing against the max `prefix_id` in `migrations/`. It does NOT have a hardcoded expected value that needs updating — the test will pass automatically once task 1.1 (migration file) and 1.2 (CONSTANT bump) are done. The task correctly says "if a prior test already asserts this, verify" but the "update its expected value" phrasing could confuse. Not blocking — the implementer will verify and see no expected-value edit is needed.

- **Task 5.3 action verb "Update" conflicts with the parenthetical clarification.** The task says "Update `openspec/specs/postgres-persistence/spec.md` SQL-file-layout requirement note if it lists `insert_tmp.sql`" but then clarifies "if so, it stays as the post-change spec since the delta spec overrides at archive — but check for consistency; if the main spec lists `insert_tmp.sql` as a managed file, the archive step will reconcile it". The word "Update" suggests editing the main spec now, which the parenthetical says is unnecessary. The actual intent is to check and document for the archive step. Recommendation: rephrase the task action to "Check `openspec/specs/postgres-persistence/spec.md` for `insert_tmp.sql` references in the SQL-file-layout requirement; note any inconsistency for archive reconciliation (no pre-archive edits to main specs)."

### 🔴 Outstanding
(empty — batch passes)

### Tasks-completeness checklist
- [x] Migration 003 + schema.sql (3 edits) — covered (Group 1, tasks 1.1–1.3)
- [x] NewNode defaults — covered (Group 2, tasks 2.1–2.3)
- [x] Protocol add_tmp removal — covered (Group 3, tasks 3.1–3.3)
- [x] PostgresNodeRepository add_tmp removal + 2 post-filter removals — covered (Group 4, tasks 4.1–4.5)
- [x] list_disabled.sql + insert_tmp.sql deletion — covered (Group 5, tasks 5.1–5.3)
- [x] allocate_task.py _TmpSelection + 5 helpers + outer body — covered (Group 6, 9 sub-tasks 6.1–6.9)
- [x] get(tmp_ip) lookups + None-branches removed; remove(tmp_node_id) direct — covered (tasks 6.4, 6.6, 6.8)
- [x] GRACE-lite graph + contracts top-down — covered (first task of each code group: 2.1, 3.1, 4.1, 6.1; module metadata tasks 2.2, 4.5, 6.9)
- [x] Unit tests (6 files: domain_ports, domain_model, application_use_cases, application_events, allocate_task_failure_modes, cloud_alloc_session_lifecycle) — covered (Group 7, tasks 2.3, 3.3, 7.1–7.5)
- [x] Integration tests (tmp lifecycle + migration 003 + filter behavior) — covered (Group 8, tasks 8.1–8.3)
- [x] Static checks (ruff, lint-imports, zuban, pytest unit/integration, grace_check, openspec validate) — covered (Group 9, tasks 9.1–9.7)
- [x] Final grep sweep for leftovers — covered (task 9.8; correctly excludes deallocate_nodes.py out-of-scope filter)
- [x] No scope creep (no SSH/allocated_ip/VARCHAR/lookup-rekey work) — verified; all non-goals respected
- [x] Task granularity (≤2h each) — verified; largest single edit is reworking a helper body (6.4, 6.6) — well bounded; smallest tasks (1.1, 1.2, 1.3) are separate conceptual edits in different files
- [x] Dependency ordering (migration → model → ports → impl → SQL → allocate_task → tests → checks) — verified; correct
- [x] Checkbox format (`- [ ] N.M`) — verified; all tasks use correct format; group headings use `## N.`; no bare bullets
- [x] Within-group ordering (6.1 graph → 6.2 _TmpSelection → 6.3 _select_and_insert_tmp → 6.4–6.7 helpers → 6.8 outer body → 6.9 module metadata) — verified; correct (consumers after producers)

Tasks batch frozen (single-round pass per 4a). Two declarative (non-decision-level) clarifications applied per soft-freeze rule:
- Task 6.2: added explicit `NodeId` top-level import note (NamedTuple resolves annotations via `typing.get_type_hints()` at class-creation time, so the import is required even with `from __future__ import annotations`).
- Task 5.3: rephrased action verb from "Update" to "Check ... note for archive reconciliation" to match the actual intent (no pre-archive main-spec edits; delta spec overrides at archive).

All 4 artifact batches (proposal, design, specs, tasks) are frozen. Change is ready for `/opsx-apply`.
