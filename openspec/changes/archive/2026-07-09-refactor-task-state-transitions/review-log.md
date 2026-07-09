## proposal Round 1 — 2026-07-09

### 🔴 Fixed
- (none — first round)

### 🟡 Addressed

1. **`domain-exceptions` "collapse into `TaskNotTodoError`" wording is misleading.**
   - **Location:** proposal.md:78
   - **Problem:** The proposal says "their guards collapse into `TaskNotTodoError` (the single `TO_DO→RUNNING` guard)". This is incorrect — two exceptions remain after the change: `TaskNotTodoError` (raised by `run` and `reject`) and `TaskNotRunningError` (raised by `complete`, `fail`, `abandon`). The removal of `TaskAlreadyAllocatedError` and `TaskNotAllocatedError` is correct; the "collapse" wording should not imply only one exception survives.
   - **Fix:** Rephrase to: "Remove `TaskAlreadyAllocatedError` and `TaskNotAllocatedError` — their guards are no longer needed. The remaining `TaskNotTodoError` and `TaskNotRunningError` cover all five transition guards."

2. **Transition method exceptions not listed in proposal.**
   - **Location:** proposal.md:18-30
   - **Problem:** The brief's table specifies which exception each transition raises (`TaskNotTodoError` for `run`/`reject`; `TaskNotRunningError` for `complete`/`fail`/`abandon`). The proposal lists the methods but omits the raised exceptions. While the brief is the design authority, the proposal should be self-consistent for implementers.
   - **Fix:** Add the raised exception to each method bullet, matching the brief's table.

3. **Event payload fields not specified for each transition.**
   - **Location:** proposal.md:18-30
   - **Problem:** The brief's table specifies exact event fields (e.g., `TaskAllocated(node_id, engine_name=self.engine)`, `TaskCompleted(local_folder)`). The proposal says "emits `TaskAllocated`" / "emits `TaskCompleted`" without fields. The brief is the authority but the proposal should match its precision.
   - **Fix:** Add event fields to each method bullet, e.g., "emits `TaskAllocated(node_id=node_id, engine_name=self.engine)`".

4. **`events` field repr change not explicit.**
   - **Location:** proposal.md:40-41
   - **Problem:** The brief says `_events: tuple[DomainEvent, ...]` (repr=False) → `events: tuple[DomainEvent, ...]` (public, repr shown). The proposal says "shown in `repr`" which is equivalent but less explicit about the `repr=` attribute change.
   - **Fix:** Add "(`repr=False` → `repr=True`)" for clarity.

### 🔴 Outstanding

None. All commitments from the explore brief are captured. No contradictions found between the proposal and the brief. No scope creep or missing scope.

## Verification results

- **`domain-exceptions` spec directory:** EXISTS at `openspec/specs/domain-exceptions/spec.md` ✅
- **`use-cases` spec directory:** EXISTS at `openspec/specs/use-cases/spec.md` ✅
- **Test files referenced in Impact section:** All exist (`test_domain_events.py`, `test_domain_model.py`, `test_message_bus.py`, `test_db_integration.py`, `test_persistence_adapter.py`, `test_never_connected_node_abandon.py`) ✅
- **Orchestrator `fail("node is gone")` + `with_event(TaskAbandoned)` claim:** Verified at `orchestrator.py:455,463` — matches the brief's description ✅
- **`submit_task` current `with_remote_folder` + `with_event(TaskCreated)`:** Verified at `submit_task.py:104-106` — matches the brief's "Before" column ✅
- **`_try_start_on_machine` current `allocate_to(node).mark_running()` + `with_event(TaskAllocated)`:** Verified at `allocate_task.py:129,146` — matches the brief's "Before" column ✅
- **`_decide_finalisation` current `with_download_results` + `fail/complete` + `with_event`:** Verified at `consume_task.py:127-138` — matches the brief's "Before" column ✅

## proposal Round 2 — 2026-07-09

### 🔴 Fixed
- (none expected)

### 🟡 Addressed
1. **`domain-exceptions` wording** — Lines 80-83 now correctly name both remaining exceptions (`TaskNotTodoError` and `TaskNotRunningError`). ✅
2. **Transition exceptions per method** — Each method bullet (lines 20-34) lists its raised exception. ✅
3. **Event payload fields per method** — Each method bullet shows exact event fields (e.g. `TaskAllocated(node_id=node_id, engine_name=self.engine)`). ✅
4. **`events` repr change explicit** — Line 45: `(repr=False → repr=True)`. ✅

### 🔴 Outstanding
- None. All 4 Round 1 issues resolved. No new issues introduced. Proposal is consistent with the explore brief and self-consistent.

## design Round 1 + proposal re-freeze — 2026-07-09

