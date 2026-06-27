# Review Log — decompose-ssh-gateway

## proposal Round 1 — 2026-06-27T12:00:00Z

### 🔴 Fixed

1. **Incomplete consumer list in UPDATE call sites** (proposal.md:54-59)
   **Location:** `openspec/changes/decompose-ssh-gateway/proposal.md` lines 54-59
   **Problem:** The proposal lists 5 files to update (orchestrator.py, manager.py, di.py, check_status.py, manage_node.py) and later says "internal consumers are listed above" (line 118). But 4 additional application-layer files import and type-annotate `MachineGateway` and will break when the Protocol is removed:
   - `application/allocate_task.py` — imports `MachineGateway`, uses `gateway: MachineGateway` in 5+ function signatures (lines 51, 118, 161, 188, 448)
   - `application/consume_task.py` — imports `MachineGateway`, uses `gateway: MachineGateway` (lines 34, 213)
   - `application/deallocate_nodes.py` — imports `MachineGateway`, uses `gateway: MachineGateway` (lines 31, 52)
   - `application/abandon_node.py` — imports `MachineGateway`, uses `gateway: MachineGateway` (lines 29, 53)
   
   These are not just "call sites" — they are consumer files whose imports and type annotations will raise `ImportError` when `MachineGateway` is deleted from `domain/ports.py`. The proposal must either list them explicitly or clarify that they are implicitly covered by the orchestrator.py update (and note that their `MachineGateway` imports + type annotations need replacing with the two new Protocols).
   **Fix:** Add the missing files to the UPDATE bullet, or add a note that all `MachineGateway` type annotations in `application/` are updated as part of the orchestrator refactor, with the 4 files enumerated.

2. **`_safe_b64decode` in test migration is misleading** (proposal.md:61)
   **Location:** `openspec/changes/decompose-ssh-gateway/proposal.md` line 61
   **Problem:** The proposal says tests "import `_write_remote_file`/`_safe_b64decode` from `infra/ssh/operations/deployment`". However, no test file imports `_safe_b64decode` (confirmed via grep). Only `_write_remote_file` is imported by tests. Including `_safe_b64decode` in the migration list implies a test dependency that doesn't exist.
   **Fix:** Remove `_safe_b64decode` from the test-migration bullet, or clarify it is listed for completeness (the function moves with the deployment module even though no test directly imports it). This is minor but factually inaccurate.

### 🟡 Addressed

1. **Alternatives A/B/C/D/E not mentioned in proposal**
   The explore-brief enumerates 5 alternatives with detailed reasoning. The proposal does not reiterate them. This is correct behavior — the proposal explains WHY (the problem) and WHAT (the split), not how the decision was reached. Alternatives belong in explore-brief and design.md. ✅ Correctly deferred.

2. **Method mapping table not included**
   The explore-brief's detailed `method → destination` table (30+ rows) and the `helpers.py` dissolution table are absent from the proposal. Correctly deferred — the granular mapping belongs in design.md. The proposal captures the split structure and the helpers migration by concern (lines 41-46) at the right level of detail. ✅

3. **Cross-module flow diagrams, call-graph matrix, open questions not included**
   All correctly deferred to design.md. The proposal captures the WHAT without implementation detail. ✅

4. **Composition vs inheritance decision not explicitly stated**
   The explore-brief makes an explicit "composition NOT inheritance" decision. The proposal doesn't state this, but the described structure (three sibling sub-collaborators `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`) implies composition. The wording "three sibling use-case collaborators" (line 33-40) is clear enough. ✅

5. **Accessor getter destination alignment** (proposal.md:24-25 vs explore-brief)
   The proposal lists `get_path`/`get_quote`/`get_engines_dir` as repository accessors. The explore-brief maps these identically. Consistent. ✅

### 🔴 Outstanding

- **Issue #1 (missing consumers) remains open** — the proposal needs to add the missing `application/` files to the UPDATE call sites list.
- **Issue #2 (safe_b64decode claim) remains open** — needs correction or clarification.

### Summary

- 🔴 Fixed: 2 issues identified (missing consumers, safe_b64decode claim)
- 🟡 Addressed: 5 items verified as correctly deferred
- 🔴 Outstanding: 2 issues requiring another round

## proposal Round 2 — 2026-06-27T15:45:00Z

