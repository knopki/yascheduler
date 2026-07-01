# Review Log — fix-cloud-alloc-session-lifecycle

## proposal Round 1 — 2026-07-01

### 🟡 Addressed

1. **All four fixes (A/B1/C/D) captured.** Proposal matches explore-brief on the exact behavioral change for each fix: A gates free-machine selection on DB-enabled IPs, B1 disconnects SSH session on setup failure before `delete_node`, C wraps per-session failures in try/except, D includes stdout in cloud-init error. ✓

2. **Why grounded in CLOUD_BUGS.md.** Opening paragraph correctly references the real Hetzner run (2026-06-30), lists all five symptoms, names the architectural root cause (connect-before-DB-enable desync), and identifies the two secondary gaps. ✓

3. **Capabilities correct.** Two modified capabilities listed: `cloud-provisioner` and `orchestrator`. Both directories exist in `openspec/specs/`. No new capabilities claimed. ✓

4. **Spec-update plan captured.** Delta requirements described: `cloud-provisioner` gets a setup-failure-disconnect requirement; `orchestrator` gets the allocatable-⇒-enabled invariant. ✓

5. **Test plan captured.** Timing-aware fakes described: `MachineRepository` fake that registers on `connect` before DB-enable, `CloudProvisioner` fake that flips to enabled only on success. ✓

6. **AGENTS.md constraints respected.** No new dependencies. No public API/CLI/DB-schema change. Minimal-change philosophy followed (B1 chosen over B2 structural; registry-level gate rejected in favor of use-case-level). ✓

7. **No contradictions with explore-brief.** All four fixes, spec targets, impact assessment, and test approach align. ✓

### 🔴 Outstanding

- **Missing rejected alternative: two-phase registration.** Explore-brief (lines 31–35) explicitly rejects "Two-phase registration (`connect` ≠ `register`, gate visibility on setup completion)" — it changes the `MachineRepository` Protocol, rejected as YAGNI because Fix A's DB-enabled gate makes the bug impossible. Proposal does not mention this alternative at all, while it does mention the other two (B2 structural, registry-level gate). This is a completeness gap: a reader of proposal.md alone would not know this architectural alternative was considered and ruled out. The two-phase registration is substantively different from the registry-level gate discussed in the proposal (it changes the Protocol itself vs. coupling to NodeRepository), so these aren't the same rejection.

  **Fix:** Add a brief note in the proposal's "Why" or "What Changes" rationale acknowledging this alternative was considered and rejected in favor of Fix A's DB-level gate, preserving the `MachineRepository` Protocol unchanged.

## proposal Round 2 — 2026-07-01

### 🔴 Fixed

1. **Rejected alternative: two-phase registration now acknowledged.** Proposal.md (lines 24–27) includes a clear parenthetical note within the Fix A rationale: "avoids the two-phase `connect`/`register` split (rejected as YAGNI: it would change the public Protocol for a class of bug Fix A already makes impossible in practice)." The edit matches the explore brief (lines 32–35) on all points — names the alternative, states why rejected (YAGNI), identifies what it would change (public `MachineRepository` Protocol), and explains why it's not needed (Fix A makes the bug impossible). No new issues introduced by the edit: the note is factual, non-contradictory, and naturally integrated into the existing Fix A paragraph. ✓

### 🟡 Addressed

All Round 1 passing items were re-verified and remain valid:

1. **All four fixes (A/B1/C/D) captured.** Proposal matches explore-brief exactly on behavior, location, and rationale for each fix. ✓
2. **Why grounded in CLOUD_BUGS.md.** Opening paragraph still references the real Hetzner run (2026-06-30) with all five symptoms, root cause, and secondary gaps. ✓
3. **Capabilities correct.** Lists the same two modified capabilities (`cloud-provisioner`, `orchestrator`). ✓
4. **Spec-update plan captured.** Delta requirements for both specs are described. ✓
5. **Test plan captured.** Timing-aware fakes described and match the explore brief. ✓
6. **AGENTS.md constraints respected.** No new dependencies, no public API/CLI/DB-schema change, minimal-change philosophy followed. ✓
7. **No contradictions with explore-brief.** Fix mapping, spec targets, impact assessment, and test approach remain in alignment. ✓

