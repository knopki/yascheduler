# Review Log — e2e-real-lifecycle

## proposal Round 1 — 2026-06-28

### 🔴 Fixed

N/A — first review of this artifact.

### 🟡 Addressed

N/A — no prior suggestions to incorporate.

### 🔴 Outstanding

None. No blocking issues found.

### 🟡 Suggestions (non-blocking)

1. **Output-file content assertion not mentioned in "What Changes"**
   - The brief's test phase 9 commits to checking each `1.input.out` exists with content `"hello e2e N"`. This is a core part of verifying the full lifecycle (output download). The proposal mentions distribution and log assertions but omits output-content verification.
   - **Recommendation**: Add a bullet such as: "Assert each task's output file exists and content matches its input."
   - Severity: non-blocking — the detail will be captured in spec.md, and "full lifecycle" implies output checking. Consider adding for completeness.

2. **Task-completion assertion not explicit**
   - The brief asserts "all 4 DONE, `context.error is None`". The proposal says "watch the daemon schedule the queued jobs" and "reject the 0:4/4:0 monopoly" but doesn't explicitly say the test waits for DONE and asserts completion before distribution check.
   - **Recommendation**: Add a bullet such as: "Poll DB until all tasks reach DONE (30s timeout); assert `context.error is None`." Or fold into the existing distribution bullet.
   - Severity: non-blocking — clearly implied by "full lifecycle" and spec detail.

### ✅ Verified Correct

- Entrypoints exercised via `_submit_async`, `_manage_node_async`, `make_daemon + orch.start()` — matches brief table.
- 4 jobs submitted BEFORE nodes added — matches brief test phase 2 vs 5-6.
- 2 SSH containers with one shared keypair — matches brief fixture design.
- Distribution invariant: set-equality `{ipA, ipB}` + reject 0:4/4:0, NOT exact 2:2 — matches brief rejected alternatives.
- Soft-remove for both nodes — matches brief test phases 10-11 and confirmed semantics.
- Log-tracking via in-memory `logging.Handler` — matches brief mechanism.
- No production-code changes, no new deps — matches brief scoping.
- Modified capabilities lists `e2e-testing`, new capabilities empty — correct.
- spec.md lines 36/41 bypass-path reference — verified against actual spec content.
- Impact section accurately lists `test_full_cycle.py` rewrite, `conftest.py` new fixtures, `spec.md` rewrite, no production code changes.
- No contradictions with explore-brief.md across any requirement.

### Recommendation

APPROVE WITH NOTES — the proposal is sound and captures all substantive commitments. The two suggestions above are minor completeness gaps; they can be resolved either by adding bullets to proposal.md or by trusting spec.md + implementation to carry the detail.

## proposal Round 1 — 2026-06-28 (post-fix)

### 🟡 Addressed
- "What Changes" now explicitly mentions the all-DONE wait + output-file content
  assertions (1.input.out exists with matching content).

### 🔴 Outstanding
- None — batch frozen.

## design Round 1 — 2026-06-28

### 🔴 Fixed
N/A — first review of this artifact.

### 🟡 Addressed
N/A — no prior suggestions for this artifact.

### 🔴 Outstanding
None. No blocking issues found. All eight decisions (D1–D8) are well-justified with rationale and alternatives. Every commitment from explore-brief.md is captured. The design is fully consistent with the frozen proposal.md — no decision-level contradictions. Goals/Non-Goals are accurate and aligned. Risks/Trade-offs are realistic and adequately mitigated. No internal inconsistencies. The batch can be frozen.

## specs Round 1 — 2026-06-28

### 🔴 Fixed

N/A — first review of this artifact.

### 🟡 Addressed

N/A — no prior suggestions for this artifact.

### 🟡 Suggestions (non-blocking)

1. **ssh_pool fixture description wording** (line 6)
   - The fixture description says "Each container yields its own `get_container_host_ip()` and mapped port 2222." This could be read as the containers yielding values directly, while the scenario (lines 19–24) correctly describes the fixture returning a list of dicts. The scenario is unambiguous, but the fixture line is slightly imprecise.
   - Suggestion: Rephrase to e.g. "The fixture yields a list of two dicts, each with host (from `get_container_host_ip()`), port (mapped 2222), username, and key_path." Or simply leave as-is — the scenario resolves any ambiguity.
   - Severity: trivial clarity nit. Not blocking.

### 🔴 Outstanding

None. No blocking issues found.

### ✅ Verified Correct

