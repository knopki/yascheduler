## proposal Round 1 — 2026-06-25

### 🔴 Fixed

- **Physical relocation captured**: `di.py` → `entrypoints/di.py` stated in §What Changes line 7.
- **Internal imports rewrite captured**: relative → absolute via layer facades (line 8). R2-correct per brief.
- **Consumer import rewrites (6 production files) captured**: line 10 enumerates the 6 files and their import patterns (via layer facade + sibling-relative for client.py).
- **Facade extension captured**: `entrypoints/__init__.py` re-exports `make_daemon`, `make_cli_deps`, `CLIDeps` alongside `Yascheduler` (line 9). Matches E1.
- **Test rewrites captured**: line 11 covers 8 test files, import rewrites, and `patch()` target updates.
- **All three spec edits captured**: `package-facades` (line 13), `dependency-injection` (line 14), `test-db-integration` (line 15) — each with correct scope.
- **GRACE artifacts captured**: M-DI ID retained, `<path>` updated, `CrossLink`s unchanged (line 16). Matches E7/E8.
- **ARCHITECTURE.md §2.8 update captured**: line 16. Matches E6.
- **No `pyproject.toml` changes** captured: line 17 — layers contract already covers `entrypoints`.
- **BREAKING claim verified**: no `[project.scripts]` entry references `yascheduler.di` (confirmed L48-54 of `pyproject.toml`). Correct.
- **Stale `_resolve_adapter` carve-out claim verified**: spec L436 still says `from .adapters.cloud.adapters import _resolve_adapter` with private name. Current `di.py:51` imports `resolve_adapter` (public) from `.infra` facade. The carve-out is indeed stale; proposal correctly flags it for cleanup.
- **No New Capabilities** (line 21-22): correct — this is a pure relocation.
- **Modified Capabilities list** (lines 24-27): correct — `package-facades`, `dependency-injection`, `test-db-integration`.
- **No implementation detail**: proposal stays at WHY/WHAT level; no file diffs, no before/after tables.
- **No `<context>`/`<rules>`/`<project_context>` blocks** copied from openspec instructions.
- **Impact section** (lines 29-37): accurate — no runtime behavior change, no dependencies, no config changes, GRACE updates listed, active changes verified for non-conflict (schema-migrations: modifies only `db.py`, not `di.py`).

### 🟡 Addressed

- **"8 test files" — actual count is 7**: Proposal line 11 and Impact section say "8 test files". Grepping the codebase finds exactly 7 files (6 unit + 1 e2e) referencing `yascheduler.di`. The brief's own header says "8" while its list shows 7. The proposal inherits this inconsistency. Should say "7 test files".
- **`queue-dataclass-migration` is archived, not active**: Proposal line 36 says "Active changes: `queue-dataclass-migration` and `schema-migrations` (both in-progress)". `queue-dataclass-migration` lives in `openspec/changes/archive/2026-06-25-queue-dataclass-migration/` — it is an archived (completed) change, not in-progress. The no-conflict assertion is correct regardless; the status label is slightly misleading.
- **E8: M-DI `<depends>` unchanged not explicit**: Proposal line 16 says "ID retained, `CrossLink`s unchanged" but does not separately state that `<depends>` is unchanged (the brief explicitly calls this out at line 110). The `<depends>` element is distinct from `<CrossLink>` elements in the XML; clarifying would remove ambiguity. Very minor.

### 🔴 Outstanding

(empty — no blocking issues found)

## design Round 1 — 2026-06-25

### 🔴 Fixed

- **E1–E9 commitment mapping confirmed**: All explore-brief decisions map to design D1–D7 or explicit Migration Plan steps (E4/E6/E9 listed as mechanical steps in Open Questions §, with E4 as pre-verified precondition). No commitment missed.
- **Proposal consistency verified**: Same scope (relocation only, no new capabilities), same breaking-change framing (no shim, internal API), same Modified Capabilities (`package-facades`, `dependency-injection`, `test-db-integration`). No contradictions.
- **Import cycle analysis verified**: Read `di.py` (lines 32–53, 59) — imports only from `.application`, `.domain`, `.infra`, `.config` (TYPE_CHECKING). Never imports `entrypoints/__init__` or `entrypoints/client`. `__init__.py` imports `.client` and will import `.di`; `.client` imports `.di`. Cycle claim correct.
- **D6 `resolve_adapter` public claim verified**: `def resolve_adapter` at `yascheduler/infra/cloud/adapters.py:192` (no leading underscore). Re-exported in `yascheduler/infra/cloud/__init__.py` and `yascheduler/infra/__init__.__all__`. Previously `_resolve_adapter`, renamed in `review-hardening`. Stale carve-out is indeed stale.
- **D2 relative-import claim verified**: `di.py` lines 32–53 use `from .application`, `from .domain`, `from .infra` (plus `from .config` in TYPE_CHECKING block at line 59). All confirmed relative.
- **`entrypoints/__init__.py` current state verified**: `__all__ = ["Yascheduler"]`, imports only `from .client import Yascheduler` (line 21). Matches stated "only Yascheduler today" claim.
- **No openspec template blocks copied**: design.md contains no `<context>`/`<rules>`/`<project_context>` blocks. Clean prose.
- **Design is WHY/HOW focused**: Decisions explain rationale (flat relocation, facade vs sibling-relative, no shim, M-DI ID retained, carve-out cleanup, filename kept). No line-by-line implementation detail.
- **Migration Plan ordering sensible**: `git mv` → rewrite internals → extend facade → rewrite consumers → rewrite tests → update docs → update specs → verify → run checks. Correct dependency ordering.