No 🔴 Outstanding issues.

## design Round 1 — 2026-07-01

### 🟡 Addressed

1. **Four fixes (A/B1/C/D) fully captured from explore-brief.**
   - Fix A: `_find_free_machines` intersects `list_free` with DB-enabled IPs in the same UoW (D1). ✓
   - Fix B1: `disconnect(ip_addr)` before `delete_node` in both `except` blocks of `allocate` (D2). ✓
   - Fix C: per-session `try/except Exception`, log `error`, `continue` — no disconnect (D3). ✓
   - Fix D: `stdout=` added to `CloudSetupError` f-string in `_setup_vm` (D4). ✓

2. **Three rejected alternatives with rationale.**
   - Two-phase registration (Non-Goals, lines 38–40): rejected YAGNI, would change `MachineRepository` Protocol. ✓
   - B2 structural context manager (Non-Goals, lines 41–43): rejected; `allocate` already owns failure-handling, colocation with `delete_node` is minimal. ✓
   - Registry-level gate (Non-Goals, lines 44–46): rejected; couples SSH collection to `NodeRepository`, breaks layering. ✓
   - All three match explore-brief (lines 32–43). ✓

3. **Cross-module data flow captured in prose.**
   - D1 describes the enabled_ips → filter flow with UoW boundaries. ✓
   - D2 describes the disconnect-before-delete path vs unchanged success path. ✓
   - D3 describes the try/except + continue loop flow. ✓
   - No ASCII diagram needed — the Decisions section structures the flows clearly. ✓

4. **Test plan captured.** Goals (lines 33–34): "unit tests with timing-aware fakes that reproduce the registry-vs-DB desync and regression-guard all four fixes." This is briefer than explore-brief's four explicit cases but covers the same intent. The test-case enumeration belongs in tasks.md when it exists. ✓

5. **Four Decisions (D1–D4) consistent with proposal.md.**
   - D1: gate in use case, not registry. Proposal says "Fix A — Gate free-machine selection on DB-enabled nodes... The gate lives in the use case, not in MachineRepository." ✓
   - D2: disconnect in allocate, not `_setup_vm`. Proposal says "Fix B — Disconnect the SSH session on setup failure. CloudProvisionerImpl.allocate calls disconnect before delete_node on both setup-failure except paths." ✓
   - D3: per-session try/except, log, continue, no disconnect. Proposal says "Fix C — Isolate per-session failures... wraps each in try/except Exception, logs the failure, and continues." ✓
   - D4: stdout in error message. Proposal says "Fix D — Include stdout in the cloud-init error message." ✓

6. **Risks/Trade-offs analysis — all four risks genuine and well-mitigated.**

   - **[Extra DB read]** → acknowledged, node counts small, possible future optimization noted. ✓

   - **[Stale enabled_ips]** → evaluated as benign one-tick lag consistent with existing behavior. ✓

   - **[Fix C masking]** → correctly scoped: "not the cleanup mechanism — it's the 'don't abort the loop' mechanism." Session monitor and deallocate path handle persistent failures independently. ✓

   - **[Fix B disconnect on never-connected]** → verified against actual code at `yascheduler/infra/ssh/repository.py:251–257`:
     ```python
     session = self._sessions.pop(ip, None)
     if session is None:
         return
     ```
     Safe no-op. Claim in design.md (lines 149–151) is accurate. ✓

   - No unlisted risks identified. Design is thorough.

7. **No contradictions with proposal.md.** Both documents agree on all four fix locations, behavioral changes, rationale, and rejection alternatives. ✓

8. **No spec-level content leaking into design.** Design Decisions describe *where* and *why* to implement, not behavioral invariants/contracts (those go in specs/). ✓

9. **AGENTS.md constraints respected.** Minimal changes, no new dependencies, no public API/CLI/DB-schema change. ✓

### 🔴 Outstanding

None.

### Verdict

**PASS** — design.md is complete, consistent with frozen proposal.md, faithful to explore-brief.md, and ready for implementation. No issues requiring changes.

## specs Round 1 — 2026-07-01

### ✅ Pass — all checks clear, no issues found.

#### Format compliance