### 🔴 Fixed
1. **Missing Protocol-typed consumer files** — Round 1 issue #1 resolved. Proposer added a dedicated "Protocol-typed call sites" bullet (lines 61–67) listing all 4 previously omitted files (`allocate_task.py`, `consume_task.py`, `deallocate_nodes.py`, `abandon_node.py`) plus `orchestrator.py` (which legitimately appears in both lists). The "APIs" impact section (lines 127–131) now enumerates all 6 modules. Verified via grep: exactly 5 files in `application/` import `MachineGateway`, matching the claim.

2. **`_safe_b64decode` test migration claim** — Round 1 issue #2 resolved. Lines 72–73 now state: "(`_safe_b64decode` is private to the deploy module and not imported by any test; no test migration needed.)" Verified via grep: no test file imports `_safe_b64decode`. ✓

### 🟡 Addressed
No new non-blocking refinements this round.

### 🔴 Outstanding
None. Both round-1 issues confirmed fixed. No new issues introduced.

### Factual Accuracy Re-confirmed
- `gateway.py` = 1020 ln, `helpers.py` = 171 ln ✅
- Dead duplicate `my_backoff_exc` in `helpers.py` (gateway.py:87–92 is canonical; gateway imports neither `my_backoff_exc` nor `my_backoff_sftp` from helpers) ✅
- 7 unit test files, 1 integration, 2 e2e as claimed ✅
- 5 protocol-typed application files + `domain/ports.py` as claimed ✅
- Behavioral call sites (5 files) and protocol-typed call sites (5 files) correctly distinguished ✅

### Baseline Coverage Intact
Alternatives A/B/C/D/E, mapping tables, cross-module flows, call-graph matrix, composition-vs-inheritance decision, open questions — all correctly deferred to `design.md` / `tasks.md`. No scope creep.

### Batch Verdict: **PASS** — ready to freeze.

## design Round 1 — 2026-06-27T16:30:00Z

### Baseline Coverage (explore-brief.md)

- **Alternatives A/B/C/D/E**: design.md §Context (L23–24) references explore-brief for full analysis and states E is implemented. D1–D9 collectively encode E's rationale. The decision-level "why over others" is implicit in D1 (principal seam), D3 (composition not inheritance), D4 (helpers dissolution). ✅
- **Method → destination mapping table**: D1 (L64–82) enumerates repository methods; D3 (L136–150) enumerates operations methods. Matches explore-brief table 1:1. ✅
- **helpers.py dissolution table (D4)**: L180–198. Every symbol destination matches explore-brief table. Design.md adds specific module names (`registry.py`, `detect.py`, `paths.py`) — refinement, not contradiction. ✅
- **Two new Protocols (D8)**: L283–350. `MachineRepository` and `MachineOperations` with full method lists. Both `@runtime_checkable`. Matches proposal and explore-brief. ✅
- **Composition/DI (D3, D5, D7)**: D3 composition over inheritance ✅; D5 narrow local protocols for collaborators ✅; D7 public re-exports from `infra/ssh/__init__.py` ✅. All match proposal.
- **Cross-module data flows**: Embedded in D1/D2 (monitor lifecycle) and D3 (deploy/download/occupancy call flows). No standalone flow diagram section needed — decision descriptions capture the paths. ✅
- **Acyclic call-graph**: Implicit in D6 (`_make_run_fn` in `platform/` keeps repo and ops independent). No cycles possible in the described structure. ✅
- **Open questions from explore-brief**: Q1 (`_make_run_fn`) → D6 ✅; Q2 (sub-objects vs flat) → Q3 ✅; Q3 (re-exports) → D7 ✅; Q4 (test imports) → Risks + Q5 ✅; Q5 (knowledge graph) → Risks section L446–453 (mitigation: tasks.md). All resolved or deferred with clear rationale.

### Factual Accuracy (verified against codebase)

