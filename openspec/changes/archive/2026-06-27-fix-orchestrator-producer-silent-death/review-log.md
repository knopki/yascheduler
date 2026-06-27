# Review Log — fix-orchestrator-producer-silent-death

## proposal Round 1 — 2026-06-26 (k-reviewer-fast)

### ✅ Confirmed
- All 11 explore-brief commitments captured (problem mechanism, 4 producers + sources, _print_stats defect, rejected alternatives A/E not adopted, approach B+C with BaseException-vs-Exception reasoning, open questions resolved/out-of-scoped, test surface, capabilities scoped to orchestrator-only, why concise, no new capabilities).

### 🔴 Outstanding
- None.

### 🟡 Addressed
- Line-number references in proposal match brief ranges; treated as approximate anchors to confirm during design.
- Brief's "Mapping to existing patterns" (consumer try/except precedent) correctly excluded as design-level detail.

### Outcome
PROPOSAL FROZEN. Proceeding to design.md (batch 2).

## design Round 1 — 2026-06-26 (k-reviewer-fast)

### ✅ Confirmed
- All 11 brief commitments captured: problem mechanism (3 chains), 4 producers + sources, _print_stats target, rejected A (why: cancels alive workers + duplicates CancelledError drain) + E/C (overengineering), approach B+C with BaseException-vs-Exception reasoning (CancelledError BaseException since 3.8; pyproject requires >=3.9), open questions all resolved, no new deps, no public surface change, out-of-scope items match proposal exactly.

### 🟡 Addressed
- Reviewer flagged `queue.name` in log snippet — but `UniqueQueue.__init__` (queue.py:85) sets `self.name = name`, so `.name` IS valid for the orchestrator's queues. No edit needed; flag is unfounded for this codebase.
- No GRACE-lite/test section in design — acceptable, scoped to proposal Impact + tasks.

### 🔴 Outstanding
- None.

### Outcome
DESIGN FROZEN. Proceeding to specs/ (batch 3).

## specs Round 1 — 2026-06-26 (k-reviewer-fast)

### ✅ Confirmed
- All 5 key commitments present as requirements: try/except Exception on producer, CancelledError preserves graceful drain (BaseException since 3.8), workers registered in self._bg_jobs, double-cancel idempotency, _print_stats same treatment.
- ADDED vs MODIFIED correct: main orchestrator spec has no "Producer error resilience" requirement → genuinely new → `## ADDED Requirements` header is right.
- Scenario format: all 5 scenarios use exactly `####`, WHEN/THEN format, each requirement has ≥1 scenario.
- Testability: each scenario is concrete and testable.
- Normative language: SHALL/SHALL NOT consistent, no should/may.
- No implementation detail (private method names are minimal contract identifiers).
- Explore-brief coverage: all 5 items captured (4 producers' sources, _print_stats, worker registration, CancelledError drain, double-cancel idempotency).

### 🟡 Addressed
- None — not even minor.

### 🔴 Outstanding
- None.

### Outcome
SPECS FROZEN. Proceeding to tasks.md (batch 4).

## tasks Round 1 — 2026-06-26 (k-reviewer-fast)

### ✅ Confirmed
- All 3 decisions + GRACE-lite + static checks covered:
  - Decision 1 (try/except Exception on producer): tasks 1.1-1.3
  - Decision 2 (workers in _bg_jobs): tasks 2.1-2.3
  - Decision 3 (_print_stats resilience): tasks 3.1-3.3
  - GRACE-lite markup: tasks 4.1-4.5
  - Static checks: tasks 7.1-7.9
- 5 spec scenarios → 7 test tasks (complete mapping): S1→5.2, S2→5.3, S3→5.5, S4→5.6, S5→6.1, plus bonus 5.4 (Decision 2 verify) + 6.2 (stats CancelledError propagation).
- Out-of-scope items excluded (consecutive-failure counter, _await_first_machine).
- Explore-brief open questions resolved: test surface → tasks 5.2-6.2; worker registration location → _bg_jobs per task 2.1.
- Format: all tasks `- [ ] N.M` under `## N.` headings; no malformed checkboxes.
- Granularity: all tasks ≤2 hours; all verifiable.
- No implementation-level overspecification (file paths + function names + marker names, not full code).

### 🟡 Addressed
- Task 5.1 file-name pattern "test_orchestrator*" doesn't match existing `test_application_orchestrator.py`, but the "if present" guard makes it clear → implementer creates a new file. No change needed.
- Task 5.4 test complexity (needs Orchestrator instantiation + mocks) — task correctly asserts WHAT not HOW. Appropriate granularity.

### 🔴 Outstanding
- None.

### Outcome
TASKS FROZEN. All 4 batches complete. Change ready for implementation via /opsx-apply.