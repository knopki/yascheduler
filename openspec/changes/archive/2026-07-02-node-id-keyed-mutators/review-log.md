# Review Log — node-id-keyed-mutators

## specs Round 1 — 2026-07-02

### 🔴 Fixed

(none)

### 🟡 Addressed

(none)

### 🔴 Outstanding

1. **cli-commands is a missing Modified Capability** — the proposal's Capabilities section lists `domain-ports`, `postgres-persistence`, and `use-cases` but does not list `cli-commands`. However, the proposal's What Changes section and D2 explicitly change `_remove_node_hard`/`_remove_node_soft` helper signatures from `(deps, ip: str)` to `(deps, node: Node)`, and the cli-commands spec has spec-level REQUIREMENTS that reference these function signatures and ip-keyed mutator calls. These REQUIREMENTS would be stale after archive unless a delta spec updates them.

   **Affected spec content in `openspec/specs/cli-commands/spec.md`:**

   - **Requirement: yasetnode dispatches add and remove paths** (lines 1201–1268):
     - Line 1206: validation UoW logic `already_there = await uow.nodes.get(spec.host)` — describes a boolean existence check that passes `spec` to helpers. Under the new design, validation resolves a `Node` to pass to helpers; the dispatch flow changes.
     - Lines 1217–1218: `_remove_node_hard(deps, spec)` — signature must update to `_remove_node_hard(deps, node: Node)`.
     - Lines 1220–1221: `_remove_node_soft(deps, spec)` — signature must update to `_remove_node_soft(deps, node: Node)`.
     - Lines 1250–1252: Scenario asserts `uow.nodes.remove("10.0.0.1")` — must become `uow.nodes.remove(node.node_id)` (or parameterized).
     - Line 1256: Scenario asserts `uow.nodes.disable("10.0.0.1")` — must become `uow.nodes.disable(node.node_id)`.
     - Line 1260: Scenario asserts `uow.nodes.remove("10.0.0.1")` — must become `uow.nodes.remove(node.node_id)`.

   - **Requirement: yasetnode positional discriminates node_id from host** (lines 1129–1136):
     - Lines 1134–1135: `"ip-keyed \`nodes.disable(node.ip)\` / \`nodes.remove(node.ip)\` mutators — the ip-keyed mutators are unchanged"` — this statement becomes false after the change; mutators are node_id-keyed. Helpers still use `node.ip` for `tasks.list_ids_by_ip_and_status(ip, RUNNING)` (Surface C, unchanged), but `disable`/`remove` receive `node.node_id`.

   - **Requirement: yasetnode module path and GRACE-lite markup** (lines 1280–1282):
     - Declares `_remove_node_hard(deps, spec)` and `_remove_node_soft(deps, spec)` as private pure function signatures — must update to `(deps, node: Node)`.

   **Fix:** Add `cli-commands` to proposal.md's Modified Capabilities and create `specs/cli-commands/spec.md` with EXACTLY the modified REQUIREMENTS listed above (full blocks, not partial edits). The unchanged requirements (argparse grammar, exit codes, output messages, etc.) are correct as-is and do NOT need to appear in the delta.

   **Severity:** 🔴 — At archive time, the main cli-commands spec will retain ip-keyed mutator language and old helper signatures, creating a contradiction between the spec and the implementation. This is a specification integrity failure that will confuse future readers and violate OpenSpec's contract-first principle.

## specs Round 2 — 2026-07-02

### 🔴 Fixed

1. **cli capability added to proposal.md Modified Capabilities** — Round 1 🔴 item resolved. Proposal.md line 44 now lists `cli` in Modified Capabilities: "`cli`: `yasetnode positional discriminates node_id from host` and `yasetnode dispatches add and remove paths` REQUIREMENTS change". The capability name `cli` matches the actual spec path (`openspec/specs/cli/spec.md`), correcting the round-1 reference which used the nonexistent name `cli-commands`.

2. **cli/spec.md delta spec created** — `openspec/changes/node-id-keyed-mutators/specs/cli/spec.md` (147 lines) exists with full-block replacements for both modified requirements. The file lists `## MODIFIED Requirements` and contains exactly the two requirements:
   - "yasetnode positional discriminates node_id from host" (lines 3-68)
   - "yasetnode dispatches add and remove paths" (lines 69-147)
   Both are full blocks (declarative SHALL text + all scenarios), not partial edits.

