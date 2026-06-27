# Review Log — fix-static-node-connect-exclusion

## proposal Round 1 — 2026-06-28

Reviewer: @k-reviewer-fast
Baseline: exploration context (no explore-brief.md; bug fix change)

### ✅ Strengths
- Why is excellent: behavior-first problem statement, correct regression attribution to `3c3f7e0` task 4.7, test masking (`cloud="e2e"` workaround) documented.
- What Changes covers all required modifications: producer filter removal, consumer guard, e2e workaround removal, unit test flip + new temporal test, spec update, knowledge-graph update.
- Capabilities correctly identifies `orchestrator` as the sole MODIFIED capability (no separate abandon_node/connect-machine/static-nodes spec exists).
- Impact section correctly enumerates affected code/tests/specs/knowledge-graph and the "No changes" list (abandon_node, `_connect_grace_for`, DB schema, CLI, INI, public interfaces).
- "No breaking changes" claim accurate for CLI/`Yascheduler` API/INI/schema/AiiDA entrypoint.
- Baseline coverage complete: bug, root cause, regression, test masking, Variant A choice. Variant B rejection correctly absent (design rationale).

### 🟡 Addressed (scope-leak nits, fixed before freeze)
- Removed exact log marker `[CONNECT_RETRY_STATIC]` from proposal (implementation detail → belongs in design.md). Now reads "log a warning and return early".
- Removed guard-placement phrase "before the grace-check" from proposal (design-level rationale → belongs in design.md). Now reads "return early so static nodes retry indefinitely ... without ever reaching abandon_node".

### 🔴 Outstanding
- None.

### Verdict
APPROVED — no blocking issues. proposal.md frozen after scope-leak fixes.
## design Round 2 — 2026-06-28

Reviewer: @k-reviewer-fast
Baseline: frozen proposal.md + exploration context

### ✅ Strengths
- Context factually accurate; regression attribution verified against orchestrator.py:262.
- Goals/Non-Goals aligned with frozen proposal; non-goals fence off abandon_node, _connect_grace_for, DB schema, CLI, INI.
- Decision 1 (Variant A over B) sound on abstraction-layering grounds.
- Decision 2 (guard before CONNECT_GRACE_CHECK) precise: _connect_failures.setdefault (line 299) and _connect_grace_for never reached for static nodes.
- Risk section complete; _await_first_machine timeout correctly identified as existing behavior, not regression.
- Jump-host analysis: None never matches any CloudConfig.prefix → default jump host used. Good catch.

### 🟡 Addressed (fixed before freeze)
- Suggestion 1 (Variant B rejection imprecision): rephrased "would not be re-yielded for 2 minutes" → "the early-return guard in abandon_node would not fire for 2 minutes (120s grace window), so _connect_failures accumulates and _connect_grace_for(None) is called unnecessarily every cycle".
- Suggestion 2 (Decision 3 understates DB-row risk): replaced "the existing VM-delete guard is sufficient" with "the existing VM-delete guard prevents cloud-cleanup side effects; the DB-row-removal risk for a future caller is explicitly accepted and documented in the risk section".
- Suggestion 3 (spec contradiction not acknowledged): added to Non-Goals — "_connect_grace_for stays as code; the spec language is tightened to say the 120s fallback applies to non-None unmatched clouds only, so the path is never reached on the production path for static nodes and is exercised only by unit tests".

### 🔴 Outstanding
- None.

### Verdict
APPROVED — no blocking issues. design.md frozen after 3 suggestion fixes.

## specs Round 3 — 2026-06-28

Reviewer: @k-reviewer-fast
Baseline: frozen proposal.md + frozen design.md

### ✅ Strengths
- All 5 required spec changes present: producer yields all enabled not-connected regardless of cloud; consumer guard before grace-check for static; 120s fallback clarified to non-None unmatched only; "Non-cloud node excluded from abandon path" → "Non-cloud node retried without abandon"; new "Static node connected by orchestrator" scenario.
- Original scenarios 1-7 preserved verbatim; scenario 6 (Unknown cloud) correctly adds "is a non-None value".
- SHALL normative language consistent.
- No scope creep: only "Connect machine loop" requirement modified.
- All 9 scenarios use exactly 4 hashtags (####) + WHEN/THEN format.
- Structure improved: general → producer yields all → static handling → cloud handling.
- All scenarios testable (unit/integration/e2e mapping verified).

### 🟡 Addressed (fixed before freeze)
- Suggestion 1 (general grace-check statement reads as universal): qualified to "For cloud-provisioned nodes, on MachineConnectionError, the orchestrator SHALL compare the elapsed monotonic age against the node's cloud connect_grace" — makes the general rule self-contained before the static-node exception.

### 🔴 Outstanding
- None.

### Verdict
APPROVED — no blocking issues. specs/orchestrator/spec.md frozen after readability fix.

## tasks Round 4 — 2026-06-28

Reviewer: @k-reviewer-fast
Baseline: frozen proposal.md + frozen design.md + frozen specs/orchestrator/spec.md

### ✅ Strengths
- Comprehensive coverage: every change from frozen proposal/design/spec mapped to a task; no gaps.
- Fine granularity: each task 5-20 min (well under 2h OpenSpec limit).
- Correct dependency order: code → unit tests → e2e → spec sync → knowledge graph → verification.
- All checkbox format `- [ ] X.Y` parseable by apply phase.
- Verifiable: every task has clear completion criterion (grep, test pass, exit code).
- Consistent with design: Variant A (guard in consumer before grace-check), abandon_node unchanged, _connect_grace_for unchanged, CHANGE_SUMMARY justifies reversal of task 4.7 per Decision 4.
- Precise test details: tasks 2.2/2.4/2.5 specify mocking strategy, assertions, log checks.
- Line references verified: 2.1:15/19, 2.6:286, 5.1:527, 5.2:1215 match source.
- GRACE-lite markup complete: block renames (1.1/1.2), MODULE_CONTRACT SCOPE + VERSION (1.3), CHANGE_SUMMARY (1.4), MODULE_MAP + CHANGE_SUMMARY in test file (2.1).

### 🟡 Addressed
- None.

### 🔴 Outstanding
- None.

### Verdict
APPROVED — no blocking issues, no suggestions. tasks.md frozen.

## Final status
All 4 artifacts (proposal, design, specs, tasks) frozen after review. Change ready for /opsx-apply.
