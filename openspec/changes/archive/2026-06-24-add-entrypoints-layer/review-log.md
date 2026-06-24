# Review Log — add-entrypoints-layer

## proposal Round 1 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md`
Frozen before this round: none (first batch)
New this round: `proposal.md`

### 🔴 Fixed
- (none raised)

### 🟡 Addressed
- Capability granularity: `entrypoints-layer` folded into `package-facades` as a
  modification (no new spec file). New Capabilities section now states `_None._`
  with rationale.
- Compat-shim rationale: added the `sys.modules` explanation to the What Changes
  bullet (binding-only in `__init__.py` fails because the module is not
  registered; a real shim file is required), with reference to explore-brief.md
  §Rejected alternatives.

### 🔴 Outstanding
- (none)

**Verdict: PASS.** proposal.md frozen.
## design Round 1 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: `proposal.md` (frozen)
New this round: `design.md`


### 🔴 Fixed
- (none raised)

### 🟡 Addressed

1. **D5 KG inventory — CrossLink/DF references to M-CLIENT incomplete after rename**
   After renaming `<M-CLIENT>` → `<M-ENTRYPOINTS-CLIENT>`, all CrossLink/DF references to `M-CLIENT` become dangling. The design explicitly updates `M-MAIN.depends` and `M-AIIDA.LINKS` but omits:
   - `<CrossLink from="M-CLIENT" to="M-APPLICATION-QUERY-TASKS" ...>` (line 859)
   - `<CrossLink from="M-CLIENT" to="M-DI" ...>` (line 902)
   - `<DF-SUBMIT>M-CLIENT -> M-DI -> ...</DF-SUBMIT>` (line 847)
   - `<DF-AIIDA-INTEGRATION>M-AIIDA -> M-CLIENT</DF-AIIDA-INTEGRATION>` (line 850)
   `grace_check.py`'s `_check_crosslink_refs` and `_check_dataflow_refs` catch these at runtime, so the implementation will not silently break — but the design inventory should list them for completeness.
   **Recommendation:** Add the four missing references to D5's scope, or note that the implementation tasks must update all `M-CLIENT` mentions in the KG (not just depends/links).

2. **D5 M-MAIN.depends — should reference M-ENTRYPOINTS (facade), not M-ENTRYPOINTS-CLIENT (deep module)**
   After the change, `yascheduler/__init__.py` imports via `from .entrypoints import Yascheduler` — the layer facade (`M-ENTRYPOINTS`), not the deep module. The design says "replace M-CLIENT with M-ENTRYPOINTS-CLIENT (reached via M-ENTRYPOINTS facade)" which is ambiguous. If literally taken, `M-MAIN.depends` would read `M-ENTRYPOINTS-CLIENT, M-SHARED`, but the import goes through the facade, so it should read `M-ENTRYPOINTS, M-SHARED`. Symmetry argument: `M-ADAPTERS` is what M-MAIN's dependents reference for `infra/`, not the deep SSH/Gateway nodes.
   **Recommendation:** Clarify D5 to state `M-MAIN.depends` = `M-ENTRYPOINTS, M-SHARED` (the facade node).

3. **Risks section has 3 [Risk] items, not 2**
   The third item ("import-linter reports a new violation") is labeled `[Risk]` but the analysis confirms it does not occur (shim is outside-layer-set). Mitigation is "none needed; passes". This is a non-issue formally tagged as a risk — it inflates the risk count and may confuse readers.
   **Recommendation:** Reclassify as a note or deducible observation (e.g., a checkmark that `lint-imports` continues to pass), not a risk with a no-op mitigation.

4. **Migration plan verify step — missing `zuban check`, `ruff format --check`, integration/e2e**
   The design lists 5 verify commands. AGENTS.md specifies 3 additional checks: `uv run zuban check`, `uv run ruff format --check .`, `uv run pytest -m integration`, `uv run pytest -m e2e`. Given no behavioral change, integration/e2e are optional. However `zuban check` (static analysis tool listed in pyproject.toml dev-deps) and `ruff format --check` are fast formatting/integrity checks the project runs routinely. Omitting them means a CI-passing change could be blocked by a formatting violation.
   **Recommendation:** Add `uv run zuban check` and `uv run ruff format --check .` to the verify step; optionally add the integration/e2e test commands.