- `gateway.py` = 1020 ln ✅, `helpers.py` = 171 ln ✅
- `my_backoff_exc` duplicate in `helpers.py:93–95` confirmed dead (canonical in `gateway.py:87–92`) ✅
- `MachineGateway` Protocol in `domain/ports.py:123–202` has exactly the methods design.md D8 splits across two Protocols ✅
- 6 internal modules reference `MachineGateway` (5 in `application/` + `domain/ports.py`) ✅
- AiiDA plugin does NOT import `MachineGateway` ✅
- CLI `check_status.py` uses: `connect`, `disconnect`, `get_path`, `get_sftp`, `_get_machine_state`, `run_full`, `get_quote` — spans both repository and operations ✅
- CLI `manage_node.py` uses: `connect`, `setup_node`, `disconnect` — spans both ✅
- `CloudProvisionerImpl` uses: `connect`, `run`, `setup_node`, `get_cpu_cores`, `disconnect_all` — spans both ✅
- `di.py` constructs `SSHMachineGateway(log=log)` once and passes `gateway=gateway` to Orchestrator, `machine_gateway=gateway` to CloudProvisionerImpl ✅
- Four `_bg_tasks` invariants (replace-prior, identity-checked done-callback, IP-keyed dict, pop-before-await) confirmed in `gateway.py:879–894` and `test_ssh_gateway_bg_tasks.py` ✅

### Design-Doc-Specific Checks

- **Context** (L1–24): Factually correct. ✅
- **Goals / Non-Goals** (L26–59): 6 goals, 7 non-goals. All crisp, aligned with proposal scope. No scope creep. ✅
- **Decisions D1–D9**: Each has decision + WHY + alternative considered + rejection reason. ✅
- **Risks / Trade-offs** (L388–466): 6 risks each with concrete mitigation. 2 trade-offs acknowledged. All realistic. ✅
- **Migration Plan** (L469–477): Pure refactor, git revert rollback, single PR, no DB/config migration. ✅
- **Open Questions Q1–Q5** (L479–545): Each answered or explicitly deferred. None block implementation. ✅
- **No WHY duplication**: Context references proposal briefly; no re-hashing. ✅
- **No full code**: Only small pseudocode snippets for architecture illustration. ✅
- **Behavior contracts preserved**: All spec.md contracts (connection retry, IP-keyed occupancy, per-file SFTP isolation, error classification, rollback-on-spawn-failure, non-idempotent ops not retried) are explicitly preserved per Non-Goals or unchanged in the split. ✅

### Consistency with Frozen Proposal

- Same split: `MachineRepository` + `SSHMachineOperations` + 3 collaborators ✅
- Same helpers dissolution destinations ✅
- Same Protocol split (two replace one) ✅
- Same call-site categories ✅
- Same test impact patterns ✅
- No contradictions found. ✅

### 🔴 Outstanding

None. All baseline commitments met; all factual claims verified; all decisions complete; no behavior contracts weakened.

### Batch Verdict: **PASS** — design.md is accurate, complete, and consistent. Ready to freeze.

## specs Round 1 — 2026-06-27T17:30:00Z

### 🔴 Fixed
None — no blocking issues found in this round.

### 🟡 Addressed

1. **`_get_machine_state`, `register_machine`, `keys()`, `items()` listed in MachineRepository port requirement but not in design D8 Protocol**
   **Location:** `specs/ssh-machine-repository/spec.md` lines 23, 16, 26-27
   **Design cross-ref:** design.md D8 (lines 283-324)
   **Problem:** The `MachineRepository port` requirement lists `_get_machine_state(ip) -> _MachineState`, `register_machine(ip, _MachineState)`, `keys() -> KeysView[str, _MachineState]`, and `items() -> ItemsView[str, _MachineState]` as if part of the Protocol. The design D8 MachineRepository Protocol includes only `get_machine_state` (returns `ConnectedMachine | None`), `__len__`, and `__contains__`. These four additional methods reference `_MachineState` (an infra-internal type in `repository.py`), which is architecturally inappropriate for a domain Protocol in `domain/ports.py`. They belong as SSHMachineRepository implementation methods (specified in the "SSHMachineRepository implements MachineRepository" requirement), not in the Protocol.
   **Fix:** Move `_get_machine_state`, `register_machine`, `keys()`, and `items()` from the "MachineRepository port" Protocol requirement to the "SSHMachineRepository implements MachineRepository" implementation requirement, or clarify they are implementation-only methods (like the design does).

