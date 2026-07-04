# Review Log — ssh-rekey-node-id

## proposal Round 1 — 2026-07-03

### 🔴 Serious issues
None — proposal faithfully captures the brief; no contradictions with rejected alternatives.

### 🟡 Addressed (fixed this round)
- `ConnectedMachine.node_id` addition not marked BREAKING → marked BREAKING with internal-only note
- "Code (10 files)" undercount → corrected to "(13 files)"
- `manage_node` add-path flow omitted final `disconnect()` → added `disconnect(node_id)` to the flow
- Prerequisite `task-allocated-node-id` commit-first not restated → added explicit Prerequisite block under DB schema
- `get_by_id(node_id)` survival not explicitly confirmed → added "unchanged" parenthetical to the NodeRepository bullet

### 🔴 Outstanding
None.

### ✅ Confirmed good
- Rejected alternatives A–D not contradicted
- Identity model (ConnectedMachine.node_id, MachineSession clean, _sessions keyed by NodeId)
- MachineRepository / CloudProvisioner / NodeRepository port contracts match brief
- Domain events (TaskAllocated/TaskAbandoned node_ip → node_id)
- 9 read-site flips all covered
- V1 cloud lifecycle (single row, UPDATE, tmp_node_id reused)
- All 8 open questions resolved
- Capability mapping — all 9 specs exist under openspec/specs/
- Why section ties to prior migration arc; scope right-sized

## design Round 1 — 2026-07-03

### 🔴 Serious issues
None — design is correct and complete.

### 🟡 Addressed (fixed this round)
- D1 overstates "All MachineRepository methods" → rephrased to specify identity-taking methods only; non-identity methods (disconnect_all/list_free/list_connected/__len__) noted as unchanged
- R6 framed dup-IP resolution as a risk → rephrased as intentional acknowledgement (not a hazard); the change is the goal, verified by e2e test
- Cross-module data flows not consolidated → added a "Data flows" subsection under Migration Plan referencing the 4 flows and their decision sections

### 🔴 Outstanding
None.

### ✅ Confirmed good
- All 9 decisions (D1-D9) — rationale clear, rejected alternatives sound, matches brief
- All 8 open questions resolved (OQ1→D5, OQ2→D8, OQ3→D7, OQ4→D7, OQ5→Non-Goals, OQ6→D9, OQ7→Migration Plan, OQ8→D6)
- No contradictions with frozen proposal.md
- Migration plan correct — no DB migration, rollback by revert, verification gates complete
- Goals/Non-Goals aligned with proposal scope
- Risks R1-R7 real with adequate mitigations
## specs Round 1 — 2026-07-03

### 🔴 Serious issues
1. cli delta: 3 MODIFIED requirement names didn't match main spec
   (`yastatus queries tasks via CLIDeps` → `yastatus queries task status`;
   `yasetnode opens a validation UoW then dispatches via per-helper UoW`
   → `yasetnode dispatches add and remove paths`;
   `yasetnode add-path uses V1-pattern (...)`
   → `yasetnode gateway lifecycle and resource safety`)
2. `openspec validate` ERROR: `yastatus` body first line lacked SHALL

### 🟡 Addressed
3. orchestrator delta did not modify "Orchestrator manages producer-consumer loops" — stale `get_session(ip)` scenario + flip #3 (ncpus `get_by_id(allocated_node_id)`) uncaptured → added MODIFIED requirement covering both

### 🔴 Outstanding
None — fixed all three; validation passes (valid: true).

### ✅ Confirmed good
- All 9 spec files present; 24/27 names matched (after fix: all map)
- All scenarios use `####`; every requirement ≥1 scenario
- `_sessions: dict[NodeId, SSHMachineSession]`, ConnectedMachine.node_id first field
- CloudProvisioner.allocate(provider, tmp_node_id) -> Node consistent across 4 specs
- get/get_by_ips REMOVED; get_by_ids ADDED with ANY(:node_ids); SQL files removed
- TaskAllocated/TaskAbandoned flipped to node_id; mapping table updated
- Dup-IP disambiguation scenario in orchestrator + use-cases
- V1 single-row UPDATE everywhere consistent

## specs Round 2 — 2026-07-03

### 🔴 Serious issues
None.

### 🟡 Addressed
- Reflow artifact: 3 paragraphs duplicated verbatim in yastatus body → removed second copy.

### 🔴 Outstanding
None. Specs frozen. `openspec validate` → valid: true.

## tasks Round 1 — 2026-07-03

### 🔴 Serious issues
1. `get`/`get_by_ips` test migration gap — 10 call sites across `tests/integration/test_db_integration.py`, `tests/integration/test_never_connected_node_abandon.py`, `tests/e2e/test_consume_retry.py` had no tasks
2. Tasks 7.7 and 11.3 referenced phantom `deallocate_node.py` (it's a function inside `deallocate_nodes.py`)

### 🟡 Addressed
3. Task 7.5 stale (consume_task already takes session) → reworded to verification/no-op
4. Task 7.7 misleading "BEFORE the guard" → reworded to rekey-only (already before the guard)

### 🔴 Outstanding
None — fixes applied (10.1b, 10.1c, 10.5 extended, 7.5/7.7/11.3 reworded).