5. **Source MODULE_CONTRACT DEPENDS field update not addressed**
   `yascheduler/__init__.py` currently has `DEPENDS: M-CLIENT, M-SHARED` in its MODULE_CONTRACT. After renaming M-CLIENT → M-ENTRYPOINTS, this field must become `DEPENDS: M-ENTRYPOINTS, M-SHARED`. The design covers the knowledge graph XML but not the source-file contract fields. While `grace_check.py` only validates LINKS fields (not DEPENDS) against the XML, the stale DEPENDS would misrepresent the dependency.
   **Recommendation:** Add a note in D5 or the migration plan to update `yascheduler/__init__.py` DEPENDS field to `M-ENTRYPOINTS, M-SHARED`.

### 🔴 Outstanding
- (none)

**Verdict: APPROVE WITH NOTES.** No blocking issues. The design is consistent with the frozen proposal across all 6 decisions (D1–D6). Five 🟡 items above should be addressed before or during implementation — the most important is #1 (KG CrossLink/DF completeness) since `grace_check.py` will error on dangling references if missed. Items #2–#5 are clarity/consistency improvements.

### 🟡 Addressed (post-review fixes in design.md)

1. D5 KG inventory expanded to enumerate all 7 `M-CLIENT` reference sites
   (M-MAIN.depends, the node itself, DF-SUBMIT, DF-AIIDA-INTEGRATION, 3
   CrossLinks) — not just depends/links.
2. D5 `M-MAIN.depends` clarified to `M-ENTRYPOINTS, M-SHARED` (facade node, not
   deep module) — matches the layer-facade import convention.
3. Risks section: dropped the non-issue `[Risk] import-linter reports a new
   violation` (confirmed non-occurring). Now 1 risk + 2 trade-offs.
4. Migration plan verify step expanded with `ruff format --check .` and
   `zuban check`; integration/e2e noted as optional smoke checks.
5. Migration plan step 3 now explicitly includes updating the
   `yascheduler/__init__.py` source-file `MODULE_CONTRACT DEPENDS` field
   (`M-CLIENT, M-SHARED` → `M-ENTRYPOINTS, M-SHARED`).

**Final verdict: PASS.** design.md frozen.


## specs Round 1 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: `design.md` (frozen), `openspec/specs/package-facades/spec.md` (existing)
New this round: `specs/package-facades/spec.md` (delta)

### 🔴 Fixed

(none raised)

### 🟡 Addressed

1. **Public API stability — "compat.py old path removed" scenario dropped**
   The existing spec has a `#### Scenario: compat.py old path removed` (verifying `yascheduler/compat.py` no longer exists; `Self`/`ParamSpec` only via `yascheduler.shared`). The MODIFIED rewrite of Public API stability does not include this scenario — it was replaced by "Deep import path resolves via compat shim". The design (D6) says "full rewrite of affected requirements" but does not explicitly say to drop this scenario. Since it documents a valid contract about current codebase state, its omission is a silent content loss.
   **Recommendation:** Either restore the scenario, or add a note in the spec prose that the `yascheduler.compat` → `yascheduler.shared.compat` relocation (from a previous change) remains unchanged. Flag this as a 🟡 because the dropped scenario is pre-existing and not directly related to this change, but it weakens spec coverage.

