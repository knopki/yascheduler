# Review Log: fix-download-rmtree-data-loss

## proposal Round 1 — 2026-06-26

### 🔴 Fixed
- N/A — first round, no prior fixes to verify.

### 🟡 Addressed

1. **Missing `orchestrator` in Modified Capabilities**
   - Location: proposal.md:21-23
   - Issue: The "Modified Capabilities" list covers `ssh-gateway`, `use-cases`, and `domain-ports` but omits `orchestrator`. The proposal modifies orchestrator behavior (conditional `_occupancy_started` discard, in-flight consume guard). The corresponding spec exists at `openspec/specs/orchestrator/spec.md` and will need updating.
   - Fix: Add `orchestrator` to the Modified Capabilities list describing the conditional occupancy-discard and consume guard changes.

2. **`download_outputs` return change not marked BREAKING**
   - Location: proposal.md:8
   - Issue: The `consume_task -> bool` change is correctly marked **BREAKING** (line 10), but `download_outputs` return shape change from 2-tuple `(meta_add, sftp_errors)` to 3-tuple `(meta_add, transient_errors, permanent_errors)` is also a BREAKING change to `MachineGateway` Protocol implementers. The Impact section (line 30) notes the effect but the What Changes section lacks the **BREAKING** marker.
   - Fix: Add **BREAKING** marker to the `download_outputs` bullet in the "What Changes" section.

3. **Modified Capabilities `ssh-gateway` description drops `meta_add`**
   - Location: proposal.md:21
   - Issue: Description says "from flat `sftp_errors` to structured `(transient_errors, permanent_errors)" but the actual return type is `(meta_add, transient_errors, permanent_errors)` (3-element tuple per explore-brief line 63 and proposal.md line 8). The `meta_add` component is silently dropped from the capability description.
   - Fix: Write "to structured `(meta_add, transient_errors, permanent_errors)`" instead.

4. **Accepted consequences not mentioned in Impact**
   - Location: proposal.md:25-31
   - Issue: The explore-brief explicitly records that cloud-dealloc-not-blocked (brief line 67) and node-stays-occupied (brief line 68) are acceptable consequences of the approach. The proposal's "Impact" section doesn't mention these, so a reviewer must infer them. Brief's recorded decisions serve as documentation of conscious trade-offs.
   - Fix: Add bullets to the "Impact" section stating that (a) cloud nodes may be deallocated while a task remains in retry (RUNNING), and (b) the node stays occupied until retry completes — both accepted trade-offs.

5. **Deferred design items not carried forward**
   - Location: proposal.md:5-13
   - Issue: The explore-brief records three open questions for design (brief lines 73-76): (1) in-flight consume guard mechanism, (2) OSError local-vs-remote disambiguation, (3) optional in-memory retry cap. The proposal mentions the in-flight consume guard (line 13) but doesn't carry forward the OSError disambiguation nuance or the retry cap as design TBDs.
   - Fix: Either (a) add a note under "What Changes" listing the open questions deferred to design.md, or (b) add a separate "Design TBD" subsection. The goal is traceability so design.md doesn't lose these items.

### 🔴 Outstanding
*(section absent — no blocking issues found)*

## design+specs Round 2 — 2026-06-26

### 🔴 Fixed
- N/A — no prior issues to verify carry-over into batch 2.

### 🟡 Addressed

1. **Mixed error state not covered in use-cases spec**
   - Location: `specs/use-cases/spec.md:24-34`
   - Problem: The ConsumeTask requirement defines behavior for `transient_errors empty → finalise` and `transient_errors non-empty AND permanent_errors empty → defer`, but does not define what happens when **both** `transient_errors` and `permanent_errors` are non-empty (possible when permanent per-file errors occur and then a session-level failure ends the loop before completion).
   - design.md Decision 4 prescribes "permanent_errors non-empty → finalise" (permanent takes priority), but the spec lacks this third branch. Without it, the condition falls through implicitly; an implementer must look to design.md for the rule.
   - Fix: Add an explicit third clause: "When `permanent_errors` is non-empty (regardless of `transient_errors`), the function SHALL finalise: apply `task.fail(error_details)`, save, commit, record `TaskFailed`, call `tracker.discard(task_id)`, and return `True`." Alternatively, restructure as a single `if permanent_errors: finalise / elif transient_errors: defer / else: finalise (success)`.

### 🔴 Outstanding
*(section absent — no blocking issues found)*

## tasks Round 3 — 2026-06-26

### 🔴 Fixed
- N/A — no prior issues to verify carry-over into batch 3.