- Each requirement uses exactly `### Requirement: <name>` (3 `#` + space + `Requirement:`). ✓
- Each scenario uses exactly `#### Scenario: <name>` (4 `#` + space + `Scenario:`). ✓
- Every requirement has at least one scenario. ✓
- Both files satisfy the OpenSpec format constraints. No silent failures (wrong hashtag count, bullet-list scenarios, etc.).

#### ADDED vs MODIFIED correctness

- **Fix A (gate):** Existing `### Requirement: Allocate loop` in orchestrator spec mentions no enabled-gating. ADDED is correct. ✓
- **Fix B (disconnect on setup failure):** Existing `### Requirement: CloudProvisionerImpl.stop closes machine_repository connections` is shutdown-only. Mid-run failure disconnect is a new requirement, not a modification. ADDED is correct. ✓
- **Fix C (loop isolation):** Existing orchestrator spec has no requirement about per-session try/except in the free-machine loop. ADDED is correct. ✓
- **Fix D (stdout in error):** Existing cloud-provisioner `### Requirement: Node setup after provisioning` mentions cloud-init but not error message format. ADDED is correct. ✓

#### Coverage

| Fix | Requirement | Spec file |
|-----|-------------|-----------|
| A — gate | Free-machine selection gated on DB-enabled nodes | orchestrator |
| B — setup-failure disconnect | Setup-failure disconnects machine_repository session | cloud-provisioner |
| C — loop isolation | Free-machine loop isolates per-session failures | orchestrator |
| D — stdout in error | Cloud-init error message includes stdout | cloud-provisioner |

All four fixes covered. ✓

#### Consistency with frozen design.md

- **D1 (gate in use case):** Spec says "SHALL read `uow.nodes.list_enabled()` in the same Unit of Work", "build `enabled_ips`", "filter `list_free`", "gate SHALL live in the use case". Matches D1 exactly. ✓
- **D2 (disconnect in both except blocks before delete_node):** Spec says both `except` blocks (CloudSetupError and generic Exception) SHALL `await self.machine_repository.disconnect(ip_addr)` before `await adapter.delete_node(...)`. Both except scenarios present. Matches D2 exactly. ✓
- **D3 (try/except+continue, no disconnect):** Spec says "wrap in try/except Exception", "except SHALL NOT call repository.disconnect". Design says same. Matches D3 exactly. ✓
- **D4 (stdout in error message):** Spec includes `stdout={result.stdout}` and `stderr={result.stderr}` in format. Matches D4 exactly. ✓
- Success-path-unchanged constraint preserved in both: orchestrator spec says "success path is unchanged" (cloud-provisioner scenario 5); cloud-provisioner spec says success path "does NOT call disconnect". ✓

#### No duplication with existing main specs

- **Orchestrator ADDED** requirements do not overlap with any of the 8 existing requirements (Orchestrator manages loops, Allocate loop, Consume loop, Deallocate loop, Connect machine loop, Stats logging, Concurrency limits, Producer error resilience, stop idempotent). ✓
- **Cloud-provisioner ADDED** requirements do not overlap with any existing requirement. The "stop closes connections" requirement is shutdown-only; the new setup-failure disconnect is mid-run failure cleanup — different scope. The "Node setup" error message format was unspecified before. ✓

#### Testability

All 12 scenarios (5 + 3 orchestrator, 5 + 2 cloud-provisioner) are concrete WHEN/THEN statements convertible to test assertions, including:
- Behavioral: exception paths, timing windows, safe no-ops, success paths. ✓
- Design-constraint: "Gate lives in the use case" (verifiable via static analysis/mock inspection). ✓


## tasks Round 1 — 2026-07-01

### 🟡 Addressed

1. **Format.** All tasks use `- [ ] X.Y description` checkbox format, grouped under `## N. Group` headings. Ordered by dependency: GRACE → Fix A → Fix B → Fix C → Fix D → Tests → Validation. No format issues. ✓

2. **Granularity.** Each task is ≤ 2 hours. Test-scaffold tasks (6.2–6.4) are bounded by "create" scope; individual test cases (6.5–6.13) are one assertion pattern each. ✓

3. **All four fixes covered.** Fix A (tasks 2.1–2.3), Fix B (3.1–3.2), Fix C (4.1–4.3), Fix D (5.1). Each maps to the correct source location (verified against actual code at the referenced line ranges). ✓