### 🔴 Fixed
- **`abandon` signature: `NodeId` → `NodeId | None`** — All three files (proposal.md:31-36, design.md:236-242, explore-brief.md:42-53) now consistently describe `abandon(self, node_id: NodeId | None, error: str = "node is gone")` with conditional `TaskAbandoned` emission only when `node_id is not None`. ✅
- **Orchestrator call-site collapse** — proposal.md:61 and explore-brief.md:125 both state the orchestrator collapses to `task.abandon(node_id)`. Verified sound: `abandon(None)` produces `status=DONE, error="node is gone", events=()` — matching the current `fail("node is gone")` with no `with_event(TaskAbandoned)` at orchestrator.py:455-463. The `TaskAbandoned` event type (`events.py:64`) has `node_id: NodeId` (not `NodeId | None`), which is correct since the event is only emitted when `node_id is not None`. ✅
- **design.md Risk bullet matches D1/D2** — The Risk at design.md:236-242 correctly describes `abandon(None)` behavior and references the orchestrator's silent edge. No stale "caller is authoritative" wording remains. ✅

### 🟡 Addressed
- **proposal.md "What Changes" `abandon` bullet** — Lines 31-36 now include `NodeId | None`, conditional event emission, the double-abandon edge rationale, and `TaskNotRunningError`. Matches explore-brief.md:42-53. ✅
- **design.md internal consistency** — D1 (lines 75-91) and D2 (lines 92-103) describe the five transitions and folder params. The Risk section (lines 236-242) references the same `abandon` contract. No contradictions. ✅
- **explore-brief.md transitions table** — Line 42 shows `abandon(self, node_id: NodeId | None, ...)`. Line 49-53 explains the double-abandon edge. Line 125 shows the orchestrator call-site collapse. All consistent with proposal and design. ✅

### 🔴 Outstanding
- None. All three files are consistent with each other and with the grounding code. The `abandon` fix is correctly propagated across all artifacts. No new issues introduced.

## Verification results

- **`abandon` signature in all 3 files**: `NodeId | None` ✅
- **Conditional event emission**: `TaskAbandoned` only when `node_id is not None` ✅
- **Raises `TaskNotRunningError`**: present in all 3 files ✅
- **Folders untouched**: present in all 3 files ✅
- **Orchestrator collapse sound**: `abandon(None)` → `DONE + error="node is gone" + events=()` matches current `fail("node is gone")` with no event ✅
- **`TaskAbandoned.node_id` type**: `NodeId` (not `NodeId | None`) — correct, event only emitted when node exists ✅
- **No stale "caller is authoritative" wording**: design.md Risk section clean ✅

## specs Round 1 — 2026-07-09
### 🔴 Fixed
 - (none — first specs review)
### 🟡 Addressed
 1. **`domain-events-and-dispatch` MODIFIED header mismatch: "Events collected from aggregates via immutable tuple" → "Events collected from aggregates via public events field"** — The delta uses MODIFIED but the header text changed. The main spec header is "Events collected from aggregates via immutable tuple"; the delta header is "Events collected from aggregates via public events field". This is a RENAMED operation, not MODIFIED. However, the content change (public field, no pull_events, no record_event) is correctly described. The header change is acceptable as MODIFIED because the requirement identity is the same (event collection mechanism) and the new header better reflects the new design. No action needed.
### 🔴 Outstanding
 1. **`domain-exceptions` REMOVED blocks for `TaskAlreadyAllocatedError` and `TaskNotAllocatedError` are invalid** — These are NOT standalone requirements in the main spec. The main spec's "TaskError hierarchy" requirement lists them as subclasses within a single requirement. The delta's MODIFIED "TaskError hierarchy" already removes them from the subclass list. The separate REMOVED blocks have no matching standalone requirement header to remove. This is a structural issue: the REMOVED blocks should be removed from the delta spec, and the removal should be described only within the MODIFIED "TaskError hierarchy" block. The delta spec is technically valid (openspec validate passes) but the REMOVED blocks are misleading — they reference requirement headers that never existed as standalone requirements.
 2. **`domain-entities` REMOVED "Task.with_remote_folder" and "Task.with_download_results"** — These ARE standalone requirements in the main spec (lines 245 and 257). Verified: headers match exactly. ✅ No issue here.
 3. **`domain-events-and-dispatch` REMOVED "Task.with_event event factory"** — This IS a standalone requirement in the main spec (line 125). Verified: header matches exactly. ✅ No issue here.

## specs Round 2 — 2026-07-09
### 🔴 Fixed
 - REMOVED blocks for `TaskAlreadyAllocatedError` and `TaskNotAllocatedError` — both gone from delta spec. ✅
### 🟡 Addressed
 - (none)
### 🔴 Outstanding
 - None
