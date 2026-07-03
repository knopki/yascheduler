## proposal Round 1 — 2026-07-02

### 🟢 Approved (no outstanding issues)

Reviewer verified all brief commitments against current code/schema/SQL:
- round-trip waste (deallocate_nodes line 130 + orchestrator line 560) — confirmed
- dedup-key weakness (ip not UNIQUE post migration 003; NodeId is SERIAL PK) — confirmed
- dead `"." in node.ip` filter (list_disabled.sql `WHERE ip <> ''`; schema VARCHAR(15) can't hold ipv6) — confirmed
- modified capabilities match real existing specs (use-cases DeallocateIdleNodes; orchestrator Deallocate loop) — confirmed
- impact file list accurate (2 source files, 2 test files, 2 specs, GRACE-lite)
- surfaces-not-touched reasoned on architectural merit, not inherited scope — confirmed
- no "out-of-scope per [other proposal]" argument present — confirmed

### 🔵 Minor (non-blocking, deferred to design.md)

- Log marker convention (add node_id alongside ip) — implicit in proposal, design to be explicit
- Queue dedup semantics — addressed in Why, design to formalize

### Decision

Proposal **frozen** per single-round pass rule (4a). Proceeding to design + specs batch.

## design+specs Round 1 — 2026-07-02

### 🟢 Approved (no outstanding issues)

Reviewer verified against current code/schema/SQL and frozen proposal:
- D1 (return list[Node]) — list[NodeId] alternative rejection sound (would reintroduce round-trip + discard ip/cloud fields)
- D2 (queue rekey to NodeId) — dedup-weakness argument accurate (migration 003 dropped ip UNIQUE; NodeId SERIAL PK; UMessage id-only eq/hash confirmed in queue.py:34-65)
- D3 (consumer takes Node, drops get(ip)) — verified deallocate_node lines 56-57 call contains/disconnect BEFORE `if node.cloud:` (line 63); consumer's `elif` branch only fires when node is None (unreachable in new flow); removing elif is correct, adding defensive duplicate would double-disconnect
- D4 (remove "." in node.ip) — verified list_disabled.sql has `WHERE enabled=FALSE AND ip<>''`; schema ip is VARCHAR(15); dead-code claim correct
- D5 (log convention) — matches node-id-keyed-mutators convention already in deallocate_node/abandon_node; consumer error log line 568 currently missing node_id (will update)
- Non-Goals: all three surfaces reasoned on architectural merit (SSH lifecycle reordering, Task.allocated_ip schema migration + 6-site cascade, cloud SDK no NodeId concept) — not inherited scope
- Risks: staleness analysis sound (disable/remove idempotent-ish); queue dedup strictly safer; type-param migration mechanical

Specs structural checks:
- use-cases MODIFIED block: full requirement copied, name match, 6 scenarios all 4 hashtags, SHALL/MUST consistent
- orchestrator MODIFIED block: full requirement copied, name match, 6 scenarios all 4 hashtags, SHALL consistent
- return type list[Node] flows through both specs coherently
- "." in node.ip removal captured as scenario
- queue rekey UniqueQueue[NodeId, Node] captured as scenario
- consumer no-duplicate-SSH-teardown captured as scenario
- D1-D5 ↔ scenarios 1:1 mapping, no orphans

### 🟡 Minor (applied as declarative fix, not decision-level)

- D3 risk precondition imprecise: wrote "raises before its internal disconnect" but disconnect (line 56-57) runs BEFORE clouds.deallocate (line 83). Fixed to "raises after its internal disconnect" with accurate precondition. Conclusion unchanged (no regression from today).

### Test coverage notes (for implementation phase)

Reviewer flagged edge cases worth adding in tests:
1. Queue dedup on shared-IP nodes (two nodes, same ip, different node_id — old code dedups to one, new code processes both)
2. Phase-2 filter without "." in node.ip (disabled cloud node with valid ipv4 still passes)
3. Consumer error log verifies node_id=%s and ip=%s

### Decision

design.md + specs/ **frozen** per single-round pass rule (4a) after declarative fix to D3 risk wording. Proceeding to tasks.md.

## tasks Round 1 — 2026-07-02

### 🟢 Approved (no outstanding issues)

Reviewer verified:
- Structural: all tasks `- [ ]`, 6 numbered groups, all ≤2h, dependency-ordered (source → tests → GRACE → verify)
- Line references: all 10 spot-checked line refs accurate (deallocate_nodes.py 130/159/161; orchestrator.py 162/539/546/556-568; test files 650/690/602/628)
- Coverage 1:1: every spec scenario (use-cases 6 + orchestrator 6) and every design decision (D1-D5) maps to at least one task; no orphan scenarios, no orphan tasks
- Verification tasks 6.1-6.7 match AGENTS.md (pytest unit/integration, zuban, ruff check/format, lint-imports, openspec validate, grace_check); e2e correctly absent (internal refactor)
- GRACE tasks 5.1/5.2 reference correct graph modules (M-APPLICATION-DEALLOCATE, M-APPLICATION-ORCHESTRATOR) and correct validation command

### 🟡 Minor (applied as declarative fix)

- Task 2.1 parenthetical claimed `NodeId` is already imported at line 41 — actually line 41 imports `TaskId`; `NodeId` is NOT yet imported. Fixed parenthetical to instruct adding `NodeId` alongside `TaskId` in the import block.

### Decision

tasks.md **frozen**. Change `deallocate-node-id-identity` is now apply-ready (all 4 artifacts done, `openspec validate --all` passes 21/21).