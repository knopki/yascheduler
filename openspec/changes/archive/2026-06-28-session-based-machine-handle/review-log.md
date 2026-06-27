# Review Log — session-based-machine-handle

## proposal Round 1 — 2026-06-27

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` (frozen as review checklist)

### Verdict
PASS-WITH-FIXES

### 🔴 Fixed
- `infra/cloud/manager.py` was INCORRECTLY labelled UNCHANGED. The
  reviewer verified that `manager.py:324, 350, 357` call
  `machine_operations.{run, setup_node, get_cpu_cores}` (all signatures
  change to take `MachineSession`) and `manager.py:405` stores the
  return of `machine_repository.connect()`. The parenthetical
  "(the returned MachineSession is not stored)" was wrong twice.
  Fixed: moved `manager.py` from UNCHANGED to MODIFIED with accurate
  description; added detail on `entrypoints/cli/check_status.py`
  `_download_convergence_snippet` / `_display_remote_output` tuple-shape
  narrowing (related, since those helpers call `repository.get_path` /
  `operations.get_sftp` which the redesign removes).

### 🟡 Addressed
- The implicit 4-tuple shape change in `check_status.py`'s helpers
  flagged by the reviewer is now noted in the What Changes entry for
  that file, so the tasks.md author has a marker to enumerate.

### ✅ Confirmed (15 brief commitments captured cleanly)
1. Disease vs symptom framing (private `_get_machine_state` is disease).
2. Repository 7-method surface.
3. Session's three faces (domain/config/primitives/monitor).
4. RF1 session-owns-monitor + D2 reversal.
5. RF2 facade kept.
6. RF3 `MachineSession` Protocol in `domain/ports.py`.
7. Q-G1/Q-G2/Q-G3 decisions reflected.
8. Predecessor ordering explicit (`cleanup-unused-repository-symbols` MUST land first).
9. AiiDA plugin unaffected.
10. Internal-only BREAKING.
11. Collaborators become stateless.
12. Disconnect ordering invariant referenced.
13. Rollback path uses `session.is_closed`.
14. Capabilities naming (`ssh-machine-session` new kebab-case).
15. Capabilities modified (`ssh-machine-repository`, `domain-ports`).

### 🔴 Outstanding
(none — single-round pass per OpenSpec review-flow rule 4a)

---

## design Round 1 — 2026-06-27

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + `proposal.md` (both frozen)

### Verdict
PASS-WITH-FIXES

### 🔴 Fixed
- **`_close()` Protocol access contradiction (design.md D1/D3).** D1
  typed `_sessions: dict[str, MachineSession]` (Protocol) but D3 called
  `await session._close()` (private). Calling a private method on a
  Protocol-typed reference would not type-check unless `_close` is in
  the Protocol, which violates Python convention. Fixed by adding a
  "Type discipline" paragraph to D1: the repository holds concrete
  `SSHMachineSession` internally (`_sessions: dict[str,
  SSHMachineSession]`), so `_close()` stays private; public-facing
  methods return the Protocol type, consumers never see `_close`.
- **D9 (`make_run_fn` placement) had no alternative considered.** Added
  the rejected alternative (move to `session.py` or `repository.py`)
  with rationale (creates a dependency edge the other must cross;
  `platform/run_fn.py` is the correct DAG root).

### 🟡 Addressed
- **Idempotency guard on `_close()`** — added: if already `_closed`,
  return immediately (protects against double-call from a buggy
  disconnect path).
- **`install_monitor` on closed session** — added: idempotent return if
  `_closed`, so a closing session does not start a doomed monitor.
- **D2 reversal framing** — expanded D3 to acknowledge both prongs of
  the original D2 rationale (a: dict parity, b: Engine-agnostic
  mechanism) and explain why each collapses under the session design.

### ✅ Confirmed (decisions + risks verified)
- D1 (three faces on one object) — sound, alternative correctly rejected
- D2 (Protocol in `domain/ports.py`) — correct
- D3 (monitor on session, D2 reversal) — sound
- D4 (keep Operations facade) — pragmatic
- D5 (stateless collaborators) — verified `OccupancyChecker`'s last
  repository need was `install_monitor` (`occupancy.py:194`), now on
  session
- D6 (per-tick resolution) — correct
- D7 (`list_*` returns `list[MachineSession]`) — verified call sites
- D8 (connection bits stay) — correct
- D10 (re-exports) — correct
- R1/R2/R3/R4/R5 mitigations — all verified against actual code

### 🔴 Outstanding
(none — single-round pass per OpenSpec review-flow rule 4a)

---

## specs Round 1 — 2026-06-27

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + `proposal.md` + `design.md` (all frozen)

### Verdict
PASS-WITH-FIXES

### 🔴 Fixed
- **`MachineRepository` Protocol dropped `contains(ip)` without
  migration plan.** The frozen explore-brief listed `contains`/
  `__contains__` as "same (unchanged surface)", but the delta spec
  kept only `__contains__`. Three production callers
  (`deallocate_nodes.py:56`, `orchestrator.py:264`, `orchestrator.py:550`)
  use `repository.contains(ip)`. Restored `contains(ip: str) -> bool`
  to the Protocol with a note about its preserved use.
- **`domain-ports` requirement title omitted `MachineSession`.** The
  requirement heading said "MachineRepository and MachineOperations
  ports replace MachineGateway" but the content described three
  Protocols. Renamed to "MachineRepository, MachineSession, and
  MachineOperations ports replace MachineGateway".

### 🟡 Addressed
- Added `download_outputs` and `start_occupancy_check` forwarding
  scenarios to `SSHMachineOperations composition` (preserves
  archive-time scenario coverage that the prior main spec had).
- Added `Repository supports contains` and `Repository supports len`
  scenarios (basic coverage for the `__contains__` / `__len__` parts
  of the 7-method surface).

### ✅ Confirmed (15 spec commitments clean)
1. `MachineSession` Protocol matches design.md D1 three faces.
2. `SSHMachineSession` matches design.md (constructed by repo.connect, owns teardown, no IP-keyed lookups).
3. `MachineRepository` 8-method surface (7 + restored `contains`).
4. `_sessions: dict[str, SSHMachineSession]` concrete type per D1 type discipline.
5. `MachineOperations` Protocol takes `MachineSession` (RF2).
6. Collaborators stateless (RF2/D5); narrow Protocols removed.
7. `domain-ports` has all three Protocols.
8. No spec leakage from cleanup (correctly attributes shared removals).
9. MODIFIED requirements carry full updated content.
10. Every requirement has ≥1 scenario.
11. All scenarios use `####`.
12. SHALL/SHALL NOT used normatively.
13. Inter-file consistency on `MachineSession` references.
14. REMOVED Requirements section correctly notes no top-level removals.
15. `_close()` access pattern matches D1 type discipline.

