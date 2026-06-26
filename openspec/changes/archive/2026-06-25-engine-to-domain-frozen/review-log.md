# Review Log — engine-to-domain-frozen (P2)

## proposal Round 1 — 2026-06-25

### 🔴 Fixed

1. **Naming inconsistency: `_parse_engine_section` vs `parse_engine_section`**

   **Location**: proposal.md line 35 vs lines 39–40  
   **Problem**: The proposal defines the free function as `_parse_engine_section` (private, with underscore, line 35) but the migration path in lines 39–40 tells consumers to migrate to `parse_engine_section(...)` (public, no underscore). If the function is truly private (underscore), tests migrating from `Engine.from_config_parser_section` would need to import a private API, which is bad practice and contradictory. If it is public (no underscore), line 35 should drop the underscore. This inconsistency is inherited from the brief (brief.md line 49 `_parse_engine_section` vs line 167 `parse_engine_section`); the proposal propagates it instead of resolving it.

   **Fix**: Choose one name and use it consistently throughout the proposal.

   - **Option A** (recommended — consumers need it): rename to `parse_engine_section` (public) everywhere — line 35, all references in the proposal, and the delta spec. The function has a public consumer (test code migrating from `Engine.from_config_parser_section`), so a public name is correct.
   - **Option B**: keep `_parse_engine_section` (private), but then the test migration path on line 39 must refer explicitly to the public `parse_engines` function (which wraps `_parse_engine_section`) and state that direct section-level parsing in tests should use a test helper, not import the private function. Update line 39 accordingly.

   Either choice resolves the ambiguity. The brief will need a corresponding fix since it is the frozen baseline; the proposal must not freeze the inconsistency.

### 🟡 Addressed

- **EngineRepository target surface**: The proposal (lines 30–31) correctly lists the preserved method set (`get`, `__getitem__`, `__contains__`, `values`, `filter`, `filter_platforms`, `get_platform_packages`). Matches the brief (lines 77–89). ✓

- **Engine field set**: Proposal does not reproduce the field table inline (which is fine — the brief has it, and the delta spec will carry it). The capabilities section (lines 77–78) lists the extended field set. ✓

- **Consumer call sites**: Proposal Impact section (lines 103–109) covers all consumers from the brief's table (lines 96–108). ✓

- **Config facade delta**: Proposal lines 47–49 and 84–86 match the brief's lines 110–123. ✓

- **Test migration coverage**: Proposal lines 57–62 and 126–131 cover the 10 mutation-to-constructor migrations, 15 MagicMock spec audits, 2 PEngineRepository→EngineRepository migrations, and test config parser migration. ✓

- **BREAKING markers**: All three BREAKING items (direct import path, `from_config_parser_section` removal, `engines_dir`/`__hash__`/`UserDict` removal) are correctly marked. ✓

- **Public API unaffected**: The explicit statement at lines 117–120 is correct and matches the plan §5 risk register. ✓

- **No P3/P4 scope leakage**: Cloud configs, `Config` aggregate, cloud parser registry, settings DTOs are all correctly left out. `warn_unknown_fields` correctly stays in `config/utils.py`. ✓

- **Capability mapping**: All five capability names (`domain-engine-types` new, `domain-entities`, `platform-adapters`, `package-facades`, `testing-unit` modified) match `openspec/specs/` directory entries. The proposed changes are directionally correct relative to what each spec currently says. ✓

- **Decision-level alignment**: All eight relevant decisions from `docs/config-layer-split-plan.md` §3 (Engine frozen, `__hash__` deleted, frozen dataclass + Mapping, no `engines_dir`, delete PEngine Protocols, parser separation, single parser module, attrs→dataclass) are faithfully reflected. No contradiction found. ✓

### 🔴 Outstanding

No outstanding serious issues. The naming inconsistency above is the only finding that must be fixed before freezing.

**Recommendation**: REQUEST CHANGES — fix the `_parse_engine_section`/`parse_engine_section` naming inconsistency before freezing.

## proposal Round 2 — 2026-06-25

### 🔴 Fixed

