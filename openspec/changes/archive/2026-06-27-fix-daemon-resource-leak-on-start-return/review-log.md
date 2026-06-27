# Review Log — fix-daemon-resource-leak-on-start-return

## proposal Round 1 — 2026-06-27

### 🟡 Addressed
- Wording imprecision in `daemon-common` capability description: "add scenarios for `start()` returning normally and for `start()` raising" reframed to scenarios for `orch.start()` returning normally, raising, and signal-handler-then-finally-no-op (aligned wording with the owning module `run_daemon`).
- Impact section test-gap statement broadened from "`disconnect_all` has no covering tests" to "the entire `stop()` cleanup chain (`clouds.stop()`, `gateway.disconnect_all()`, `http_session.close()`) currently lacks test coverage" for completeness.

### 🔴 Outstanding
- (none)

**Result:** APPROVED, frozen. Single round — no 🔴 issues.

---

## design Round 1 — 2026-06-27

### 🔴 Fixed
- (none — no 🔴 issues found)

### 🟡 Addressed
- (none — design clean, all fidelity/decision/non-goal/risk checks passed)

### 🔴 Outstanding
- (none)

**Result:** APPROVED, frozen. Single round.

---

## specs Round 1 — 2026-06-27

### 🟡 Addressed
- `specs/daemon-common/spec.md`: requirement statement "invoked exactly once on every exit path" was ambiguous (on the signal path `orch.stop()` is called twice; only the cleanup body runs once). Reworded to "the cleanup body of `orch.stop()` executes exactly once on every exit path" with a clarifying clause that the function may be called more than once but only the first call runs the body.
- `specs/orchestrator/spec.md`: added a 9th scenario "interleaved stop() calls are serialized by the guard" as belt-and-suspenders coverage for the `_stopped` atomicity claim under real asyncio interleaving (second call arrives while first is mid-`await` inside the cleanup body).

### 🔴 Outstanding
- (none)

**Result:** APPROVED, frozen. Single round.

---

## tasks Round 1 — 2026-06-27

### 🟡 Addressed
- Stale line-number references in tasks 1.1–1.7: updated to current tip (sibling change `fix-orchestrator-producer-silent-death` has landed, shifting `stop()` from ~686 to lines 729-743). Now references "currently lines 729-743" etc. so the implementer lands at the correct location.
- Task 1.3 updated to note the `except Exception` now also covers worker tasks registered in `_bg_jobs` by the sibling change (composition confirmed live in code: `_create_producer_consumers` line 593 registers workers in `self._bg_jobs`).
- Task 1.7 contract update note similarly extended to mention worker-task tolerance.
- Task 2.1 block-marker placement fixed: the `START_BLOCK_START_ORCHESTRATOR` / `END_BLOCK_START_ORCHESTRATOR` pair around the bare `await orch.start()` would split a `try` body from its `finally` clause across marker boundaries. Renamed to `START_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP` / `END_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP` enclosing the entire `try/finally` construct so the semantic block matches the syntactic construct.

### 🔴 Outstanding
- (none)

**Result:** APPROVED. Single round — all 13 scenarios, D1-D4, GRACE-lite markup, static checks, scope discipline verified covered.

---

## Composition note (live verification)

During tasks review, verified against the current codebase tip that the sibling change `fix-orchestrator-producer-silent-death` has **already landed**:
- `_create_producer_consumers` (`orchestrator.py:568`) now registers workers in `self._bg_jobs` (line 593, `START_BLOCK_REGISTER_WORKERS`).
- Producer-error resilience (`try/except Exception` around `async for msg in producer():`, lines 599-612) is in place.
- `stop()` (lines 729-743) is UNCHANGED — confirms this change's scope (`stop()` hardening + `run_daemon` try/finally) is orthogonal and non-overlapping.
- `self._stopped` does NOT yet exist — confirms this change is not duplicating sibling work.

The two changes compose exactly as design D-risk #4 predicted: `stop()` now iterates a larger `_bg_jobs` set (coordinators + workers); the `except Exception` (D3) applies uniformly to both. No conflict, no duplication.