- Entrypoints via `_submit_async`, `_manage_node_async`, `make_daemon + orch.start()` — matches brief, proposal, design.
- 4 jobs submitted before nodes — steps 2 vs 4, matches brief phase 2 vs 5-6.
- 2 SSH containers, shared keypair, container IP separation — fixture + scenario, matches design D6.
- Distribution invariant: set equality + reject 0:4/4:0 — step 8 + scenario, matches design D4.
- Soft-remove path — step 10 + scenario, matches design D5.
- log_records fixture — fixture + scenario, matches design D7.
- CWD isolation per submit — step 2, matches design D8.
- No production-code changes — confirmed throughout.
- Output-file content assertion — step 7 + scenario, captured.
- All-DONE wait with 30s timeout — step 6, captured.
- context.error is None — step 7, captured.
- Stop daemon in finally — step 12, captured.
- Log assertions per task_id with both IPs — step 9 + scenario, captured.
- Task lifecycle TO_DO → RUNNING → DONE — scenario, captured.
- Engine deployment to both containers — scenario, captured (adapted from existing spec).
- TRUNCATE both tables in teardown — fixture line 9, captured.
- Correctly uses `## MODIFIED Requirements` (not `## ADDED Requirements`) — line 1.
- All 12 scenarios in WHEN/THEN format with `####` headings.
- All 3 requirements use SHALL.

### Recommendation

APPROVE — no blocking issues. The delta spec is complete, consistent with the frozen proposal and design, and captures every commitment from explore-brief.md. The batch can be frozen.


## tasks Round 1 — 2026-06-28

### 🔴 Fixed

N/A — first review of this artifact.

### 🟡 Addressed

N/A — no prior suggestions to incorporate.

### 🟡 Suggestions (non-blocking)

1. **Task 2.2 finally block lacks CancelledError/TimeoutError handling**
   - The task says: `try/finally` that calls `orchestrator.stop()` + `asyncio.wait_for(orch_task, timeout=10)`.
   - Both existing e2e tests (`test_full_cycle.py:148-152`, `test_consume_retry.py:314-318`) wrap the `wait_for` in `try/except (asyncio.CancelledError, asyncio.TimeoutError)` with `orch_task.cancel()`. Without this, a slow orchestrator shutdown (>10s) would raise an unhandled TimeoutError in the finally block, masking any test failure.
   - **Suggestion**: Amend task 2.2 to include the except clause as in the existing pattern:
     ```
     finally:
         await orchestrator.stop()
         try:
             await asyncio.wait_for(orch_task, timeout=10)
         except (asyncio.CancelledError, asyncio.TimeoutError):
             orch_task.cancel()
     ```

2. **Minor: task 2.1 test signature vs stdout capture mechanism**
   - Task 2.1 lists `async def test_full_cycle(..., monkeypatch, tmp_path)` without `capfd`. Task 2.3 offers both `capfd` and `contextlib.redirect_stdout` as alternatives.
   - If the implementer prefers `capfd`, they must add it to the signature in 2.1. If they use `redirect_stdout`, no change needed.
   - **Suggestion**: Either add `capfd` to the 2.1 signature for clarity, or settle on one mechanism in 2.3 to avoid ambiguity. Non-blocking — the implementer can resolve either way.

3. **Spec drift note (informational — for task 3.1)**
   - The frozen spec (line 11) requires a "Function-scoped orchestrator fixture that creates but does not start an Orchestrator instance" in conftest.py. No task implements this — the design and tasks intentionally create the orchestrator directly in the test body (task 2.2).
   - Task 3.1 (spec drift verification) should update the spec to remove this fixture requirement, since it's unused.
   - Not a tasks.md issue; flagged so 3.1 doesn't overlook it.

### 🔴 Outstanding

None. No blocking issues found.

### ✅ Verified Correct

- All 21 tasks are in `- [ ] X.Y description` checkbox format.
- Tasks are ordered by dependency: fixtures (1.x) → test rewrite (2.x) → spec verification (3.x) → validation (4.x).
- Every section-2 step maps 1:1 to the 12 frozen spec steps and the 13 explore-brief test phases.
- Every fixture from the explore-brief (ssh_pool, log_records, e2e_config modified) has a dedicated task.
- test_consume_retry.py backward compatibility covered (1.2 wrapper + 1.4 verification).
- GRACE-lite markup covered for both test file (2.11) and conftest (4.1).
- All validation tasks covered (3.2, 4.2–4.5).
- All tasks are small (< 2 hours) and individually verifiable.
- No production-code changes implied by any task.
- Every commitment from explore-brief, proposal, design, and spec is captured in the task list.

### Recommendation

APPROVE — no blocking issues. The batch can be frozen.

## tasks Round 1 — 2026-06-28 (post-fix)

### 🟡 Addressed
- Task 2.1 signature now includes `capfd` (settled on the capfd mechanism for stdout capture).
- Task 2.2 finally block now includes `except (asyncio.CancelledError, asyncio.TimeoutError): orch_task.cancel()` matching the established pattern.
- Task 3.1 "orchestrator fixture" concern: the existing `openspec/specs/e2e-testing/spec.md` already lists an orchestrator fixture (pre-existing, carried over in the MODIFIED requirement); no new work needed — task list unchanged on this point.

### 🔴 Outstanding
- None — batch frozen. Change is ready for /opsx-apply.