### 🟡 Addressed

(empty — no minor issues found)

### 🔴 Outstanding

(empty — no blocking issues found)

## specs Round 1 — 2026-06-25

### 🔴 Fixed

- **Coverage**: Three delta spec files exist (`package-facades`, `dependency-injection`, `test-db-integration`) matching the proposal's Modified Capabilities list exactly. No extra or missing capability.
- **R3 "Layer direction" (package-facades)**: `yascheduler.di` removed from outside-layer-set enumeration in the body; composition root now described as `yascheduler.entrypoints.di` subject to R3. New scenario "Composition root imports from infra — allowed" added. Matches explore-brief changes.
- **"Outside-layer-set exemptions" (package-facades)**: `yascheduler.di` removed from bullet list; `yascheduler.data` and `yascheduler.client` retained. "Scheduled for migration" paragraph replaced with "now lives at yascheduler.entrypoints.di" statement. Scenario "Composition root is layer-checked after migration" added. Scenario "Outside-set modules not flagged" updated to enumerate only `config, data, client`. Scenario "Outside-set modules still use facades" updated to use `yascheduler.entrypoints.di`.
- **"Documented private-symbol carve-outs" (package-facades)**: Rewritten to state the list is now empty. `_resolve_adapter` carve-out removed with rationale (renamed to public `resolve_adapter` in `review-hardening`, now imported via `infra` facade). Scenario "No private-symbol carve-outs remain" added; old "Private symbols stay on deep paths" rewritten with new behavior.
- **NEW "Entrypoints layer facade contents" (package-facades)**: Documents `entrypoints/__init__.py` re-exports `{Yascheduler, make_daemon, make_cli_deps, CLIDeps}` with 3 scenarios (CLI-via-facade, client sibling-relative, composition-root-via-layer-facades). Matches D3 (facade extension).
- **MODIFIED requirement header matching (package-facades)**: Headers `Layer direction (R3)` (L5 original → L3 delta), `Outside-layer-set exemptions` (L256 → L39), `Documented private-symbol carve-outs` (L430 → L82) all match whitespace-insensitive.
- **"make_daemon factory" (dependency-injection)**: Body updated with "exposed at `yascheduler.entrypoints.di`". "No module in yascheduler.di SHALL import" → `yascheduler.entrypoints.di`. "No DB-facade import" scenario's WHEN clause: `di.py is imported` → `yascheduler.entrypoints.di is imported`.
- **"make_cli_deps factory" (dependency-injection)**: Body updated with "exposed at `yascheduler.entrypoints.di`".
- **"DI factories in yascheduler.entrypoints.di" (dependency-injection)**: Renamed from `yascheduler.di`. Body updated. New scenario "Import factories via entrypoints facade" added covering `from yascheduler.entrypoints import make_daemon, make_cli_deps`.
- **"Each factory creates only needed dependencies" (dependency-injection)**: Included with full content, unchanged body. Matches review criteria.
- **MODIFIED requirement header matching (dependency-injection)**: Headers match (whitespace-insensitive) for `make_daemon factory`, `make_cli_deps factory`, `Each factory creates only needed dependencies`. The renamed header `DI factories in yascheduler.entrypoints.di` intentionally differs from original `DI factories in yascheduler.di`.
- **"Yascheduler query path integration against PostgreSQL" (test-db-integration)**: The ONE change (`yascheduler.di.make_cli_deps` → `yascheduler.entrypoints.di.make_cli_deps`) is correctly applied at line 20. All other body text and first 3 scenarios preserved verbatim.
- **Scenario format**: Every requirement in all three deltas has at least one scenario. All scenario headers use exactly 4 hashtags (`####`). No 3-hashtag or bullet-list scenarios found.
- **SHALL/MUST normative language**: Used correctly throughout all three deltas. No `should`/`may` in normative positions.
- **No template/context leakage**: Zero instances of `<context>`, `<rules>`, or `<project_context>` blocks in any of the three delta files.
- **Consistency with design.md D1, D3, D6**: D1 (flat relocation) reflected in all path references. D3 (facade extension) reflected in new "Entrypoints layer facade contents" requirement. D6 (stale carve-out removal) reflected in rewritten "Documented private-symbol carve-outs".