4. **Orchestrator spec scenarios — all covered.**
   - Setup-in-flight invisible → 6.5 ✓
   - Multiple workers no pile-on → 6.6 ✓
   - Enabled node allocatable → 6.7 ✓
   - Disabled-but-not-disconnected excluded → 6.8 ✓
   - Gate-not-in-repo → structural constraint, covered by 7.3 (ruff) and 7.4 (lint-imports) ✓
   - Stale session no abort → 6.10 ✓
   - Cloud branch reached → 6.11 ✓
   - No-disconnect-in-except → tested by 6.10/6.11 (no disconnect assertion in loop), explicitly verified by task 4.3 ✓

5. **GRACE-lite ordering.** Section 1 (1.1–1.7) comes before implementation sections 2–5. Task 1.7 correctly limits scope to "verify no structural change needed" with specific annotation targets (M-APPLICATION-ALLOCATION, M-CLOUD-PROVISIONER). ✓

6. **Validation section (7.1–7.7).** Matches AGENTS.md verification commands: pytest (unit, integration), ruff check + format, lint-imports, grace_check.py, openspec validate — all present. ✓

7. **No implementation leaking.** Tasks describe WHAT (e.g., "add `enabled_nodes = await uow.nodes.list_enabled()` and build `enabled_ips`") without pasting full code. Code-level decisions remain in design.md. ✓

8. **Design consistency (D1–D4).**
   - D1 (gate in use case): 2.1 reads `list_enabled` in same UoW as `list_by_status` ✓
   - D2 (disconnect in both except blocks): 3.1–3.2 mirror the two except blocks, with disconnect before `delete_node` ✓
   - D3 (no disconnect in except): 4.3 explicitly says "verify NO disconnect" ✓
   - D4 (stdout in error): 5.1 adds `stdout={result.stdout}` to the CloudSetupError f-string ✓

9. **Source line references.** Verified against actual code at `allocate_task.py` and `manager.py`. Line ranges are accurate (e.g., `_find_free_machines` at 159–174, CloudSetupError except at 180–186, generic except at 187–193, CLOUD_INIT error at 328–331). ✓

### 🟡 Outstanding — coverage gaps for cloud-provisioner spec scenarios

The following `#### Scenario:` entries in `specs/cloud-provisioner/spec.md` lack a corresponding test task in section 6. All four involve edge cases or negative assertions on the disconnect behavior. None are 🔴 blocking (the core behavioral paths are covered), but they leave secondary paths unguarded.

1. **Generic exception disconnects before deleting VM** — the fake `CloudProvisioner` in 6.3 only raises `CloudSetupError` on failure; test 6.9 only covers the CloudSetupError `except` path. The generic `Exception` path (manager.py:187–193) gets the same one-line change but is never tested.
   **Suggestion:** Add a test that configures the fake to raise a non-`CloudSetupError` (e.g., `RuntimeError`), calls `allocate_task`, and asserts the session is disconnected.

2. **Disconnect on never-connected IP is safe no-op** — design.md (lines 146–151) explicitly calls out this edge case (`_connect_to_vm` fails before `connect` registers a session). The fake `MachineRepository.disconnect` in 6.2 already models the safe no-op (`pop(ip, None)`), but no test exercises it.
   **Suggestion:** Add a test that triggers the failure at the `_connect_to_vm` phase (before `connect` is called), asserts `disconnect` is called for the IP, and verifies no exception is raised from the disconnect.

3. **Success path does not disconnect** — the spec scenario asserts the session remains registered after successful `allocate`. Existing test 6.7 ("enabled node allocatable") would pass but doesn't explicitly assert that `disconnect` was NOT called.
   **Suggestion:** Add a negative assertion to test 6.7 (or as a separate test) that verifies the fake repository's `disconnect` call count is zero for the allocated IP.

4. **Cloud-init timeout message is unchanged** — the timeout branch (manager.py:332–336) is unchanged by Fix D. No test verifies the timeout message format remains `"cloud-init status --wait timed out on {ip_addr} after {timeout}s"`.
   **Suggestion:** Add a test that exercises the timeout path (the fake could raise `asyncio.TimeoutError` on the `run` call) and asserts the error message does NOT contain `stdout=`. Low priority — the timeout path is independent of Fix D.