2. **`MachineOperations` Protocol deployment method name differs from design D8**
   **Location:** `specs/ssh-machine-repository/spec.md` line 184 vs design.md D8 line 340
   **Design cross-ref:** design.md D8 line 340 (`deploy_task`), Q3 (lines 504-525)
   **Problem:** Design D8's `MachineOperations` Protocol lists `deploy_task(...)` as the Protocol method (flattened namespace, per Q3 option a). The spec lists `start_task_on_machine(...)` (the implementation's internal name, per Q3 option b). Since Q3 is deferred to implementation, either is valid, but the spec should note the divergence from the design's explicit Protocol listing, or align with the design.
   **Fix:** Either rename to `deploy_task` to match D8, or add a note that `start_task_on_machine` is chosen as the Protocol method name (deviation from D8's `deploy_task`).

3. **`make_run_fn` naming differs from design's `_make_run_fn`**
   **Location:** `specs/platform-adapters/spec.md` line 57 vs design.md D6 line 234
   **Design cross-ref:** design.md D6 line 234 (`_make_run_fn`)
   **Problem:** Design D6 uses `_make_run_fn` (private, with underscore, matching current gateway.py line 1001). The spec uses `make_run_fn` (without underscore). This is a reasonable rename since the function becomes public when extracted to `platform/run_fn.py`, but it deviates from the frozen design without noting the change.
   **Fix:** Add a brief note that the function is renamed to `make_run_fn` (public) when extracted, or align with the design.

4. **No explicit "constructs exactly one SSHMachineOperations" scenario in dependency-injection delta**
   **Location:** `specs/dependency-injection/spec.md` lines 122-161
   **Design cross-ref:** design.md D7, proposal.md lines 103-106
   **Problem:** The original requirement had a scenario "clouds is None constructs exactly one SSHMachineGateway" ensuring single construction. The delta preserves this for `SSHMachineRepository` (scenario line 134) but does not add an equivalent "constructs exactly one `SSHMachineOperations`" scenario. The "shares one operations instance" scenario (line 129) covers identity via `is` check, which implicitly constrains to one construction, but lacks the explicit single-construction invariant the original had.
   **Fix:** Add a "constructs exactly one SSHMachineOperations" scenario parallel to the "constructs exactly one SSHMachineRepository" scenario.

### 🔴 Outstanding
None. All items above are non-blocking refinements.

### Batch Verdict: **PASS** — no blocking issues found. 4 non-blocking items flagged for cleanup.

## tasks Round 1 — 2026-06-27T14:10:55Z

### 🔴 Fixed

1. **Wrong line number for `check_gw` in task 14.10**
   **Location:** `openspec/changes/decompose-ssh-gateway/tasks.md` line 122
   **Problem:** Tasks 14.10 says "The `check_gw = SSHMachineGateway(log=log)` line at 282 → `SSHMachineRepository(log=log)`". The actual line in `tests/e2e/test_consume_retry.py` is 293, not 282. Line 282 is `assert task is not None`. An implementer following the exact line number would look at the wrong code.
   **Fix:** Change `line at 282` to `line at 293`.

### 🟡 Addressed

No non-blocking refinements this round.

### 🔴 Outstanding

None. The single line-number error is concrete and easy to fix. No other issues found across format, granularity, dependency ordering, spec coverage, design-decision reflection, or factual accuracy.

### Summary

- 7 unit test files, 1 integration, 1 e2e — all present and accounted for with corresponding migration tasks (14.1–14.10). ✅
- All 5 delta specs requirements mapped to at least one implementing task. ✅
- All 9 design decisions D1–D9 reflected in the task structure. ✅
- All 5 Open Questions (Q1–Q5) resolved or covered by implementing tasks. ✅
- Q3 resolution (`start_task_on_machine` name) explicitly noted in task 7.1. ✅
- D6 (`make_run_fn` in `platform/run_fn.py`) reflected in task 1.4. ✅
- D7 (public re-exports) reflected in task 8.1. ✅
- Q1 (atomic removal) reflected in tasks 7.1 + 13. ✅
- Dependency ordering correct: platform → repository → operations → ports split → call-sites → deletion → tests → knowledge graph → final checks. ✅
- All gateway.py and helpers.py line-number references verified against actual code — all correct. ✅
- `abandon_node.py` gateway parameter is indeed unused (confirmed via codebase read). ✅
- Three bg-task regression suites exist and are correctly referenced in task 14.1. ✅
- Static checks (group 16) cover ruff check, ruff format, lint-imports, zuban check, pytest (unit/integration/e2e), openspec validate, and no-remaining-reference scan. `grace_check.py` covered in tasks 1.5 and 15.3. ✅
- No scope creep: every task falls within the proposal's declared scope. ✅

### Batch Verdict: **PASS** — 1 non-blocking factual error found and easily fixable. Tasks are accurate, complete, and ready to apply after correcting the line number.