### 🔴 Outstanding
(none — single-round pass per OpenSpec review-flow rule 4a)

---

## tasks Round 1 — 2026-06-27

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + `proposal.md` + `design.md` + three spec files (all frozen)

### Verdict
PASS-WITH-FIXES

### 🔴 Fixed
- **Task 9.1 wrong dependency** — `M-SSH-SESSION <depends>` listed
  `M-SSH-OPERATIONS-BASE`, but `my_backoff_exc` is MOVED TO session.py
  (not imported from operations/base.py). Corrected to
  `M-PLATFORM, M-SSH-EXCEPTIONS, M-DOMAIN` with inline rationale.
- **Task 2.3 too large (>2h)** — split into 2.3 (constructor + domain
  face + properties + `my_backoff_exc`), 2.4 (base primitives), 2.5
  (monitor mechanism + `_close`), 2.6 (semantic markup), 2.7 (grace_check).
- **Section 3 too large (18 sub-tasks)** — reorganized into 3.1 (state
  shape + delete `_MachineState`/`_get_machine_state`), 3.2 (lifecycle),
  3.3 (queries), 3.4 (delete migrated wrappers), 3.5 (Protocol), 3.6
  (connection bits stay), 3.7 (MODULE_CONTRACT), 3.8 (smoke test).
- **Task 6.1 too large** — split into 6.1 (producer/stats/dealloc) and
  6.2 (consumer per-tick session resolution + `_start_task_on_machine`
  signature change). Subsequent task numbers shifted.
- **Rollback unexpected-state check not mentioned (task 5.2)** — added
  explicit note to preserve the `session.machine.state != BUSY` warning
  between `is_closed` guard and `session.update(...)`.
- **Task 6.3 (now 6.3) callback type change not explicit** — added
  explicit bullet that `start_task_on_machine` callback type changes
  from `Callable[[ConnectedMachine, Engine, Task], ...]` to
  `Callable[[MachineSession, Engine, Task], ...]` in `_try_start_on_machine`
  and `_allocate_free_machine` signatures, and the orchestrator's
  callback registration site is updated to pass session instead of
  machine.

### 🟡 Addressed
- Task 3.5 method count corrected from "8-method" to "9-method"
  (`connect`, `disconnect`, `disconnect_all`, `list_free`,
  `list_connected`, `get_session`, `contains`, `__contains__`, `__len__`).
- Task 10.8 grep list extended: added `get_machine_state`,
  `_MachineState` (in addition to `_get_machine_state`, `_machines[`,
  `_monitors[`, `register_machine`, `MachineGateway`); scope extended
  to `tests/` as well.
- Task 7.2 added `test_fresh_session_is_not_closed` (covers the
  `is_closed is False on a freshly connected session` spec scenario).
- Task 7.4 detailed the monitor identity check migration
  (`_monitors[ip] is task` → `session._monitor_task is task`).
- Task 6.10 (formerly 6.9) noted that DI construction signature is
  preserved; the implementation internally constructs stateless
  collaborators.

### ✅ Confirmed (task commitments sound)
- Predecessor check (task 1.1) with STOP instruction.
- Code line references all verified (orchestrator.py:470, deployment.py
  rollback structure, check_status.py:250-251/340, cloud/manager.py
  lines 324/350/357/405).
- R1 (rollback `is_closed`) — tasks 5.2 + 7.5 sentinel.
- R2 (test rewrite bulk) — task 7.4 enumerates four invariants with
  behavioral rename.
- R4 (disconnect ordering) — tasks 2.5 + 3.2 spell out `_closed=True`
  before first await.
- Knowledge graph section 9: new M-SSH-SESSION, shrunk M-SSH-REPOSITORY,
  shrunk M-SSH-OPERATIONS-BASE, 5 new CrossLinks.
- Static checks section 10 covers all project commands.
- Re-exports section 8 updates both package roots.
- Protocol layering matches design D2.
- Facade preserved (D4).
- Connection bits stay (D8).

### 🔴 Outstanding
(none — single-round pass per OpenSpec review-flow rule 4a)

---

## Final validation — 2026-06-27

- `openspec validate session-based-machine-handle --json` — passed (0 issues).
- `openspec validate --all --json` — passed (46/46 items valid).
- `python3 scripts/grace_check.py` — exit 0 (53 pre-existing warnings,
  0 errors; no new warnings introduced by this change's artifacts).

All four artifacts (proposal, design, specs, tasks) frozen after
single-round review each.