2. **"Yascheduler client query method public contract" — stale file path in body**
   The existing spec (unchanged per D6) says: "The `Yascheduler` class in `yascheduler/client.py` SHALL preserve its public query API…" After this change, the real implementation lives in `yascheduler/entrypoints/client.py`; `yascheduler/client.py` is a compat shim. The body text is now technically imprecise (the class definition moved). The design D2 explicitly says the shim does NOT re-export `Config`, so the body is misleading about which file defines the class.
   **Recommendation:** Either (a) treat this as requiring a MODIFIED update to this requirement to neutralise the file-path reference (requires unfreezing design D6's "unchanged" list), or (b) accept the imprecision since `yascheduler.client.Yascheduler` still resolves. Flag as 🟡 — not blocking, but a spec accuracy concern.

3. **Outside-layer-set exemptions — scenario enumerates outside-set modules inconsistently with prose**
   The prose lists: `config`, `data`, `di`, `client`, `aiida_plugin`, `daemon_systemd`, `daemon_sysv` (7 items). The scenario "Outside-set modules not flagged for layer direction" lists: `yascheduler.config`, `yascheduler.data`, `yascheduler.di`, `yascheduler.client`, `yascheduler.aiida_plugin`, `yascheduler.daemon_systemd`, `yascheduler.daemon_sysv` (7 items — matches). ✅ Good.

### 🔴 Outstanding

(none)

**Verdict: APPROVE WITH NOTES.** No blocking correctness or security issues. The spec delta is consistent with the frozen proposal and design across all checked dimensions. Two 🟡 items above (dropped scenario, stale file path) are spec accuracy concerns to resolve before archiving.

## specs Round 2 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: `openspec/specs/package-facades/spec.md` (existing), `design.md` (frozen), `proposal.md` (frozen), `review-log.md` `specs Round 1` findings
New this round: `specs/package-facades/spec.md` (delta, edited since Round 1; design.md declarative edit "unchanged→rewritten" for the query-method requirement)

### 🔴 Fixed

1. **"compat.py old path removed" scenario restored under Public API stability**
   Round 1 finding #1: the scenario was missing in the delta spec. The MODIFIED Public API stability requirement now includes `#### Scenario: compat.py old path removed` (lines 253–255), matching the existing spec lines 398–400 exactly (whitespace-insensitive). ✓

2. **"Yascheduler client query method public contract" stale file path fixed and requirement promoted from "unchanged" to MODIFIED**
   Round 1 finding #2: the body referenced `yascheduler/client.py` as the class location. The delta spec now rewrites this requirement (lines 257–291): the body leads with "The `Yascheduler` class SHALL preserve its public query API across the relocation from `yascheduler/client.py` to `yascheduler/entrypoints/client.py`" and keys the contract on the resolvable symbol (`from yascheduler import Yascheduler`), not the file path. All 8 original normative bullets preserved (zero-arg construction, keyword-only deps_factory, 4 query method signatures, 6-key Mapping shape, TaskStatus enum, cloud=None, ip="" when unallocated). SHALL appears on the first body line (line 259). ✓

### 🟡 Addressed

1. **design.md declarative edit: "Yascheduler client query method public contract" moved from unchanged list to rewritten paragraph**
   The edit adds a paragraph (design.md lines 210–218) explaining that this requirement is also rewritten because its body referenced the file path. This is declarative — the proposal's modified-capability entry for `package-facades` already encompassed decoupling the `Yascheduler` contract from the file path (proposal.md lines 83–88). The edit does not introduce a new decision or change scope; it accurately reflects that the same decoupling extends to this sibling requirement. Consistent with the frozen proposal. ✓

2. **Round 1 🟡 item #3 (outside-set scenario enumeration) re-verified**
   The delta spec's prose lists 7 outside-set modules (config, data, di, client, aiida_plugin, daemon_systemd, daemon_sysv) and the scenario enumerates all 7 — no inconsistency. ✓

### 🔴 Outstanding

- (none)

### Verification checklist (7 items)

1. ✅ **Header match**: delta spec line 257 `### Requirement: Yascheduler client query method public contract` matches existing spec line 402 exactly (whitespace-insensitive).
2. ✅ **Body leads with SHALL + normative bullets preserved**: line 259 "The `Yascheduler` class SHALL preserve..." — SHALL on first body line. All 8 original bullets present. Consistent with D6 (Public API decoupling).
3. ✅ **"Contract holds via each import path" scenario** (lines 317–319): consistent with D2 (compat shim preserves deep import). Does not over-claim — asserts only that identical behavior holds regardless of import path, which follows from the re-export chain.
4. ✅ **"compat.py old path removed" scenario** (lines 253–255): matches existing spec lines 398–400 exactly.
5. ✅ **design.md edit declarative**: moves requirement from "unchanged" to "rewritten" with rationale. Within scope of the proposal's modified-capability entry. No unfreezing needed.
6. ✅ **`openspec validate add-entrypoints-layer --json`**: `valid: true`, `"issues": []`.
7. ✅ **No 🔴 issues remaining** in delta spec.

**Verdict: APPROVE.** All Round 1 findings resolved. No blocking correctness, security, or integration issues. Spec delta is consistent with frozen proposal and design, and `openspec validate` passes.

## tasks Round 1 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: `proposal.md` (frozen), `design.md` (frozen), `specs/package-facades/spec.md` (frozen)
New this round: `tasks.md`

### 🔴 Outstanding

1. **Task 1.3: relative imports BREAK on file move — fundamentally wrong claim**
   Task 1.3 states: "the file already imports via `from .application import query_tasks`, `from .config import Config` ... these are absolute facade paths and remain valid; no changes needed."

   **This is categorically wrong.** These are **relative** imports (`.application`, `.config`, `.di`, `.domain`, `.shared`). When `client.py` is moved from `yascheduler/client.py` to `yascheduler/entrypoints/client.py`, they resolve as:
   - `from .application` → `yascheduler.entrypoints.application` (doesn't exist)
   - `from .config` → `yascheduler.entrypoints.config` (doesn't exist)
   - `from .di` → `yascheduler.entrypoints.di` (doesn't exist)
   - `from .domain` → `yascheduler.entrypoints.domain` (doesn't exist)
   - `from .shared` → `yascheduler.entrypoints.shared` (doesn't exist)

   **All 5 imports will raise `ModuleNotFoundError`** at runtime.

   Empirically verified with a reproduction: `from .application import query_tasks` inside `yascheduler/entrypoints/client.py` raises `ImportError: No module named 'yascheduler.entrypoints.application'`.

   **Fix:** Rewrite task 1.3 to mandate changing all 5 relative imports to absolute layer-facade paths:
   ```python
   from yascheduler.application import query_tasks
   from yascheduler.config import Config
   from yascheduler.di import CLIDeps, make_cli_deps
   from yascheduler.domain import Task, TaskStatus
   from yascheduler.shared import CONFIG_FILE, to_sync
   ```

   The task should explicitly enumerate each import and its target path, not claim they remain valid.

   *Severity: 🔴 BUG — blocks execution. If an implementer follows task 1.3 as written ("no changes needed"), the moved file will be unusable.*

### 🟡 Addressed

1. **Task 6.5: inaccurate line reference for M-AIIDA**
   Task 6.5 cites `M-AIIDA.LINKS (line ~8)`. M-AIIDA is at line 61 in the KG XML, not line 8. It has no `<LINKS>` element. The actual M-AIIDA→M-CLIENT reference to update is the CrossLink at line 861, which is already covered by task 6.7(b). Task 6.5 is redundant but does not create a coverage gap.

   **Not a blocking issue.** The line reference is stale/misplaced but the work (updating the M-AIIDA→M-CLIENT dependency) is covered by another task. If 6.5 is removed to avoid confusion, ensure 6.7(b) is still present (it is).

2. **Test file MODULE_CONTRACT DEPENDS reference stale M-CLIENT**
   Three test files reference `M-CLIENT` in their `DEPENDS` field:
   - `tests/unit/test_client_query.py` line 7: `DEPENDS: M-CLIENT, M-APPLICATION-QUERY-TASKS, M-DOMAIN-MODEL`
   - `tests/unit/test_characterization.py` line 7: `DEPENDS: M-CLIENT, M-DI`
   - `tests/integration/test_client_query_integration.py` line 7: `DEPENDS: M-CLIENT, M-CONFIG, M-DB, M-PERSISTENCE-SCHEMA`

   After the KG rename, `M-CLIENT` becomes `M-ENTRYPOINTS-CLIENT` (real implementation) + `M-CLIENT-SHIM` (compat shim). The tests import from `yascheduler.client` (the shim), so their DEPENDS should reference `M-CLIENT-SHIM`.

   Per AGENTS.md ("Test modules stay out of graph"), `grace_check.py` does not validate test-file KG references, so there is no enforcement risk. This is a documentation consistency concern only — the stale reference will not cause a CI failure.

   **Optionally add** a subtask to 5.x that updates the test file MODULE_CONTRACT DEPENDS fields to reference `M-CLIENT-SHIM` instead of `M-CLIENT`.

3. **GRACE-lite ordering: KG update comes after code**
   AGENTS.md's GRACE-lite rule states "update knowledge graph ... BEFORE code." The tasks order code creation (groups 1-5) before KG update (group 6).

   For a relocation change where the new file paths do not exist yet, this is acceptable — the KG tasks describe paths that only exist after the move. Recommend adding a brief note in the task group header acknowledging this exception to the GRACE-lite ordering rule so future reviewers understand why it is intentional.

4. **Task 1.2: FIXME comment removal location**
   Task 1.2 says "Remove the `# FIXME: move to adapters/api?` comment." This comment is at line 53 of `yascheduler/client.py` (above the `Yascheduler` class definition). Confirmed present. ✓

5. **Task 8.8 smoke check scope**
   Task 8.8 verifies that all 3 import paths resolve to the **same** class object via `is`. This is good coverage of the key design invariant (D2/D3). The design explicitly calls integration/e2e optional; their absence from group 8 is intentional. ✓

### Summary

| Check | Status | Notes |
|-------|--------|-------|
| Checklist format (`- [ ] N.X`) | ✅ | All 30 tasks conform |
| Coverage of D1–D6 | ✅ | All design decisions mapped |
| Proposal "What Changes" coverage | ✅ | All 11 bullets mapped |
| Task granularity (<2h each) | ✅ | No oversized or trivial tasks |
| Task ordering / dependencies | ✅ | Sensible dependency flow |
| Verification commands (AGENTS.md) | ✅ | All 7 commands in group 8 |
| GRACE-lite ordering (KG before code) | 🟡 | Acceptable for relocation; note intent |
| **Relative imports in task 1.3** | **🔴** | **All 5 imports break on file move** |

**Recommendation: REQUEST CHANGES** — one 🔴 blocking issue (task 1.3's claim that relative imports remain valid is fundamentally wrong; must mandate absolute imports). Four 🟡 items are non-blocking but worth addressing during implementation.

## tasks Round 2 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: `proposal.md` (frozen), `design.md` (frozen), `specs/package-facades/spec.md` (frozen), `tasks.md` (Round 1)
New this round: `tasks.md` (edited since Round 1)

### 🔴 Fixed

1. **Task 1.3: relative imports → absolute facade paths (Round 1 blocking issue #1)**
   The task now correctly enumerates all 5 relative imports with their absolute replacements:
   - `from .application import query_tasks` → `from yascheduler.application import query_tasks`
   - `from .config import Config` → `from yascheduler.config import Config`
   - `from .di import CLIDeps, make_cli_deps` → `from yascheduler.di import CLIDeps, make_cli_deps`
   - `from .domain import Task, TaskStatus` → `from yascheduler.domain import Task, TaskStatus`
   - `from .shared import CONFIG_FILE, to_sync` → `from yascheduler.shared import CONFIG_FILE, to_sync`

   The rationale header explains: "they currently resolve against `yascheduler.client.*` and would break as `yascheduler.entrypoints.client.*` after the move" — correct and explicit. ✓

   Each target is verified R2-compliant:
   - `yascheduler.application` — layer facade (`__init__.py`) ✓
   - `yascheduler.config` — root-level module (outside-layer-set; canonical import form) ✓
   - `yascheduler.di` — root-level module (outside-layer-set; canonical import form; consistent with design D3: "imports its dependencies via their layer facades") ✓
   - `yascheduler.domain` — layer facade ✓
   - `yascheduler.shared` — layer facade ✓

   **Path check:** `from yascheduler.di import CLIDeps, make_cli_deps` is the correct canonical form. `yascheduler.di` is an outside-layer-set module (not a package facade), but the design D3 and the spec's Outside-layer-set exemptions consistently treat root-level modules as importable via their top-level path. The import is from entrypoints (top layer) to an outside-set module — no layer-direction violation. ✓

   **Verdict:** Blocking issue fully resolved. No remaining claim that relative imports "just work."

### 🟡 Addressed

1. **Task 6.5: M-AIIDA.LINKS distinction clarified (Round 1 🟡 #1)**
   Task 6.5 now includes a note explicitly distinguishing the MODULE_CONTRACT `LINKS:` field in `yascheduler/aiida_plugin.py` (line ~8) from the `<CrossLink>` in the KG XML (handled in 6.7(b)). The note is clear and accurate. The `~8` line reference was verified against `yascheduler/aiida_plugin.py:8` — correct. ✓

2. **Task 5.5: test MODULE_CONTRACT DEPENDS field update (Round 1 🟡 #2)**
   New subtask 5.5 added: "Update the `MODULE_CONTRACT DEPENDS` field in the 3 affected test files if it references `M-CLIENT`" — described as cosmetic. This implements the Round 1 optional recommendation. Per AGENTS.md ("Test modules stay out of graph"), no CI enforcement risk. Not scope creep: the Round 1 review recommended it, the files are already being touched by 5.1–5.3, and it prevents stale documentation references. Acceptable. ✓

3. **GRACE-lite ordering (Round 1 🟡 #3)**
   Accepted as pragmatic for a relocation change; no tasks.md changes needed. ✓

4. **Task 6.1 line range `~41-56` vs actual M-CLIENT lines 32-47**
   Pre-existing in Round 1, not introduced by edits. The `<M-CLIENT>` element name is the unambiguous selector; the ~9-line offset is a cosmetic imprecision in a human hint. No change needed. ✓

### 🟡 Noted (pre-existing, not introduced by Round 2 edits)

5. **`yascheduler/application/query_tasks.py` LINKS field**
   Line 7: `#   LINKS: M-DOMAIN-MODEL, M-APPLICATION-UOW, M-CLIENT`. After renaming `M-CLIENT` → `M-ENTRYPOINTS-CLIENT`, this reference becomes stale. However:
   - `query_tasks.py` is not in scope for this change (no file move, no import change).
   - `grace_check.py --json` output (verified) shows only size-warnings — it does not validate source-file LINKS references against KG entries. No CI failure.
   - This is pre-existing documentation drift, not introduced by Round 2 edits. Not a 🔴 or 🟡 for this change. Flagged for awareness in the follow-up migration of remaining entrypoints residents.

### Verification Summary

| Check | Status | Detail |
|-------|--------|--------|
| Task 1.3 lists 5 replacements with correct paths | ✅ | All 5 verified against actual modules |
| No claim that relative imports "just work" | ✅ | "would break" rationale explicit |
| NEW 🔴 issues from edits | ✅ | None |
| `openspec validate add-entrypoints-layer --json` | ✅ | `valid: true`, `"issues": []` |
| Checkbox format `- [ ] N.X` | ✅ | 31/31 conform — all numbered consecutively |
| Line numbers in tasks 5.1–5.3, 6.4–6.7 | ✅ | Verified against actual files |
| Tasks coverage of frozen artifacts | ✅ | All 6 design decisions (D1–D6), all 11 proposal bullets |
| Task 5.5 scope creep | 🟡 | Acceptable — cosmetic cleanup of files already touched; recommended by Round 1 review |

### Recommendation

**APPROVE.** The Round 1 🔴 blocking issue (relative imports) is fully resolved. Task 1.3 now correctly mandates absolute facade paths with a correct rationale. No new 🔴 issues introduced. All 31 checkboxes valid. `openspec validate` passes. Edits (1.3 fix, 5.5 addition, 6.5 clarification) are consistent with the frozen proposal, design, and spec.

## artifacts Round 3 (post-implementation correction) — 2026-06-24

### 🔴 Fixed
- Removed spurious `M-AIIDA` → client graph edges in `yascheduler/aiida_plugin.py` MODULE_CONTRACT (`LINKS: M-ENTRYPOINTS-CLIENT` → `LINKS: none`), `docs/knowledge-graph.xml` (deleted `DF-AIIDA-INTEGRATION` and `CrossLink from="M-AIIDA" to="M-ENTRYPOINTS-CLIENT"`), and unfroze proposal.md/design.md/explore-brief.md/tasks.md to reflect the removal. The `aiida_plugin.py` module does not import the yascheduler client (verified via `rg "from yascheduler|import yascheduler" yascheduler/aiida_plugin.py` — zero matches); it talks to yascheduler via SSH/transport. The `LINKS: M-CLIENT` reference was always factually wrong; `add-entrypoints-layer` mechanically renamed it to `M-ENTRYPOINTS-CLIENT` (task 6.5) instead of removing it. The delta spec `specs/package-facades/spec.md` did not reference the AIIDA→client edge, so no spec unfreeze was needed. Decision-level unfreeze applied to proposal/design/tasks/explore-brief only.

### 🟡 Addressed
- None.

### 🔴 Outstanding
- None.