### 🟡 Addressed

- **test-db-integration delta: last scenario body missing**: The 4th scenario `Test asserts status against domain.TaskStatus` at line 35 has only the header line — the WHEN/THEN body from the original (lines 110–111) is absent. The delta file is 35 lines long and ends at the scenario header. The body content is unchanged from the original (no `yascheduler.di` reference), so the delta is incomplete. Add the full body before freeze:
  ```markdown
  - **WHEN** the integration test's `status` assertion is inspected
  - **THEN** it uses one of `int(result["status"])`, `result["status"] == 0`, `result["status"] == domain.TaskStatus.TO_DO`, or `result["status"].name == "TO_DO"` — never `isinstance(result["status"], yascheduler.db.TaskStatus)`
  ```

### 🔴 Outstanding

(empty — no blocking issues found)

## tasks Round 1 — 2026-06-25

### 🔴 Fixed

- **Format**: All 36 tasks use `- [ ] X.Y description` checkbox format. Grouped under `## N. Group` headings. No format violations.
- **Granularity**: Every task is a single-file/single-action edit (one import rewrite, one metadata update, one grep/command run). None exceeds 2 hours.
- **Coverage against explore-brief — §1 Physical move**: Task 1.1 (`git mv`), 1.2 (`# FILE:` header), 1.3 (internal import rewrite to absolute-via-facades), 1.4 (`START_CHANGE_SUMMARY`). All four accounted for.
- **Coverage against explore-brief — §2 Facade extension**: Tasks 2.1 (add imports), 2.2 (extend `__all__`), 2.3 (update `MODULE_CONTRACT`), 2.4 (update `MODULE_MAP`), 2.5 (update `CHANGE_SUMMARY`). Matches D3.
- **Coverage against explore-brief — §3 Production consumers (6 files)**: Tasks 3.1–3.6 cover exactly the 6 files from the brief table: `daemon_common.py`, `submit.py`, `check_status.py`, `show_nodes.py`, `manage_node.py`, `client.py`. Verified against live grep of all `from yascheduler.di import` — no other production consumers exist.
- **Coverage against explore-brief — §4 Test files (7 files)**: Tasks 4.1–4.8 cover exactly the 7 test files: `test_di.py` (2 tasks: import + patches), `test_cli_behavioral.py`, `test_cli_check_status.py`, `test_cli_manage_node.py`, `test_cli_show_nodes.py`, `test_cli_submit.py`, `test_full_cycle.py`. Verified against live grep — no other test files reference `yascheduler.di`.
- **Coverage against explore-brief — §5 Docs**: Task 5.1 updates `M-DI` `<path>` in knowledge-graph (ID retained, `<depends>` unchanged); task 5.2 updates `ARCHITECTURE.md` §2.8 heading and in-body references. Both match E7/E8/E6.
- **Coverage against explore-brief — §6 Spec updates**: Tasks 6.1 (`package-facades`), 6.2 (`dependency-injection`), 6.3 (`test-db-integration`) — all three delta specs covered.
- **Coverage against explore-brief — §7 Verification**: Tasks 7.1 (rg), 7.2 (pytest -m unit), 7.3 (lint-imports), 7.4 (ruff), 7.5 (zuban), 7.6 (grace_check), 7.7 (openspec validate), 7.8 (integration/e2e). All verification steps present.
- **Coverage against design.md Migration Plan (10 steps)**: Step 1→§1.1, step 2→§1.2–1.4, step 3→§2, step 4→§3, step 5→§4, step 6→§5.1, step 7→§5.2, step 8→§6, step 9→§7.1, step 10→§7.2–7.7. All 10 steps mapped.
- **Coverage against spec deltas**:
  - "Entrypoints layer facade contents" → §2 implements it (re-exports `Yascheduler`, `make_daemon`, `make_cli_deps`, `CLIDeps`).
  - "Composition root imports from infra — allowed" → §1.3 (absolute via facades) + §7.3 (lint-imports verification).
  - "CLI subpackage imports composition root via facade" → §3.1–3.5 implement it.
  - "Client sibling import of CLIDeps" → §3.6 implements it.
  - "Import factories via entrypoints facade" → §2 (facade extension) + §3 (consumer rewrites).