### 🟡 Addressed

1. **Task 2.2 missing START_CHANGE_SUMMARY for ports.py**
   - Location: `tasks.md:12`
   - Issue: `ports.py` changes its public Protocol signature (`download_outputs` return type), which per AGENTS.md rule 2 warrants a `START_CHANGE_SUMMARY` entry. Task 2.2 only mentions `MODULE_MAP` and `START_CONTRACT` but omits `START_CHANGE_SUMMARY`.
   - Fix: Add "and add a `START_CHANGE_SUMMARY` entry" to task 2.2.

2. **Task 3.5 naming ambiguity with 3.3**
   - Location: `tasks.md:20`
   - Issue: Task 3.3 references renaming `_record_finalization_event` (or renaming to `_decide_finalisation`), but task 3.5 references `_finalize_task` — an inconsistent name not used in 3.3. Could confuse an implementer about which function to modify.
   - Fix: Use the same function name across 3.3 and 3.5 (either `_record_finalization_event`, `_decide_finalisation`, or `_finalize_task`).

### 🔴 Outstanding

1. **Existing tests not updated for new return shape and signature — test suite WILL break**
   - Location: `tasks.md:35-42` (tasks 6.1-6.6 add NEW tests only; no task updates existing tests)
   - Problem: Tasks 6.1-6.6 add new unit tests but do NOT update the several existing tests that WILL break because of the 2-tuple → 3-tuple return shape and `-> None` → `-> bool` signature change. Without update tasks, the first `uv run pytest -m unit` will fail. At minimum ~9 test locations across 4 files must be updated:
     - `tests/unit/test_ssh_gateway_download_outputs.py` (4 tests, lines 55, 80, 112, 139, 150): all destructure `meta_add, sftp_errors` from a 2-tuple return → will get `ValueError: not enough values to unpack` on the new 3-tuple. Assertions on `sftp_errors` must be split to check `transient_errors` vs `permanent_errors` according to new classification (per-file OSError → permanent, session OSError → transient).
     - `tests/unit/test_application_events.py` (2 tests, lines 213, 281-282): `download_outputs` mock returns 2-tuple `([], [])` and `([], [("/remote/file", OSError(...))])` → must return 3-tuple `([], [], [])` and `([], [], [("/remote/file", OSError(...))])` respectively.
     - `tests/unit/test_application_use_cases.py` (2 tests, lines 545, 625-627): same mock return shape issue as events tests.
     - `tests/unit/test_domain_ports.py` (line 178): `download_outputs` return type annotation and return value are 2-tuple `tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]` → must be 3-tuple.
   - Fix: Add a task (e.g., 6.0 or 6.7) "Update existing unit tests in `test_ssh_gateway_download_outputs.py`, `test_application_use_cases.py`, `test_application_events.py`, and `test_domain_ports.py` to match the new 3-tuple return shape and `-> bool` signature" — or better, integrate the updates into the existing test tasks by expanding them to cover both update and new test work.

## tasks Round 3 (re-review after fixes) — 2026-06-26

### 🔴 Fixed
1. **Missing existing-test-update tasks** — The 🔴 blocking issue from round 3 is resolved. New group 7 (lines 44–50) adds 5 tasks (7.1–7.5) covering all 4 affected file categories documented in the original finding:
   - 7.1 — search-based discovery (covers all callers and mockers)
   - 7.2 — 2-tuple → 3-tuple unpack update + assertion split (covers `test_ssh_gateway_download_outputs.py` 4 tests)
   - 7.3 — `-> None` → `-> bool` return assertions (covers `test_application_use_cases.py` and `test_application_events.py`)
   - 7.4 — mock/fake `MachineGateway` implementations + `_record_finalization_event`/`_finalize_task` test updates (covers `test_domain_ports.py`, `test_application_use_cases.py`, `test_application_events.py`)
   - 7.5 — `pytest -m unit` run gate before e2e

### 🟡 Addressed
1. **Task 2.2 missing START_CHANGE_SUMMARY** — Resolved. Task 2.2 now lists `START_CHANGE_SUMMARY` alongside `START_CONTRACT`/`MODULE_MAP`, labels the change as "public Protocol signature change", and includes "add a `START_CHANGE_SUMMARY` entry" in the instruction.
2. **Task 3.5 naming ambiguity with 3.3** — Resolved. Task 3.5 now explicitly references the 3.3 rename (`_decide_finalisation`) and says "keep the wrapper structure consistent with the renamed function", reconciling the inconsistency.

### 🔴 Outstanding
*(section absent — no blocking issues found)*