### 🟡 Addressed

(none — the round 1 items are fully resolved in round 2's artifact set)

### 🔴 Outstanding

(none)

### 🟡 Observations (not blocking, worth noting)

1. **Stale function signatures in sibling requirement "yasetnode module path and GRACE-lite markup"** — `openspec/specs/cli/spec.md` lines 1358-1359 still list `_remove_node_hard(deps, spec)` and `_remove_node_soft(deps, spec)` (the OLD signatures). This requirement is NOT among the two modified by the delta, so it remains in the main spec as-is after archive. The function list there will be stale (correct new signatures: `_remove_node_hard(deps, node: Node)`, `_remove_node_soft(deps, node: Node)`).

   **Impact:** Low — this requirement's primary purpose is file path, GRACE-lite markup, and YAGNI for use-case extraction. The function list is incidental. The two correctly modified requirements carry the authoritative signature contract. A future reader cross-referencing the "module path" requirement's function list would see outdated parameter types, which could cause momentary confusion but not implementation error.

   **Options:**
   - Accept as-is (low impact, no functional contradiction)
   - If archival hygiene demands consistency, add `cli` Modified Capability scope to also replace the "module path" requirement's function-list SHALL text (lines 1357-1360). The scenarios in that requirement do NOT need updating — they test file path, GRACE-lite markers, and FIXME absence, not parameter types.

### ✅ Verified Correct

- **Q1: Full-block replacement** — Both modified requirements carry full declarative text + all scenarios, replacing the original blocks. No partial edits. ✓

- **Q2: Alignment with design D2** — Scenarios resolve Node via `get_by_id` (node_id path) and `get(ip)` (host_spec path), pass `Node` to helpers. Helper signatures are `(deps, node: Node)`. Text: "the validation UoW resolves the `Node` early". All match D2. ✓

- **Q3: node_id-keyed mutators, ip-keyed tasks lookup** — Scenarios use `uow.nodes.remove(NodeId(7))`, `uow.nodes.disable(NodeId(7))`. Text: "`node.node_id` for the `nodes.disable(node.node_id)` / `nodes.remove(node.node_id)` mutators and `node.ip` for `tasks.list_ids_by_ip_and_status(node.ip, TaskStatus.RUNNING)` (Surface C — ip-keyed, unchanged)". ✓

- **Q4: "remove helpers take Node not ip" scenario** — Present at delta spec lines 137-139 with correct assertion: `(deps, node: Node)` not `(deps, ip: str)`. ✓

- **Q5: No contradictions with frozen proposal/design** — The delta contains no decision-level content that contradicts proposal.md or design.md. The D18 reference (line 105) is a carry-over from the original spec, not new content. ✓

- **Q6: Other requirements not stale** — "yasetnode gateway lifecycle" (add path only, unchanged) ✅. "yasetnode success messages" (uses `node.ip`, still correct) ✅. Only the "module path" function list is stale (see 🟡 observation above). No ip-keyed mutator references remain in unchanged requirements that would be contradicted by the change. ✓

- **Q7: All Modified Capabilities have delta specs** — domain-ports ✅, postgres-persistence ✅, use-cases ✅, cli ✅. testing-unit does not need a separate delta: its "Domain port Protocol conformance" requirement (testing-unit spec lines 92-101) doesn't spell out `StubNodeRepository` method signatures — it's a generic Protocol conformance check. The signature change flows from the domain-ports delta implicitly. ✓

- **`openspec validate --all --json`** — The `node-id-keyed-mutators` change passes validation (1 change, 1 valid, 0 errors). The 1 overall failure is the pre-existing `cloud` spec (two requirements missing SHALL/MUST keywords), unrelated to this change. ✓

## tasks Round 1 — 2026-07-02

### 🔴 Fixed

(none)

### 🟡 Addressed

(none)

### 🟡 Observations (not blocking, worth correcting)

1. **Task 8.3: incorrect count of `disable` asserts** — Says "update the 6 `disable` asserts" in `test_application_use_cases.py`, but the file has only 2 `disable` assertions that reference an IP string (`assert_called_once_with("10.0.0.1")` at line 597 and `assert_awaited_once_with("10.0.0.1")` at line 752). There are also 3 `remove` assertions (lines 363, 430, 753). The total IP-string assertions across both methods is 5, not 6.

   **Fix:** Correct the count to match reality, or drop the count entirely ("update all `disable` and `remove` mock-call asserts to expect `NodeId`").

   **Impact:** Low — the developer will find all assertions regardless when running tests. But the wrong count could confuse readers.

2. **Task 10.1: `M-PERSISTENCE` should be `M-PERSISTENCE-POSTGRES`** — Says to update `M-PERSISTENCE` `<annotations>` for the four `PostgresNodeRepository` mutators, but `PostgresNodeRepository` lives in `M-PERSISTENCE-POSTGRES` (knowledge graph line 633, path `yascheduler/infra/persistence/postgres.py`). `M-PERSISTENCE` (line 600) is the package facade at `yascheduler/infra/persistence/__init__.py`.

   **Fix:** Change "M-PERSISTENCE" to "M-PERSISTENCE-POSTGRES" in task 10.1.

   **Impact:** Low — a developer checking the graph will see the mismatch. But a literal reading adds annotations to the wrong element.

3. **Task 11.5: wrong pre-existing spec name** — Says "the pre-existing `cloud-providers` failure", but the spec is named `cloud` (`openspec/specs/cloud/`), confirmed in review-log line 82 and the specs directory listing.

   **Fix:** Change "cloud-providers" to "cloud" in task 11.5.

   **Impact:** Low — cosmetic. The intent (pre-existing, unrelated) is clear.

4. **Dead helper functions not cleaned up** — After tasks 7.1/7.4 refactor `_manage_node_async` to resolve and pass a `Node` directly, the helpers `_get_by_ip` (line 406) and `_remove_ip` (line 412) in `manage_node.py` become dead code. No task explicitly removes them or acknowledges they should stay.

   **Fix:** Either add a subtask to remove both helpers, or add a note that they are intentionally left as dead code (unlikely).

   **Impact:** Low — dead code is a hygiene issue, not a correctness issue. Unreferenced functions won't cause runtime errors.

### ✅ Verified Correct

- **Q1: Coverage** — Every implementation step from all four delta specs and the design is covered by at least one task. Specifically:
  - domain-ports spec (sig changes, docstring, contracts): 1.1–1.4 ✅
  - postgres-persistence spec (4 SQL files, 4 Impl methods): 2.1–2.4, 3.1–3.5 ✅
  - use-cases spec (deallocate_node, deallocate_nodes loop, abandon_node, tmp-cleanup): 4.1–4.3, 5.1–5.2, 6.1–6.3 ✅
  - cli spec (validation UoW, helper sigs, dispatch, contracts): 7.1–7.5 ✅
  - Tests (StubNodeRepository, existing assert updates, new tests): 8.1–8.4, 9.1–9.4 ✅
  - GRACE-lite (knowledge-graph, contracts, module maps): 1.3, 1.4, 3.5, 4.3, 5.2, 6.3, 7.5, 10.1, 10.2 ✅
  - Verification: 11.1–11.6 ✅

- **Q2: Ordering** — Tasks are ordered correctly by dependency: Protocol → SQL → Impl → Application call-sites → CLI → Tests → GRACE → Verification. No task depends on a later task. ✅

- **Q3: Task size** — Every task is under 2 hours. The largest (7.1–7.5 CLI refactoring) is ~1.5h. ✅

- **Q4: Missing tasks** — No missing tasks found:
  - Design D5 (logs add `node_id`): 4.1, 5.1 ✅
  - Design D6 (no rowcount check): implicit in 6.1/6.2 ("skip if None") ✅
  - StubNodeRepository: 8.1 ✅
  - knowledge-graph.xml: 10.1 ✅

- **Q5: No contradictions with frozen artifacts** — All tasks align with the frozen specs, design, and proposal. The tasks describe the same signature changes, SQL key changes, call-site changes, and test updates as the specs. ✅

- **Q6: Task 11.5 correctly notes pre-existing failure** — Correctly identifies the `openspec validate` failure as pre-existing and unrelated. Minor naming inaccuracy (says "cloud-providers", actual name is "cloud") but intent is correct. ✅

- **No blocking issues** — All observations are minor inaccuracies or hygiene items. No 🔴 severity issues found.