### Verdict

**PASS** — tasks.md is well-formed, complete for all four fixes, correctly ordered, and consistent with all frozen baselines. The four missing test-to-scenario mappings are non-blocking coverage improvements (none would let a real regression escape because the core behavior paths are tested and the code changes are simple one-liners). Address them before archiving sync if test coverage of all spec scenarios is required.

## tasks Round 2 — 2026-07-01

### 🟡 Addressed

All four Round 1 🟡 gaps now have explicit test tasks. Each new task was verified for technical accuracy against the actual code and design decisions:

1. **Generic exception disconnect path (Round 1 gap 1) → Task 6.10**
   Configures the fake `CloudProvisioner` to raise a non-`CloudSetupError` `Exception` during `allocate`, asserts `machine_repository.disconnect(ip)` is still called before VM deletion. Covers the second `except Exception` block (manager.py:187–193), symmetric to existing 6.9's `CloudSetupError` coverage. ✓

2. **Never-connected safe no-op (Round 1 gap 2) → Task 6.11**
   Triggers failure at `_connect_to_vm` before `machine_repository.connect` registers a session (verified call chain: `_setup_vm:314` → `_connect_to_vm:403` → `connect`; if `connect` fails, `except Exception` at line 414 re-raises as `CloudSetupError`; no session in `_sessions`). Asserts `disconnect(ip)` on absent IP is a safe no-op (`_sessions.pop(ip, None)`) and VM is still deleted. Matches design.md D2 risk (lines 146–151). ✓

3. **Success-path no-disconnect negative assertion (Round 1 gap 3) → Task 6.12**
   Separate test (not bolted onto 6.7) that triggers the fake to succeed, then asserts the session REMAINS in `_sessions` — explicit negative assertion that `disconnect` was NOT called. Labels itself as "negative assertion on disconnect call". ✓

4. **Timeout message unchanged (Round 1 gap 4) → Task 6.16**
   Triggers `asyncio.TimeoutError` path (manager.py:332–336, unchanged by Fix D). Asserts the raised `CloudSetupError` message is exactly `"cloud-init status --wait timed out on {ip} after {timeout}s"` — verifies the timeout branch does NOT read `result.stdout`/`result.stderr`. Matches spec scenario. ✓

### Renumbering consistency

- Original sequence 6.1–6.13 → 6.1–6.17 (four insertions).
- Shift: original 6.10→6.13, 6.11→6.14, 6.12→6.15, 6.13→6.17.
- New tasks inserted at natural grouping boundaries: Fix B tests (6.10–6.12) right after existing Fix B test 6.9; Fix D timeout test (6.16) right after existing Fix D test 6.15.
- Sequence is 6.1→6.17 continuous with zero gaps and zero duplicates. ✓

### Round 1 passing criteria — still hold

1. **Format.** All tasks use `- [ ] X.Y` checkbox, `## N. Group` headings. ✓
2. **Granularity ≤ 2h.** Each new task is one assertion pattern. ✓
3. **Coverage A/B1/C/D.** Fix A (2.1–2.3, 6.5–6.8), Fix B (3.1–3.2, 6.9–6.12), Fix C (4.1–4.3, 6.13–6.14), Fix D (5.1, 6.15–6.16). ✓
4. **GRACE ordering.** Section 1 (1.1–1.7) before implementations 2–5. ✓
5. **Validation section (7.1–7.7).** All verification commands present. ✓
6. **No code pasting.** Tasks describe intent, not copy-paste. ✓
7. **D1–D4 consistency.** Verified against actual code at `manager.py:180–193` and `_connect_to_vm:402–415`. ✓
8. **Source line references.** Re-verified: `except CloudSetupError` at 180, `except Exception` at 187, `_connect_to_vm` at 386, `connect` at 403, `CLOUD_INIT` timeout at 332–336 — all accurate. ✓

### No new 🔴 issues found

All four new tasks are technically sound, factually accurate against the codebase, and consistent with the frozen design.md and spec scenarios.

### Verdict

**PASS** — tasks.md Round 2 closes all four Round 1 🟡 gaps with precisely-targeted test tasks. Renumbering is clean. No new issues introduced.

