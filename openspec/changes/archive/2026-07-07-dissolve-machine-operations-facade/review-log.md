## proposal Round 1 — 2026-07-07

Reviewer: orchestrator (inline; @k-reviewer-fast returned empty twice).

### 🔴 Fixed
- `tests/e2e/test_full_cycle.py` was listed in Impact but grep returned 0 matches for `SSHMachineOperations` in that file. Removed.

### 🟡 Addressed
- Test file count for `test_ssh_gateway*.py` corrected: 5 → 6.
- Added missing test files to Impact: `test_cli_check_status.py` (mocks ops for `yastatus`), `test_cloud_provisioner_impl.py` (mocks `machine_operations`), `test_cloud_alloc_session_lifecycle.py` (configurable SSHMachineOperations).

### ✓ Verified
- `run_full`/`run_bg`/`occupancy_check` have zero production callers.
- `cloud/` and `e2e-testing/` specs don't mention `MachineOperations` — Modified Capabilities list is exhaustive.
- All 5 facade pass-through call sites hold a `session` in hand (manager.py ×3, orchestrator.py ×1, manage_node.py ×1).
- `CloudProvisionerImpl` uses only session pass-throughs (`run`/`setup_node`/`get_cpu_cores`).
- `SSHMachineOperations` is a pure facade; `self._repo` is assigned but never read (grep `self\._repo` returned only the assignment line in `base.py:61`).

### 🔴 Outstanding
None.

---

## proposal Unfreeze — 2026-07-07 (during design round)

Design D2 settled on **three** collaborator params for `Orchestrator.__init__`
(`task_deployer`, `output_downloader`, `occupancy_checker`); proposal had said
**two** with `OutputDownloader` taken only by `consume_task`. The orchestrator
needs to hold `output_downloader` to thread it into `consume_task` from its
consumer loop, so it must be a constructor parameter. Decision-level change
to a frozen artifact — unfrozen proposal.md, applied the fix, re-froze.

---

## design Round 1 — 2026-07-07

Reviewer: orchestrator (inline; @k-reviewer-fast returned empty).

### 🔴 Fixed
- (See proposal Unfreeze entry above — design-proposal consistency.)

### 🟡 Addressed
- D6 specifies `__all__` contents for the operations package — borderline implementation detail. Kept as the package-facade contract surface (consistent with `package-facades` spec style).

### ✓ Verified
- D1–D8 each have rationale + alternatives; no decision is unjustified.
- Risks section identifies 4 concrete risks + 1 trade-off.
- D8 test-fake-surface table supports proposal's framing ("facade does nothing, removal shrinks surface").
- D5 signatures match the actual `allocate_task`/`consume_task` parameter lists (verified against `consume_task.py:228-236`, `allocate_task.py:119-128`).
- D3 CloudProvisionerImpl rewrite verified against `manager.py:369, 393, 400`.

### 🔴 Outstanding
None.

---

## specs Round 1 — 2026-07-07

Reviewer: orchestrator (inline; @k-reviewer-fast returned empty in earlier rounds).

### 🔴 Fixed
- `package-facades` delta had two mismatched requirement headers: `Layers (R3)` (actual: `Layer direction (R3)`) and `Domain layer facade` (actual: `Domain package facade contents`). OpenSpec matches MODIFIED requirements by header text — both corrected.

### ✓ Verified
- All 8 spec deltas present: `domain-ports`, `ssh-infrastructure`, `dependency-injection`, `orchestrator`, `use-cases`, `cli`, `package-facades`, `testing-unit`.
- Every MODIFIED/REMOVED requirement header matches the original verbatim (cross-checked against `openspec/specs/<cap>/spec.md` headers).
- `openspec validate dissolve-machine-operations-facade --json` passes (after header fix).
- `domain-ports` MODIFIED scenario asserts `MachineOperations` is absent.
- `ssh-infrastructure` REMOVED both facade requirements with Reason + Migration; MODIFIED 3 behavior requirements to reference `OutputDownloader`/`TaskDeployer`/`OccupancyChecker` directly.
- `dependency-injection` MODIFIED both make_daemon requirements; new scenario asserts `CloudProvisionerImpl` is constructed WITHOUT `machine_operations=`.
- `orchestrator` MODIFIED 3 requirements; new scenario asserts three collaborator kwargs (`task_deployer=`, `output_downloader=`, `occupancy_checker=`).
- `use-cases` MODIFIED 2 requirements with collaborator-typed params.
- `cli` MODIFIED 2 requirements; scenario asserts no `SSHMachineOperations` is constructed on the add path.
- `package-facades` MODIFIED 4 requirements; import scenarios reference the three collaborators; symbol count adjusted 9 → 11.
- `testing-unit` MODIFIED 1 requirement; `MachineOperations` removed from the Protocol list.

### 🔴 Outstanding
None.

---

## tasks Round 1 — 2026-07-07

Reviewer: orchestrator (inline).

### ✓ Verified
- 11 task groups, dependency-ordered (domain ports → facade deletion → package facade → Cloud → Orchestrator → use cases → DI → CLI → tests → knowledge graph → verification).
- Each task is scoped to ≤2 hours of work; test-update tasks are split per-file for parallelisability.
- `openspec validate --all --json` passes (19/19 items).
- `openspec status` reports 4/4 artifacts complete.
- All affected files from the proposal's Impact section appear as task targets:
  - Production: `domain/ports.py`, `infra/ssh/operations/base.py` (deleted), `infra/ssh/operations/__init__.py`, `infra/__init__.py`, `infra/cloud/manager.py`, `application/orchestrator.py`, `application/allocate_task.py`, `application/consume_task.py`, `entrypoints/di.py`, `entrypoints/cli/manage_node.py`.
  - Tests: all 9 listed test files have explicit task entries.
- Verification gates include all checks from `AGENTS.md` (`zuban`, `ruff`, `lint-imports`, `grace_check.py`, `openspec validate`, pytest markers).

### 🟡 Noted (not blocking)
- Tasks 9.6 (6 unit test files) and 9.7 (integration test with 40+ method signatures) are the largest mechanical items — could be parallelised across @k-implementer instances per-folder during apply. No spec change needed.

### 🔴 Outstanding
None.