- **Ordering**: Tasks follow dependency order: git mv (§1) → extend facade (§2) → rewrite consumers that use the facade (§3) → rewrite tests (§4) → update docs (§5) → update specs (§6) → verify (§7). Within each section, sub-tasks also follow logical order (e.g., 2.1–2.2 before 2.3–2.5). No ordering violations.
- **No template leakage**: Zero instances of `<context>`, `<rules>`, or `<project_context>` blocks.
- **No code in tasks**: Only acceptable import-line examples. No code snippets.
- **Verifiability**: Every task has a concrete action (exact before→after import line, exact command to run, exact section heading to change). No vague descriptions.
- **Version consistency verified**: `di.py` current VERSION 5.3.0 / LAST_CHANGE v5.3.0 → task 1.4 correctly sets LAST_CHANGE v5.4.0 and moves v5.3.0 to PREVIOUS_CHANGE. `entrypoints/__init__.py` current VERSION 2.2.0 → task 2.3/2.5 correctly bumps to v2.3.0 and preserves v2.2.0 as PREVIOUS_CHANGE.
- **Task counts correct**: 6 production files (§3) and 7 test files (§4) match live grep. No missed consumers.

### 🟡 Addressed

- **Task 4.2 patch target counts slightly inaccurate**: The illustrative enumeration says "SSHMachineGateway (2)" → actual = 1 (line 195); "Orchestrator (4)" → actual = 5 (lines 197, 240, 265, 285, 300); total "~12" → actual = 16 patch targets. The core instruction "replace every `patch("yascheduler.di.X")` target" is unambiguous and the task still works correctly — the developer will search-and-replace globally rather than counting. Fix: correct the counts to match reality before freeze, but not blocking.

### 🔴 Outstanding

(empty — no blocking issues found)

## specs Round 2 — 2026-06-25

### 🔴 Fixed

- **ADDED "Entrypoints layer facade contents" correctly placed under `## ADDED Requirements`**: No longer mixed into MODIFIED block. Requirement is well-formed — first sentence contains SHALL, lists exactly the 4 symbols matching design.md D3 (`Yascheduler`, `make_daemon`, `make_cli_deps`, `CLIDeps`), and has 3 properly-formatted scenarios. Cross-check against main spec confirms no such requirement name exists there (grep returned zero hits), so ADDED (not MODIFIED) is correct.
- **MODIFIED Requirements block now contains ONLY the 3 genuinely modified requirements**: "Layer direction (R3)", "Outside-layer-set exemptions", "Documented private-symbol carve-outs". All other requirements (`Shared kernel config-import prohibition`, `Within-package relative imports (R1)`, `Cross-package facade imports (R2)`, `Package facade as public surface`, `Entrypoints layer facade`, `Compat shim for yascheduler.client`, `Layers contract configuration`, `Documented residual edges`, `Domain package facade contents`, `Extended facade contents`, `Broad ignore_imports tradeoff`, `Public API stability`, `Yascheduler client query method public contract`) are correctly absent from the MODIFIED block (unchanged).
- **test-db-integration delta last scenario body restored**: Round 1 🟡 item fixed — the 4th scenario `Test asserts status against domain.TaskStatus` now has the full WHEN/THEN body (lines 36–38), not just the header.
- **Consistency with design.md D3 verified**: ADDED requirement's 4 symbols exactly match the design decision: `Yascheduler` from `.client`, `make_daemon`/`make_cli_deps`/`CLIDeps` from `.di`. Scenarios match D3's two-path strategy (CLI-via-facade, client sibling-relative).

### 🟡 Addressed

- **Main spec "Entrypoints layer facade" tension**: The main spec's pre-existing requirement (line 173: "sole public surface", scenario line 207: "re-exports only Yascheduler") conflicts with the ADDED requirement's expanded symbol set in the combined delta view. This is an inherent delta-mechanism tension — the ADDED requirement is the authoritative overlay. Recommend updating "only Yascheduler" language in the main spec's "Entrypoints layer facade" requirement at archive time.
- **proposal.md Impact § still says "8 test files"**: Line 31 of `proposal.md` says "8 test files rewritten" while §What Changes line 11 correctly says "7 files". This was a Round 1 🟡 item that was partially fixed but missed in the Impact section. Not in scope for this round.

### 🔴 Outstanding

(empty — no blocking issues found)