1. **Naming inconsistency — Option A applied**

   `_parse_engine_section` → `parse_engine_section` and `_engine_valid_fields` → `engine_valid_fields` throughout proposal.md. Grep confirms zero instances of the underscore-prefixed forms remain in the proposal. All three parser functions are now consistently public: `parse_engine_section`, `parse_engines`, `engine_valid_fields`. ✓

### 🟡 Addressed

- All Round 1 🟡 items from the review log remain clean — no regression introduced by the rename.

### 🔴 Outstanding

None. No new issues introduced by the fix. Full re-scan of the proposal against the explore-brief found no contradictions, omissions, or errors.

**Brief declarative fix needed**: The frozen `explore-brief.md` still carries the old naming on two lines:
  - Line 49: `entrypoints/config_parser.py::_parse_engine_section` → should be `parse_engine_section`
  - Line 51: `entrypoints/config_parser.py::_engine_valid_fields` → should be `engine_valid_fields`

  This is a declarative fix (name correction only — no decision-level change). Per workflow rules, the brief can be corrected without re-opening decisions. Recommend applying these two edits before freezing the proposal.

No outstanding serious issues. The proposal is ready to freeze (after the brief's declarative fix).

**Recommendation**: APPROVE WITH NOTES — fix the two stale underscores in `explore-brief.md` lines 49 and 51, then freeze.

## design Round 1 — 2026-06-25

### 🔴 Fixed

1. **Missing merge plan for existing `domain/model.py::Engine`**

   **Location**: design.md D1, Goals, Migration step 1
   **Problem**: The design assumes `domain/engine.py::Engine` is created fresh with no prior domain Engine. But `yascheduler/domain/model.py:156` already defines a `@dataclass(frozen=True) Engine` with 7 fields (`name`, `spawn`, `input_files`, `output_files`, `platforms`, `check_cmd`, `check_pname`, plus `validate_inputs`). This Engine is re-exported by `domain/__init__.py:130` and listed in `__all__` (line 70). The config Engine (from `config/engine.py:116`) has 11 fields (adds `deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval`). The design must explain the reconciliation strategy — whether:
   - (a) `domain/model.py::Engine` is extended with the 4 missing fields and the config Engine is deleted (no new `domain/engine.py` for Engine — Deploy* and EngineRepository still need a home), or
   - (b) A consolidated `domain/engine.py::Engine` replaces both, and `Engine` is removed from `domain/model.py` with `domain/__init__.py` imports updated accordingly.

   **Fix**: Add a paragraph in D1 or a new decision that explicitly describes the merge strategy. At minimum acknowledge the existing domain Engine and state which option is chosen and why.

2. **`make_default_field` deletion claim is factually wrong**

   **Location**: design.md D2 lines 114–117
   **Problem**: D2 states `make_default_field` is "deleted from `config/utils.py` since its only remaining consumer after P2 is the cloud-config parser (P3), which will re-implement the equivalent inline." This is incorrect. After P2, `config/remote.py` (line 32 imports it, lines 39–42 use it) and `config/db.py` (line 27 imports it, lines 34–38 use it) still consume `make_default_field`. Neither module moves until P4. Deleting it from `config/utils.py` in P2 would immediately break those modules. Only `config/engine.py`'s usage (the engine-specific consumer) is removed in P2.

   **Fix**: Either (a) keep `make_default_field` in `config/utils.py` in P2 (add a TODO that it stays for `remote.py` and `db.py` until P4), or (b) adjust the claim to state `make_default_field` is kept in `config/utils.py` in P2 and removed in P4. Do not delete it in P2.

### 🟡 Addressed

- **Naming consistency**: `parse_engine_section`, `parse_engines`, `engine_valid_fields` — all three are consistently public with no leading underscore. Round 1/2 fix applied correctly. ✓
- **EngineRepository target surface** (design.md D3): Code snippet matches brief lines 77–92 exactly. Methods preserved: `get`, `__getitem__`, `__contains__`, `values`, `filter`, `filter_platforms`, `get_platform_packages`. No `engines_dir`, no `__hash__`, no `UserDict`. Design adds inline `return self.data.get(name)` implementations (soft detail). ✓
- **Engine field set** (design.md Goals and D1): All 11 fields preserved. `validate_inputs` correctly stays on Engine (pure domain logic, not INI parsing). ✓
- **Consumer call sites**: All 11 production consumers (from brief lines 96–108) are covered in migration steps 4–6. ✓
- **Config facade delta**: `yascheduler.config` stops re-exporting Engine/EngineRepository/Deploy* correctly. `warn_unknown_fields` stays in `config/utils.py` (correct — P3 cloud parsing uses it). ✓
- **Non-Goals**: All 6 items correctly exclude P3 (ConfigCloud move), P4 (settings/aggregate move), P5 (attrs removal), field set changes, `validate_inputs` changes, and CloudConfig Protocol introduction. No P2 commitment is excluded. ✓
- **Risk coverage**: All 6 risks have explicit mitigations. Public API stability risk is covered implicitly by "INI format and Config public surface unchanged" statement. ✓
- **Migration plan**: 9 steps mirror tasks.md ordering and cover all affected files from proposal Impact section. No P3/P4 work leaks in. Rollback is clean. ✓
- **Decision-level alignment**: All locked decisions from plan §3 (Engine frozen, delete `__hash__`, frozen dataclass + Mapping, no `engines_dir`, delete PEngine Protocols, parser separation, single parser module, attrs→dataclass) are faithfully reflected. No contradiction with frozen proposal.md. ✓
- **Rejected alternatives coverage**: All 8 alternatives from brief are addressed (alt #1 via D1, #2 via D4, #3 via D3, #4 via D5, #5 via D6, #6 via D2, #7 via D1, #8 implicitly via "single-repo single-PR" in migration plan). ✓
- **Cross-module data flows**: Submit path, SSH setup path, and cloud config build path all described (D3, D7). ✓
- **Test migration**: Mutation-to-constructor migration (~10 files, matches grep), MagicMock spec audits (grep confirms 24 sites, brief says ~15 — inaccuracy inherited from brief), 2 PEngineRepository→EngineRepository sites, and config parser test migration all listed. ✓
- **No P3/P4 scope leakage**: Cloud configs, Config aggregate, cloud parser registry, settings DTOs all correctly excluded. ✓

### 🔴 Outstanding

Two blocking issues remain (see 🔴 Fixed above):
1. Missing merge plan for existing `domain/model.py::Engine` — must be resolved before freezing.
2. `make_default_field` deletion claim is factually wrong — must be corrected before freezing.

**Recommendation**: REQUEST CHANGES — fix both 🔴 issues before freezing.

## design Round 2 — 2026-06-25

### 🔴 Fixed

1. **D1 merge plan — resolved**

   D1 is completely rewritten. It now: (a) explicitly acknowledges `domain.model.Engine` exists with 7 fields + `validate_inputs` (lines 86–90), (b) identifies `config.Engine` as a separate 11-field attrs class (lines 92–95), (c) states the merge strategy: extend `domain.model.Engine` with 4 fields → relocate to `domain/engine.py` → re-export from `domain.model` and `yascheduler.domain` for backward compat (lines 97–104), (d) notes 4 added fields have defaults so existing call sites keep working (lines 106–108). ✓

2. **D2 `make_default_field` correction — resolved**

   D2 now explicitly says `make_default_field` is **not deleted** in P2 because `config/remote.py`, `config/db.py`, and `config/cloud.py` still consume it (lines 136–142). Stays in `config/utils.py` until P3/P4 remove the last consumers. `warn_unknown_fields` likewise stays. ✓

### 🟡 Addressed

- **Consistency with proposal.md**: The merge strategy (extend → relocate → re-export) matches proposal.md lines 26–35. `make_default_field` handling matches proposal.md lines 53–54. ✓
- **Alternative #9 reflected**: explore-brief §"Rejected alternatives" alt #9 (keep two classes separate) is listed in D1's rejected alternatives (lines 118–121). ✓
- **D3–D7 consistent with merge**: D3 (EngineRepository surface) places new frozen class alongside merged Engine in `domain/engine.py`. D4 (PEngine deletion) is made possible by merge — infra can now import Engine from domain. D5 (__hash__ removal) and D6 (engines_dir removal) are unrelated to merge but don't contradict. D7 (composition root) correctly references merged types. ✓
- **Migration plan step 1 technically sound**: Extend in-place → relocate → re-export works. `from yascheduler.domain.model import Engine` continues to resolve because `domain/model.py` re-exports from `domain/engine.py`. ✓
- **Goals/Non-Goals accurate**: Goals list all 7 P2 outcomes correctly. Non-Goals correctly exclude P3/P4/P5 scope and preserve field set constraints. Minor wording issue noted below. ✓
- **Rejected alternatives coverage**: All 9 alternatives from brief are referenced across D1–D7 (brief alts #1/#7/#9 in D1, #6 in D2, #3 in D3, #2 in D4, #4 in D5, #5 in D6, #8 in migration plan). ✓

### 🔴 Outstanding

No blocking issues remain. The two Round 1 blocking issues are fully resolved.

**Two minor items flagged for awareness (not blocking):**

1. **Circular import risk — `Engine.validate_inputs` ↔ `TaskContext` not addressed in design**

   `Engine.validate_inputs(ctx: TaskContext)` currently lives on `domain.model.Engine` and imports `TaskContext` from the same module. After P2, `Engine` moves to `domain/engine.py`, but `Engine.validate_inputs(self, ctx: TaskContext)` still needs the `TaskContext` type, which stays in `domain/model.py`. If `domain/engine.py` imports `TaskContext` at module level and `domain/model.py` imports `Engine` from `.engine` (for re-export), a circular import results.

   **Mitigation exists**: `from __future__ import annotations` is already present in `domain/model.py` (line 27). `domain/engine.py` should import `TaskContext` under `TYPE_CHECKING` only — the annotation is never evaluated at runtime. The design does not mention this pattern; it should be called out in tasks.md so the implementer is aware. Defer to tasks (not a design-level blocker — the solution is well-known and standard).

2. **Non-Goals wording ambiguity: "no additions" vs Goals adding 4 fields**

   Non-Goals line 75: `Changing Engine field set (no additions, no removals — only form and location).` This contradicts the Goals (line 43) and D1 (line 97), which state the existing `domain.model.Engine` gains 4 fields from `config.Engine`. The intent is that the *resulting* field set matches the union of both Engines (i.e., no *net new* fields beyond what `config.Engine` already has), but the wording "no additions" is ambiguous. Recommend rephrasing to: `No field additions beyond the 4 fields already present in config.Engine (deployable, platform_packages, check_cmd_code, sleep_interval).`

Neither item is blocking. Both are minor clarifications for the implementer.

**Recommendation**: APPROVE WITH NOTES — address the two minor items (circular import mitigation in tasks, Non-Goals rephrasing) before or during implementation. The design is ready to freeze.

## specs Round 1 — 2026-06-25

### 🔴 Fixed

1. **MODIFIED target `Config facade contents` does not exist as a requirement heading in the current spec**

   **Location**: `package-facades/spec.md` (delta), `openspec/specs/package-facades/spec.md` line 444 (existing)

   **Problem**: The delta's MODIFIED section declares `### Requirement: Config facade contents`. The current spec has no `### Requirement: Config facade contents` heading. The config facade re-export rules live as a sub-bullet under `### Requirement: Extended facade contents (lazy publication driven by consumers)` (line 473: `- **yascheduler/config/__init__.py** SHALL re-export: ... AzureImageReference`).

   Per review rules, a MODIFIED requirement must match an existing `### Requirement: <name>` heading. This delta targets a heading that doesn't exist. The config facade re-exports *are* being changed (Engine types removed), but the structural delta is wrong.

   **Root cause**: The config facade content was promoted from a sub-bullet to a standalone requirement. It should either (a) be in the `## ADDED Requirements` section (new top-level requirement) with `Extended facade contents` separately MODIFIED to remove the config sub-bullet, or (b) `Extended facade contents` itself should be the MODIFIED target, with its config sub-bullet updated in-place.

   **Fix**: Choose one of:
   - (Recommended) Move `Config facade contents` to `## ADDED Requirements` (new standalone requirement), and add `Extended facade contents` to `## MODIFIED Requirements` to remove the config sub-bullet and its related scenario (`Config facade exposes AzureImageReference` — which moves to the new requirement).
   - (Minimal) Drop `## MODIFIED Requirements` > `Config facade contents` from the delta; add the config facade SHALL NOT constraints as an update to the config sub-bullet within `Extended facade contents` in a new MODIFIED block for that requirement.

2. **`Extended facade contents` not updated — config sub-bullet becomes stale**

   **Location**: `openspec/specs/package-facades/spec.md` line 473–474 (existing, not in delta)

   **Problem**: Related to finding #1. The existing `Extended facade contents` requirement claims its enumerated re-exports are "the complete set required to make every pre-existing cross-package import R2-compliant" (line 476). After P2, this claim is stale: the config facade must also SHALL NOT re-export Engine types — a constraint the `Extended facade contents` requirement doesn't mention. Since the delta doesn't MODIFY `Extended facade contents`, this requirement would remain in the spec alongside the new `Config facade contents` requirement without acknowledging the SHALL NOT constraint.

   The two requirements are compatible (not contradictory), but the "complete set" claim in `Extended facade contents` is no longer accurate.

   **Fix**: Once finding #1 is resolved (either ADDED + MODIFY `Extended facade contents`, or MODIFY `Extended facade contents` directly), ensure `Extended facade contents` is updated to either (a) remove the config sub-bullet entirely with a note delegating to `Config facade contents`, or (b) update the sub-bullet to include the SHALL NOT constraints.

### 🟡 Addressed

- **`Domain package facade contents` "Events regression check" scenario dropped without reason**

  **Location**: `domain-entities/spec.md` (delta MODIFIED), existing spec lines 440–443

  **Observation**: The existing `Domain package facade contents` has a scenario `Events regression check` (WHEN: import events, THEN: all resolve). The delta's MODIFIED block drops this scenario without comment. However, the intent is subsumed by the existing `Domain facade exposes all required categories` scenario (which imports `TaskCreated`, an event) and the new `Domain facade exposes Engine types` scenario. No correctness issue — the event symbols are tested by the first scenario. The removal is semantically safe but missing a documented reason.

  No action needed — the scenario's coverage is preserved by the other scenarios.

- **Consistency across all 5 deltas**: Engine field set (11 fields, defaults on 4), EngineRepository surface (7 methods, no UserDict, no `__hash__`, no `engines_dir`), parser functions, facade deltas, and test migration all agree across specs. No contradictions found.

- **Proposal alignment**: All delta requirements reflect the proposal's What Changes and design D1–D7 faithfully. No requirement contradicts a frozen design decision.

- **Scope discipline**: No P3/P4/P5 leakage detected. No references to ConfigCloud*, Config aggregate move, attrs removal, or settings DTOs.

- **Scenario technical accuracy**: All spot-checked scenarios are functionally correct. Minor imprecision in `EngineRepository is unhashable` rationale (says "__hash__ is not defined" but frozen dataclass does generate `__hash__` — it fails at runtime because the `data: Mapping` field is a `dict` which is unhashable) is functionally correct and non-blocking.

### 🔴 Outstanding

Two blocking issues remain:

1. **`Config facade contents` MODIFIED targets a heading that doesn't exist** — see 🔴 Fixed #1 above. This must be fixed before the specs can freeze.

2. **`Extended facade contents` not updated** — see 🔴 Fixed #2 above. The config sub-bullet and its "complete set" claim become stale with the introduction of the new `Config facade contents` requirement (once finding #1 is resolved).

   Both findings stem from the same structural delta choice. Fix finding #1 and finding #2 resolves together.

**Recommendation**: REQUEST CHANGES — fix the two structural delta issues (Config facade contents MODIFIED target + Extended facade contents staleness) before freezing.

## specs Round 2 — 2026-06-25

### 🔴 Fixed

1. **MODIFIED target `Config facade contents` eliminated — Round 1 issue resolved**

   The delta no longer contains a `### Requirement: Config facade contents` heading. The config facade SHALL NOT constraints are inlined into `Extended facade contents (lazy publication driven by consumers)` as a new paragraph under the config sub-bullet. Both MODIFIED headings (`Domain package facade contents` and `Extended facade contents (lazy publication driven by consumers)`) exist in the current spec (lines 422 and 444). Whitespace-insensitive match confirmed. ✓

2. **`Extended facade contents` updated — SHALL NOT clause + new scenarios + closing paragraph**

   The MODIFIED block now contains:
   - Config sub-bullet preserved verbatim: `yascheduler/config/__init__.py SHALL re-export: AzureImageReference` (line 55–56, matches existing line 473–474).
   - NEW paragraph: `yascheduler/config/__init__.py SHALL NOT re-export Engine, EngineRepository, Deploy, ...` (lines 58–60).
   - NEW clause: physical files `yascheduler/config/engine.py` and `yascheduler/config/engine_repository.py` SHALL NOT exist (lines 61–65).
   - Updated closing paragraph: adds `(Engine types are now R2-compliant via yascheduler.domain, not yascheduler.config.)` after the existing "complete set" sentence (lines 67–70).
   - 2 new scenarios: `Config facade no longer exposes Engine types` (lines 96–98) and `Config engine modules removed` (lines 100–102). ✓

### 🟡 Addressed (from Round 1)

- **Round 1 🟡 "Events regression check" dropped**: Still absent from the delta's MODIFIED `Domain package facade contents`. Intentionally preserved — coverage subsumed by `Domain facade exposes all required categories` scenario (imports `TaskCreated`). ✓
- **Field set, method surface, parser separation, facade deltas, test migration**: All consistent across 5 deltas and aligned with proposal + design. Cross-checked against all D1–D7 decisions. ✓
- **Scope discipline**: No P3/P4/P5 leakage. No references to ConfigCloud*, Config aggregate move, attrs removal, or settings DTOs. ✓
- **Scenario technical accuracy**: All spot-checked scenarios functional. No regression from Round 1. ✓

### 🟡 New minor observations (not blocking)

1. **Missing scenario for `empty input_files` rejection in testing-unit spec**

   **Location**: `testing-unit/spec.md` lines 10–12 (prose requires `empty input_files` rejection), no corresponding scenario in the delta or in `domain-engine-types/spec.md`.
   **Detail**: The MODIFIED testing-unit prose lists `empty input_files` as a parser-side validation. The `_check_at_least_one_elem` validator exists in the design (D2). But neither the testing-unit delta nor the domain-engine-types spec has a `#### Scenario` for this behavior. The requirement is stated in SHALL prose (enforceable), but the scenario gap means a test author implementing strictly from scenarios would miss it.
   **Fix**: Add a scenario to either `testing-unit/spec.md` or `domain-engine-types/spec.md`:
   ```
   #### Scenario: parse_engine_section rejects empty input_files
   - **WHEN** `parse_engine_section` is called with `input_files=""` or `input_files=()`
   - **THEN** `ValueError` is raised by the parser-side `_check_at_least_one_elem` validator
   ```
   **Severity**: Non-blocking. The prose requirement is unambiguous, and a diligent implementer will cover it. Fix if this spec set goes through another round; otherwise defer to implementation tasks.

2. **`Domain package facade contents` "Events regression check" scenario removal undocumented**

   The MODIFIED delta silently drops this existing scenario. The Round 1 review accepted it as "coverage preserved by other scenarios." The scenario text saying "when a consumer imports the events previously available via yascheduler.domain.__init__" tests a non-regression guarantee that isn't explicitly tested by the preserved scenarios (which only test that `TaskCreated` resolves — not that all 7 event symbols resolve). The coverage is factually preserved (`TaskCreated` is one of the 7; if it resolves, the event module is importable), but the intent signal is lost.
   **Severity**: Non-blocking. The requirement prose still lists all 7 event symbols under the **Events** bullet.

### 🔴 Outstanding

No blocking issues remain. The two Round 1 blocking issues (Config facade contents MODIFIED target + Extended facade contents staleness) are fully resolved. The delta structural integrity, heading matching, SHALL/MUST language, scenario hashtag convention (exactly `####`), and testability are clean across all 5 specs.

**Recommendation**: APPROVE WITH NOTES — address the missing `empty input_files` scenario as a task-level item if desired. The specs are ready to freeze.

## tasks Round 2 — 2026-06-25

### 🔴 Fixed

1. **Task 4.1 — `SetupNodeCallable.__call__` references `PEngineRepository`**

   Line 32 now says: "replace with `EngineRepository` imported under `TYPE_CHECKING` from `yascheduler.domain` (add a `TYPE_CHECKING` import block if not present)." ✓

2. **Tasks 4.2/4.3 — `PEngineRepository` imports + type hints in linux.py/windows.py**

   Lines 33–34 now say: "switch `from .protocol import ... PEngineRepository ...` → `from yascheduler.domain import EngineRepository`" and "Change all `engines: PEngineRepository` type hints (linux.py:250,307,327) to `engines: EngineRepository`." ✓

3. **Task 8.3 — rewritten as multi-bullet**

   Lines 71–76 now contain 5 sub-bullets covering: constructor call migration (line 72), `test_engine_empty_input_files` parser-side migration (line 73), `engines_dir` kwarg removal (line 74), `NotImplementedError` → `TypeError` assertion (line 75), and `from_config_parser_section`→`parse_engine_section` migration (line 76). ✓

4. **Tasks 7.6/7.7 — PEngine import removal + `MagicMock(spec=PEngine)` → `Engine`/`MagicMock(spec=Engine)`**

   Lines 62–63 now say: "remove `PEngine` import (line 42); replace `MagicMock(spec=PEngine)` (line 233) with `Engine(name="test_engine", spawn=..., ...)` or `MagicMock(spec=Engine)`; replace `engine.name = "test_engine"` (line 234) with full `Engine(...)` constructor." ✓

### 🟡 Addressed

5. **New task 4.4 — platform/__init__.py re-exports removed (non-blocking gap)**

   Line 35: "remove `PEngine` and `PEngineRepository` from the `.protocol` re-export block (lines 75-76, 149-150 reference these names)." ✓

6. **Task 9.8 grep scope expanded to `tests/` (non-blocking gap)**

   Line 89: "Grep `PEngine\|PEngineRepository` in `yascheduler/` AND `tests/` — zero matches." ✓

7. **Task 8.3 documents `NotImplementedError` → `TypeError` assertion change (non-blocking gap)**

   Line 75: "Update the `pytest.raises(...)` assertion from `NotImplementedError` to `TypeError`." ✓

8. **Task 8.3 documents `engines_dir` kwarg removal (non-blocking gap)**

   Line 74: "drop the `engines_dir` kwarg (does not exist on the domain `EngineRepository`)." ✓

9. **Tasks 1.6/1.7 mention MODULE_MAP/CHANGE_SUMMARY updates (non-blocking gap)**

   Lines 8–9: both tasks now include "Update MODULE_MAP" and "CHANGE_SUMMARY" instructions. ✓

### 🟡 Additional verification

- **Task numbering**: Section 4 has 6 items (4.1–4.6), section 7 has 9 items (7.1–7.9), section 8 has 5 items (8.1–8.5). No numbering drift. No broken references between tasks. Ordering matches dependency structure: 1+2 (new code) → 3+4 (delete old code) → 5 (app imports) → 6 (graph) → 7+8 (test migration) → 9 (verification). ✓
- **Line number references**: All external file line references (task 4.1 line 215, 4.2 lines 250/307/327, 4.3 lines 286/329, 4.4 lines 75-76/149-150, 4.5 line 828, 4.6 line 52, 5.x lines, 7.x lines, 8.x lines) point to pre-existing code, not tasks.md — no shift risk. ✓
- **Spec coverage**: Cross-checked every scenario across all 5 delta specs against tasks. Every scenario has a corresponding task or set of tasks. No requirement lost coverage. ✓
- **Tasks 7.6/8.1 interaction clean**: 7.6 removes `PEngine` from the unit test's multi-line import block (`yascheduler.infra.ssh.platform.protocol`); 8.1 later removes `PEngineRepository` from the same block and adds `EngineRepository` from `yascheduler.domain`. Both names in the same import block, handled by separate tasks — correct. ✓
- **Integration test (task 7.7)**: Only imports `PEngine` (line 38), not `PEngineRepository`. No overlap with task 8.1. ✓

### 🔴 Outstanding

No outstanding serious issues. The tasks are ready to freeze.

**Recommendation**: APPROVE.
