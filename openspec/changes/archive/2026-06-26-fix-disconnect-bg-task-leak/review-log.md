## proposal+design+specs+tasks Round 1 — 2026-06-26

### 🔴 Fixed
 - _(none — no must-fix blocking issues)_

### 🟡 Addressed
 - **Recovery vs. prevention (design.md Migration Plan)**: the fix prevents
   NEW cross-cancellations but does NOT self-heal machines whose monitors
   were already killed before the deploy. Orchestrator logic: once
   `ip ∈ _occupancy_started` with a dead monitor, neither restart nor
   consume fires. Operators must restart the daemon (or otherwise re-trigger
   the task) to recover in-flight victims. Migration Plan mentions "daemon
   restart" for deploy but should explicitly state the fix is preventive,
   not curative, for already-affected tasks. Soft suggestion only — does
   not block freeze.
 - **Conditional conn close in spec scenario**: `disconnect single machine`
   scenario asserts "the SSH connection for 10.0.0.1 is closed", but the
   actual code closes conditionally on `state.conn._transport` being truthy
   (`gateway.py:337`). The existing main spec already glosses this; the
   delta preserves the same wording. Acceptable — pinning existing behavior.
 - **Decision 2 (identity-checked done-callback) necessity**: confirmed
   necessary given Decision 1's "replace prior monitor" semantics. Without
   the identity check, when `start_occupancy_check(A)` re-fires for an
   already-monitored IP, the cancelled prior task's done-callback would
   evict the freshly-installed replacement. Decisions 1 and 2 are
   internally coherent.

### 🔴 Outstanding
 - _(empty — ready to freeze)_

### Verification performed
- Bug accuracy: confirmed `gateway.py:173` `set[asyncio.Task]`, `gateway.py:331`
  `for task in list(self._bg_tasks)` cancels all, `gateway.py:810-811`
  add/discard idiom. Bug description in proposal/design is accurate.
- Orchestrator flow: confirmed `_occupancy_started` set at `orchestrator.py:131`,
  gating at `:344` (`if ip not in self._occupancy_started`), discard at `:369`.
  Reasoning holds — once collateral-cancelled, no restart path.
- Spec delta header: existing `openspec/specs/ssh-gateway/spec.md:120`
  uses `### Requirement: Disconnect and cleanup` — delta matches word-for-word.
- Scenario hashtag count in delta: all use exactly `####`. ✓
- MODIFIED block completeness: original scenarios "Disconnect single machine"
  and "Disconnect all" preserved (expanded for single); new scenarios added
  for the cross-machine invariant, unknown IP, and re-registration semantics.
- Test site claims (`tests/integration/test_ssh_gateway.py:516,628,662` and
  `tests/unit/test_ssh_gateway.py:856`): all confirmed via grep. Test at
  `:887` correctly noted as not indexing `_bg_tasks` directly.
- Production code sites: 4 (`gateway.py:173, 331, 810, 811`) — all covered by
  tasks 1.1–1.3.
- Scope discipline: no port contract / AiiDA / DB / config impact. ✓
- `openspec validate fix-disconnect-bg-task-leak --json` → `valid: true`. ✓

### Pass/Fail
**PASS — ready to freeze.** All four artifacts are internally consistent,
factually accurate against the codebase, and cover every commitment in
`explore-brief.md`. The two 🟡 items are soft suggestions the implementer
may absorb during apply (one-line addition to design.md Migration Plan
noting preventive-only scope; spec wording unchanged).
