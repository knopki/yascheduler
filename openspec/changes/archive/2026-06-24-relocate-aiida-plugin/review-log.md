## proposal Round 1 — 2026-06-24 14:55

Reviewer: @k-reviewer (batch = proposal.md, NEW; baseline = explore-brief.md).
All 13 brief commitments checked against proposal.md; factual claims verified
against source files (aiida_plugin.py, di.py, pyproject.toml, test_di.py,
knowledge-graph.xml, ARCHITECTURE.md, package-facades/spec.md,
testing-unit/spec.md, dependency-injection/spec.md).

### 🔴 Outstanding
None. The proposal faithfully captures all 13 checklist commitments from the
brief. No gaps, contradictions, scope drift, or factual errors found.

Checklist verification (all PASS):
1. File move target flat under `entrypoints/` — STATED (L22). ✓
2. No compat shim, old path ceases to exist — EXPLICIT (L25-26, L33, L91, L103). ✓
3. Entry-point path swap exact — STATED (L27-29, L107-108). ✓
4. Entry-point name `yascheduler` unchanged — NOTED with importlib rationale
   (L30-31, L111-112). ✓
5. make_aiida deletion scope (fn + contract block + MODULE_MAP + SCOPE/LINKS +
   CHANGE_SUMMARY) — STATED (L38-41). ✓ (minor wording imprecision on LINKS —
   see 🟡 #1)
6. TestMakeAiida deletion scope (class + import + SCOPE + MODULE_MAP) — STATED
   (L42-43). ✓
7. entrypoints/__init__.py does NOT re-export YaScheduler — EXPLICIT with
   lazy-public rationale (L36-37). ✓
8. Knowledge graph (M-AIIDA path, M-DI annotation, no CrossLink changes) —
   STATED (L44-47). ✓ (minor wording imprecision on LINKS — see 🟡 #1)
9. Spec deltas: package-facades (outside-set drops aiida_plugin + stale db;
   lazy-public prose drops follow-up; SHALL-remain-loadable + scenario
   reground) and testing-unit (drop make_aiida bullet); dependency-injection
   NO delta — STATED (L48-58, L90-98). ✓ Verified dependency-injection spec
   has zero make_aiida/aiida references.
10. ARCHITECTURE.md full refresh (§1 diagram, §2 table, §2.8, §2.9, §3.7,
    §3.8, §4 tree, §6.2 DELETE, §6.3 DELETE, §7 DELETE) — STATED (L59-70,
    L121-122). ✓ Verified all stale claims exist in current ARCHITECTURE.md.
11. Out-of-scope items (di/daemon/infra-cli migration deferred; no DI
    replacement; no new tests; CHANGELOG untouched) — STATED (L72-78). ✓
12. Capabilities: no NEW; MODIFIED = package-facades + testing-unit only (NOT
    dependency-injection) — STATED (L82-98). ✓
13. BREAKING flags (old module path ceases; make_aiida removed from
    yascheduler.di) — CONSISTENT (L32-33, L40-41, L113-115). ✓

Template check: ## Why / ## What Changes (with ### Out of scope) /
## Capabilities (### New Capabilities + ### Modified Capabilities) /
## Impact — correct. No `<context>`/`<rules>`/`<project_context>` blocks
copied. ✓

Factual verification (all confirmed against source):
- Plugin has zero `from yascheduler` / `import yascheduler` imports (only
  `aiida.*` + stdlib). ✓
- Plugin uses `self.transport.*` (SSH transport) and shells out to
  yasubmit/yastatus — does NOT use Yascheduler client. ARCHITECTURE.md L116
  / L251-252 "uses Yascheduler client" claim is factually wrong, as proposal
  states. ✓
- di.py make_aiida (L237-238) raises NotImplementedError; contract block
  L230-236 has LINKS: M-AIIDA. ✓
- pyproject.toml L57 entry-point matches proposal's "from" string exactly. ✓
- knowledge-graph.xml: M-AIIDA path L81, M-DI fn-make_aiida annotation L385,
  no M-AIIDA in M-DI <depends> L380, no CrossLink/DF touches M-AIIDA. ✓

### 🟡 Addressed (suggested improvements — declarative additions / clarity)

1. **di.py LINKS wording imprecise** (proposal L39, L47). The top-level
   `MODULE_CONTRACT LINKS` field of di.py (L7) does NOT contain `M-AIIDA` —
   it lists `M-APPLICATION-ORCHESTRATOR, M-ENTRYPOINTS-CLIENT, M-CLI-COMMANDS,
   M-APPLICATION-MESSAGE-BUS, M-APPLICATION-ALLOCATION-TRACKER`. The only
   `M-AIIDA` reference in di.py is inside the make_aiida `START_CONTRACT`
   block (L235), which is deleted wholesale with the function. The brief's
   instruction "MODULE_CONTRACT LINKS: drop M-AIIDA" (brief L64) is itself
   slightly off. Recommend proposal clarify: "the only M-AIIDA LINKS
   reference is inside the make_aiida contract block being deleted; the
   top-level LINKS field needs no separate edit." Prevents implementer from
   searching L7 for a non-existent M-AIIDA.

2. **di.py PURPOSE + M-DI `<purpose>` still mention "AiiDA"** (not in scope
   of brief or proposal). di.py L4 PURPOSE: "factories per entry point
   (daemon, CLI, AiiDA)"; knowledge-graph.xml L378 M-DI `<purpose>`:
   "factories per entry point: daemon, CLI, AiiDA." After make_aiida
   deletion, the "AiiDA" token in both is stale (no AiiDA factory remains).
   The brief's di.py section lists SCOPE/LINKS/MODULE_MAP/CHANGE_SUMMARY
   edits but omits PURPOSE; the M-DI graph section omits `<purpose>`. Both
   the brief and proposal miss this. Recommend explicit note that PURPOSE
   and `<purpose>` drop the "AiiDA" mention to keep the contract internally
   consistent with the edited SCOPE.

3. **ARCHITECTURE.md §4 tree: client.py-at-root not explicit** (proposal
   L66-68). Proposal says "drops aiida_plugin.py from root" but does not
   explicitly state `client.py` REMAINS at root as a shim. Brief L157
   specifies "client.py at root remains as shim." A reader could infer both
   root files are dropped. Recommend adding "client.py remains at root as
   compat shim" to the §4 tree description.

4. **ARCHITECTURE.md §6 numbering gap** (proposal L68-69). After deleting
   §6.2 and §6.3, §6 contains §6.1 and §6.5 (note: §6.4 is already absent
   today, so gaps are precedent). Proposal describes the doc as a "full
   refresh" but does not say whether §6.5 is renumbered. Minor; flag for
   design.md / implementer discretion.

5. **package-facades spec L78 prose examples go stale** (proposal L48-51).
   L78 reads "The practical risk of yascheduler.shared importing an entry
   point, the legacy DB layer, or the AiiDA plugin is negligible." After
   this change, "the legacy DB layer" (yascheduler.db removed) and "the
   AiiDA plugin" (relocated into entrypoints, caught by the layers contract)
   are no longer apt examples of root-resident outside-set modules. The
   proposal's umbrella "outside-layer-set exemption list drops
   yascheduler.aiida_plugin ... and the stale yascheduler.db" covers the
   enumerated lists (L76, L246, L253) but may not surface the prose example
   at L78. Recommend explicit mention so the spec delta does not leave L78
   internally inconsistent with the trimmed enumeration.

6. **package-facades spec L253 scenario enumeration** (brief L108-109 calls
   it out as a distinct touchpoint from the L75-80 prose). Proposal's
   umbrella "exemption list drops" phrasing covers it, but the brief
   distinguished the scenario enumeration as a separate edit. Explicit
   mention ensures the scenario's enumerated list (`yascheduler.config,
   ... yascheduler.aiida_plugin ...`) is trimmed alongside the requirement
   prose. (Note: L253 does NOT list yascheduler.db, so only aiida_plugin is
   removed there — the brief's "same removals" is slightly imprecise.)

### 🟢 Good
- All 13 brief commitments captured; no scope drift, no contradictions.
- BREAKING flags applied consistently and scoped precisely (only deep-path
  importers affected; AiiDA discovery by name is preserved, consistent with
  AGENTS.md public-interface-stability rule for the AiiDA entrypoint).
- Rejected alternatives stay rejected and are not re-litigated in the
  proposal body (no shim, no subpackage, no facade re-export, no new tests,
  no DI replacement) — they surface only as positive statements of the
  chosen path.
- Factual claims all verified against source: zero yascheduler imports in
  the plugin, SSH-transport-not-client usage, NotImplementedError stub,
  entry-point name unchanged, dependency-injection spec has no make_aiida
  requirement.
- Entry-point NAME stability rationale (`importlib.metadata.entry_points`
  discovery by name) is correctly stated — this is the key argument that
  the path swap is non-breaking for AiiDA users and only breaking for
  direct deep-path importers.
- Knowledge-graph update scope is correct: no CrossLink/DF changes needed
  (verified none reference M-AIIDA); only M-AIIDA path + M-DI annotation.
- Template structure correct; no forbidden context/rules/project_context
  blocks.

### Recommendation
**APPROVE WITH NOTES.** No blocking (🔴) issues. The 🟡 items are
clarity/completeness improvements that can be folded in as declarative
additions to proposal.md before freeze, or deferred to design.md / the
specs delta author's checklist. None would cause an implementer to write
incorrect code given the brief as a cross-reference, but #1 and #2 in
particular are worth a one-line clarification to avoid implementer
confusion (non-existent M-AIIDA in L7 LINKS; stale "AiiDA" in PURPOSE).

## proposal Round 1 — resolution — 2026-06-24 15:05

Batch: proposal.md. Reviewer: @k-reviewer. Result: APPROVE WITH NOTES
(no 🔴).

Folded into proposal.md as declarative additions before freeze:
- 🟡 #1 — clarified that the only `M-AIIDA` reference in `di.py` is inside the
  `make_aiida` contract block being deleted; the top-level `MODULE_CONTRACT
  LINKS` field (L7) does NOT list `M-AIIDA` and needs no separate edit.
- 🟡 #2 — added that `di.py` `MODULE_CONTRACT PURPOSE` (L4) and the graph
  `M-DI` `<purpose>` drop the "AiiDA" mention to stay consistent with the
  trimmed `SCOPE`/`<annotations>`.

Deferred to design.md / specs-delta author's checklist (not blocking):
- 🟡 #3 — §4 tree: state `client.py` remains at root as shim.
- 🟡 #4 — §6 numbering after §6.2/§6.3 deletion (implementer discretion).
- 🟡 #5 — package-facades L78 prose examples ("legacy DB layer", "AiiDA
  plugin") go stale; spec delta must not leave L78 inconsistent with the
  trimmed enumeration.
- 🟡 #6 — package-facades L253 scenario enumeration trims `aiida_plugin`
  only (no `yascheduler.db` present at L253).

**proposal.md frozen.** Single-round pass per the pass rule (no 🔴 in the
round).

## design Round 1 — 2026-06-24 15:55

Reviewer: @k-reviewer (batch = design.md, NEW; baseline = frozen proposal.md + explore-brief.md).

### 🔴 Outstanding
None. The design is consistent with the frozen proposal, fully captures all brief commitments, follows the template structure, and makes correct factual claims verified against source.

### 🟡 Addressed (deferred items from proposal review now confirmed present)

All 6 🟡 items from the proposal review checklist addressed in design.md:

1. **🟡 #3 — §4 tree client.py-at-root** → D5 `§4 tree` explicitly says `client.py remains at root as shim`. ✓
2. **🟡 #4 — §6 numbering gap** → D5 says §6.2/§6.3 DELETE but does not renumber §6.5 (no change from the proposal's position; implementer discretion still applies). Noted but not a defect. ✓
3. **🟡 #5 — package-facades L78 prose** → D6 explicitly says "L78 prose ('the legacy DB layer, or the AiiDA plugin is negligible') also goes stale and is rewritten." ✓
4. **🟡 #6 — package-facades L253 scenario** → D6 explicitly says "L253 does NOT list yascheduler.db, so only aiida_plugin is removed there." ✓

The two items folded into proposal.md before freeze (🟡 #1 LINKS clarification, 🟡 #2 PURPOSE cleanup) are naturally reflected in D4's scope.

### 🟢 Good

**Proposal consistency** — every section of the frozen proposal's "What Changes" is mapped to one or more Decisions or Goal items. No scope drift, no new capabilities beyond what the proposal implied (D6's `yascheduler.db` cleanup was already in the proposal's package-facades delta scope).

**Brief commitment coverage** — verified against all touchpoints:

| Touchpoint | Design location | Status |
|---|---|---|
| File move to flat `entrypoints/aiida_plugin.py` | D1 + Goals | ✓ |
| No shim, old path ceases | D2 + Non-Goals | ✓ |
| Entry-point path swap, name preserved | Context + Migration step 3 | ✓ |
| `make_aiida` deletion (fn, contract, MODULE_MAP, PURPOSE/SCOPE, `<fn-make_aiida>`, `<purpose>`) | D4 + Goals | ✓ |
| TestMakeAiida deletion | Goals | ✓ |
| entrypoints/__init__.py: no YaScheduler re-export | D3 + Goals | ✓ |
| Knowledge graph: M-AIIDA path + M-DI cleanup | Goals | ✓ |
| Spec deltas: package-facades + testing-unit | Goals + D6 | ✓ |
| ARCHITECTURE.md full refresh (all 8+ sections) | D5 | ✓ |
| `yascheduler.db` cleanup from outside-set lists | D6 | ✓ |

**Decision quality** — D1, D2 carry explicit alternatives (subpackage path, shim treatment). D3, D4, D5, D6 carry rationale even without strict "Alternatives" subheads; none silently overrides a proposal commitment.

**Risks** — both BREAKING changes explicitly flagged:
- Old `yascheduler.aiida_plugin` module path ceases → mitigation (entry-point name unchanged, no known callers). ✓
- `make_aiida` removed from `yascheduler.di` → mitigation (only test did it, test updated in this change). ✓

**Non-Goals** match the proposal's "Out of scope" exactly (di/daemon/infra-cli deferred; no DI replacement; no new tests; CHANGELOG untouched; no facade re-export; no shim). ✓

**Template** — `## Context / ## Goals / Non-Goals / ## Decisions / ## Risks / ## Migration Plan / ## Open Questions`. No `<context>`/`<rules>`/`<project_context>` blocks. ✓

**Factual accuracy** — verified against source (di.py make_aiida stub, plugin zero yascheduler imports, pyproject.toml entry-point, ARCHITECTURE.md stale claims, knowledge-graph M-AIIDA/M-DI state, package-facades spec outside-set enumeration). All claims in §Context match current codebase state.

### Informational observations (non-blocking)

1. **§6 numbering gap still open** — D5 deletes §6.2 and §6.3 but does not specify whether §6.5 is renumbered. Identical to [proposal review 🟡 #4](review-log.md#L93-L97), deferred to implementer discretion. No action needed.

2. **shared/ subtree content** — D5 says "show `shared/` subtree" without enumerating files. The actual `yascheduler/shared/` contains 4 files (`__init__.py`, `async_utils.py`, `compat.py`, `variables.py`); the current ARCHITECTURE.md shows only `async_utils.py`. The design correctly leaves file enumeration to the implementer's ground-truth check.

### Recommendation

**APPROVE.** No blocking issues. The design is correct, consistent, and complete against the frozen proposal and the explore brief.

## design Round 1 — resolution — 2026-06-24 15:58

Batch: design.md. Reviewer: @k-reviewer-fast. Result: APPROVE (no 🔴).
All 4 deferred 🟡 items from the proposal review confirmed addressed in
design.md (§4 tree: client.py remains at root as shim; §6 numbering gap left
to implementer discretion; package-facades L78 prose staleness covered by D6;
L253 scenario enumeration covered by D6).

No edits required. **design.md frozen.** Single-round pass per the pass rule.

## specs Round 1 — 2026-06-24 15:06

Batch: two delta spec files (NEW, not yet frozen). Reviewer: @k-reviewer.
Baselines: frozen proposal.md, frozen design.md, live specs at
`openspec/specs/package-facades/spec.md` and
`openspec/specs/testing-unit/spec.md`.

### 🔴 Outstanding

None. All 5 MODIFIED requirements in both delta files pass the 6-item
checklist (MODIFIED header, exact header match, full content, no dropped
scenarios, 4-hashtag scenarios, at least one scenario per requirement).
No factual errors, no scope drift, no stale `<context>`/`<rules>`/`<project_context>` blocks, no NEW/REMOVED capabilities.

### 🟢 Good

#### `package-facades/spec.md` — 4 MODIFIED requirements

**A. "Shared kernel config-import prohibition"**
- Header matches live spec L60 exactly (`### Requirement: Shared kernel config-import prohibition`). ✓
- Outside-set enumeration drops `yascheduler.db` and `yascheduler.aiida_plugin`; enumeration now reads `yascheduler.data`, `yascheduler.di`, `yascheduler.client`. ✓
- Rationale prose rewritten: "the legacy DB layer, or the AiiDA plugin" → "an entry point or a compat shim". ✓
- Both original scenarios preserved verbatim. ✓

**B. "Entrypoints layer facade"**
- Header matches live spec L165 exactly (`### Requirement: Entrypoints layer facade`). ✓
- `aiida_plugin.py` dropped from lazy-public follow-up sentence; explicit statement that AiiDA plugin is NOT re-exported by the facade (discovered via entry-point registry). ✓
- All 3 original scenarios preserved verbatim. ✓
- New scenario "AiiDA plugin is not re-exported by the entrypoints facade" added with `####` heading. ✓

**C. "Outside-layer-set exemptions"**
- Header matches live spec L236 exactly (`### Requirement: Outside-layer-set exemptions`). ✓
- `yascheduler.aiida_plugin` bullet (live L246) dropped. `yascheduler.db` is NOT present in this requirement (verified live L242-247). ✓
- Outside-set scenario enumeration drops only `yascheduler.aiida_plugin`. ✓
- All 4 original scenarios preserved verbatim. ✓

**D. "Public API stability"**
- Header matches live spec L437 exactly (`### Requirement: Public API stability`). ✓
- `yascheduler.aiida_plugin` bullet rewritten to key on entry-point *name* `yascheduler` + object path `yascheduler.entrypoints.aiida_plugin:YaScheduler`. Notes `importlib.metadata.entry_points` discovery by name, BREAKING deep-path removal (no shim). ✓
- AiiDA plugin scenario regrounded: "under its entry-point name" with explicit entry-point group and object path. ✓
- New scenario "Old aiida_plugin module path is gone" added — correctly specifies `ModuleNotFoundError`. ✓
- All other 6 original scenarios preserved verbatim (Yascheduler resolves, deep shim path, constructor extension, path constants, to_sync, compat.py removed). ✓

#### `testing-unit/spec.md` — 1 MODIFIED requirement

**E. "Dependency injection factories"**
- Header matches live spec L135 exactly (`### Requirement: Dependency injection factories`). ✓
- `make_aiida raises NotImplementedError` bullet dropped; other 3 bullets preserved (`CLIDeps`, `make_cli_deps`, `make_daemon`). ✓
- Single scenario "make_cli_deps returns CLIDeps with PostgresUnitOfWork factory" preserved verbatim. ✓

#### Global checks

- Both delta files use `## MODIFIED Requirements` header (not `## Requirements`). ✓
- No `<context>`/`<rules>`/`<project_context>` blocks copied. ✓
- No NEW capabilities or REMOVED requirements introduced — only MODIFIED. ✓
- All scenarios use `####` (4 hashtags). ✓
- Every requirement has at least one scenario. ✓
- No factual errors: entry-point group `aiida.schedulers` confirmed from `pyproject.toml` L56; object path `yascheduler.entrypoints.aiida_plugin:YaScheduler` consistent across all artifacts; `yascheduler.db` module confirmed absent from codebase (stale reference correctly removed). ✓

### Recommendation

**APPROVE.** No blocking issues. Both delta spec files are correct, complete, and consistent with the frozen proposal and design. The 5 MODIFIED requirements faithfully implement D1-D6 from design.md.

## specs Round 1 — resolution — 2026-06-24 16:08

Batch: specs (package-facades + testing-unit delta files). Reviewer:
@k-reviewer-fast. Result: APPROVE (no 🔴).

All 5 MODIFIED requirements verified: exact header match to live spec, full
updated content (not partial diff), no dropped scenarios, correct 4-hashtag
formatting, ≥1 scenario each. No factual errors, no scope drift, no stale
blocks copied. Deltas faithfully implement D1-D6 from frozen design.md.

No edits required. **specs frozen.** Single-round pass per the pass rule.

## tasks Round 1 — 2026-06-24 16:10

Batch: tasks.md (NEW, not yet frozen). Reviewer: @k-reviewer.
Baselines: frozen proposal.md, frozen design.md, frozen specs delta files.

### 🔴 Outstanding
None.

### 🟡 Addressed (fix before freeze)

1. **Task 4.1 — "both test methods" is inaccurate**
   Location: tasks.md:18
   Problem: Says "both test methods `test_raises_not_implemented_error`" but `class TestMakeAiida` (L172-183 of `tests/unit/test_di.py`) contains **one** test method only.
   Fix: Change "both test methods `test_raises_not_implemented_error`" → "the test method `test_raises_not_implemented_error`". Line range L172-183 stays correct.

### 🟢 Good

**Coverage**: Every frozen commitment checked:
- D1 (flat entrypoints/aiida_plugin.py) → 1.1 ✓
- D2 (no shim, entry-point path swap) → 2.1 ✓
- D3 (facade no re-export) → 1.2 explicitly forbids adding YaScheduler/YaschedJobResource to __all__ ✓
- D4 (make_aiida deletion) → 3.1-3.3 (di.py) + 4.1-4.3 (tests) ✓
- D5 (ARCHITECTURE.md full refresh) → 8.1-8.10, every D5 subsection has a corresponding task ✓
- D6 (yascheduler.db cleanup) → 6.2, 6.4 ✓
- Knowledge graph (M-AIIDA path + M-DI annotation/purpose) → 5.1-5.3 ✓
- package-facades delta (4 MODIFIED requirements) → 6.1-6.5 ✓
- testing-unit delta (1 MODIFIED requirement) → 7.1 ✓
- Verification (pytest, lint-imports, ruff, zuban, grace_check, openspec validate, entry-point smoke, import smoke, stale-reference sweep) → 9.1-9.10 ✓

**No scope drift**: No tasks touch di.py/daemon/infra-cli migration, DI wiring replacement, new AiiDA tests, CHANGELOG, facade re-export of YaScheduler, or compat shim at old path. ✓

**Line references factually accurate** (verified against source):
- di.py L4 PURPOSE / L5 SCOPE / L7 LINKS / L13 MODULE_MAP / L230-238 make_aiida block ✓
- test_di.py L6 SCOPE / L14 MODULE_MAP / L39 import / L172-183 class ✓
- KG L81 M-AIIDA path / L377-387 M-DI block / L378 purpose / L385 fn-make_aiida ✓
- pyproject.toml L56-57 entry-point ✓

**Tasks 6.x/7.x framing correct**: "verify + finalize" matches the prior review batch where spec delta files were already reviewed and frozen. Tasks ask for confirmation of content, not creation from scratch. ✓

**Task ordering respects dependencies**: move (1.x) → entry-point swap (2.x) → di.py deletion (3.x) → test cleanup (4.x) → graph (5.x) → spec verify (6.x/7.x) → ARCHITECTURE.md (8.x) → verification (9.x). ✓

**Verifiability**: Every task has concrete completion criteria. Verification tasks 9.1-9.10 all carry exact shell commands (9.8 includes reinstall prerequisite and python one-liner; 9.10 has correct glob exclusions). ✓

**Consistency with design.md Migration Plan**: Steps (reinstall → entry-point smoke → pytest → lint-imports → ruff → zuban → grace_check → openspec validate) match tasks 9.1-9.8 order. ✓

### Recommendation

**APPROVE WITH NOTES.** Single 🟡 item (task 4.1 "both test methods" → one test method). Fix before freeze is trivial. No 🔴 issues.

## tasks Round 1 — resolution — 2026-06-24 16:15

Batch: tasks.md. Reviewer: @k-reviewer-fast. Result: APPROVE WITH NOTES
(no 🔴). One 🟡 fixed before freeze:

- 🟡 Task 4.1 said "both test methods" — `TestMakeAiida` has one test method
  (`test_raises_not_implemented_error`). Corrected to "the test method".

Full coverage of D1-D6 confirmed; no scope drift; line references verified
against source; spec-delta framing (verify + finalize) correct; ordering
respects dependencies; verification tasks carry concrete commands.

**tasks.md frozen.** Single-round pass per the pass rule (no 🔴 in the round).

All `applyRequires` artifacts done: proposal ✓, design ✓, specs ✓, tasks ✓.
