# Review Log — collapse-provider-selection

## proposal Round 1 — 2026-06-24

### 🔴 Outstanding
- **O1** — Graph-impact entry mislabels the M-block for `export-ProviderSelection`. proposal.md:45 read `remove export-ProviderSelection (M-DOMAIN-MODEL)` but the annotation is in **M-DOMAIN** (knowledge-graph.xml:199, the `domain/__init__.py` re-export block closing at :203), not M-DOMAIN-MODEL. `type-ProviderSelection` at knowledge-graph.xml:246 IS in M-DOMAIN-MODEL. Fix: split the entry by correct M-block.
- **O2** — `cloud-provisioner` capability entry under-scoped. Only called out removing the "ProviderSelection is primitive-only" scenario (spec :83–85) but missed the requirement paragraph at spec :54–58 (`select_provider(...) -> ProviderSelection | None` + wrapping into `ProviderSelection(name, username)`) and the "Higher priority wins" scenario at spec :69 (`returns a ProviderSelection with name=...`). Both reference a type that no longer exists; the capability delta must cover them.

### 🟡 Addressed (non-blocking, folded in during fix pass)
- **M1** — `test_persistence_adapter.py` assertion `n.username == "deployer"` → `n.username == "root"` not acknowledged in Impact. Folded in.
- **M2** — `postgres-repositories` scenario wording "given cloud and username" → "given cloud, username defaults to 'root'". Folded into Capabilities.
- **M3** — `test_domain_model.py` contains `TestProviderSelection` class that must be DELETED, not "replaced with strings". Made explicit in Impact.
- **M4** — `use-cases` spec has `clouds.allocate(selection.name)` at multiple sites, not just the `add_tmp` call. Enumerated in Capabilities.
- **M5** — `domain-ports` prose lines 146–149 ("gets a ProviderSelection... calls allocate(selection.name)") not mentioned. Folded into Capabilities.

### 🔴 Fixed
(none — first-pass review)

---

## proposal Round 2 — 2026-06-24

### 🔴 Fixed
- **O1** — proposal.md:47 now splits `export-ProviderSelection` → M-DOMAIN and `type-ProviderSelection` → M-DOMAIN-MODEL with explicit rationale.
- **O2** — proposal.md:26 now explicitly rewrites the requirement paragraph (spec :54–58), the "Higher priority wins" scenario assertion (spec :69), and removes the "ProviderSelection is primitive-only" scenario (spec :83–85).

### 🟡 Addressed
- **M1–M5** — all folded in as documented in Round 1.

### 🟡 Outstanding (non-blocking, fixed before freeze)
- Count qualifier "two call sites" in the use-cases entry was factually wrong — the use-cases spec has three `clouds.allocate(selection.name)` occurrences (requirement body :41, "No free machine" scenario :52, "Cloud allocation failure cleans up tmp-node" scenario :55). Fixed: changed to "three call sites: requirement body + two scenarios". Non-blocking because the transformation rule `selection.name → selection` is grep-complete and unambiguous.

### 🔴 Outstanding
(none — batch frozen)

---

## design Round 1 — 2026-06-24

### 🔴 Outstanding
- **D5 line citations wrong** — `design.md:76-77` cited `knowledge-graph.xml:199` for `export-ProviderSelection` (actually at line 228, in M-DOMAIN) and `:246` for `type-ProviderSelection` (actually at line 275, in M-DOMAIN-MODEL). The M-ID locations were correct; only the line numbers were wrong. An implementer trusting the line numbers would land in the wrong module's annotation block.

### 🟡 Addressed (verified against code)
- D1 2/3-paths reasoning — verified: `allocate_task.py:320` is the only in-memory path; `deallocate_nodes.py:81` and `allocate_task.py:378-380` originate from DB strings.
- D2 `DEFAULT 'root'` — verified at `schema.sql:4` and `schema.sql:18-19`.
- D3 select_provider body — verified against `manager.py:110-135`; `config = self.configs[adapter.name]` at line 134 is the lookup being removed.
- D4 atomic A+B — verified: `add_tmp(selected_name, selection.username)` at `allocate_task.py:256` is the sole consumer of `selection.username`.
- Context FIXME + re-derivation references — `model.py:433`, `model.py:436`, `manager.py:367` all accurate.
- Risks — tmp-row username shift verified at `test_persistence_adapter.py:358,365` (unique `add_tmp("aws", "deployer")` + `n.username == "deployer"`; adjacent line 342 belongs to a different test).
- Non-Goals (all four required exclusions present): option C, re-resolve elimination, real `Node.username` flow, schema/migration.
- Migration Plan — no data migration; rollback is code-revert only.
- No freeze violations — design introduces no new Modified Capability, no new Impact area. D3 is decision-level new but previewed in proposal.md:12.
- All four required Risks present: future metadata, breaking port type, tmp-row shift, loss of named field.

### 🟡 Minor (non-blocking, not fixed)
- Context section mildly restates proposal WHY — within rule #5 tolerance ("a brief Context" allowed). The technical landscape (port convention, exact destructure line, FIXME refs) is genuinely needed to ground D1-D3.

### 🔴 Fixed
(none — first-pass review)

---

## design Round 2 — 2026-06-24

### 🔴 Fixed
- **D5 line citations** — dropped `:199` and `:246` entirely; kept M-ID + annotation tag references (`export-ProviderSelection` in M-DOMAIN, `type-ProviderSelection` in M-DOMAIN-MODEL). Verified M-ID locations: `export-ProviderSelection` at line 213 inside M-DOMAIN (173-217), `type-ProviderSelection` at line 260 inside M-DOMAIN-MODEL (244-262).

### 🔴 Outstanding
(none — batch frozen)

---

## specs Round 1 — 2026-06-24

### 🔴 Outstanding
- **Spurious REMOVED `ProviderSelection value object` in domain-ports** — `specs/domain-ports/spec.md:81-87` targeted `### Requirement: ProviderSelection value object`, but the original spec has no such standalone requirement. `ProviderSelection` is a paragraph embedded inside `### Requirement: CloudProvisioner port` (original L163-166). OpenSpec apply keys REMOVED matches only on `### Requirement:` headings; for a non-existent target it throws at archive time. The removal is already achieved by the MODIFIED `CloudProvisioner port` requirement (which omits the defining paragraph). `openspec validate` does not catch this; it surfaces only at `openspec archive`.
- **Spurious REMOVED `ProviderSelection is primitive-only` in cloud-provisioner** — `specs/cloud-provisioner/spec.md:40-46` targeted `### Requirement: ProviderSelection is primitive-only`, but the original has this as a `#### Scenario:` inside `### Requirement: Provider selection by priority and capacity` (original L83-85), not a standalone requirement. Same archive-break risk. The scenario is already dropped by the MODIFIED requirement (which omits it). Diverges from frozen proposal which says "remove the 'ProviderSelection is primitive-only' **scenario**" (scenario-level edit), not a requirement removal.

### 🟡 Addressed (verified correct)
- All 5 MODIFIED requirements copy the ENTIRE original block — no lost scenarios, no lost method lists.
- All scenario headers use exactly 4 hashtags (`####`).
- Every requirement has ≥1 scenario.
- Specific transformations present and correct:
  - domain-ports: `add_tmp` signature shrinks; `select_provider` return `str | None`; prose "gets a ProviderSelection... allocate(selection.name)" rewritten; "Select provider returns ProviderSelection" scenario rewritten to assert string return.
  - cloud-provisioner: requirement paragraph rewritten; "Higher priority wins" scenario assertion rewritten to `returns the string provider_a.name`.
  - use-cases: 3 `clouds.allocate(selection.name)` sites rewritten to `clouds.allocate(selection)`; `add_tmp(selection.name, selection.username)` → `add_tmp(selection)`.
  - postgres-repositories: `add_tmp(cloud)` signature; "Add temporary node" scenario wording rewritten to "given cloud, username defaults to 'root'".
  - test-db-integration: `add_tmp("az")` no username arg; asserts `username="root"` from DB default.
- Consistent with frozen proposal/design baselines (A+B atomic, no option C, DB schema unchanged, public API untouched).

### 🟡 Minor (non-blocking, not fixed)
- Pre-existing self-contradiction in `CloudProvisioner port` (body "capacity() is removed" vs preserved `#### Scenario: Report capacity`) — pre-existing in original, MODIFIED correctly copies full block, out of scope.

### 🔴 Fixed
(none — first-pass review)

---

## specs Round 2 — 2026-06-24

### 🔴 Fixed
- Deleted spurious `## REMOVED Requirements` section from `specs/domain-ports/spec.md` (was lines 81-87). MODIFIED `CloudProvisioner port` already achieves the removal.
- Deleted spurious `## REMOVED Requirements` section from `specs/cloud-provisioner/spec.md` (was lines 40-46). MODIFIED `Provider selection by priority and capacity` already achieves the removal.
- `openspec validate --all --json` re-run: 33/33 passed, 0 failed.

### 🔴 Outstanding
(none — batch frozen)

---

## tasks Round 1 — 2026-06-24

### 🔴 Outstanding
- **O1 — Task 2.1 missed `PURPOSE` update** — `manager.py:101` reads "Select best provider by priority/capacity/platform, wrap result in ProviderSelection." Task 2.1 only mentioned OUTPUTS; the PURPOSE line would continue lying about wrapping into ProviderSelection. No automated check catches this (`grace_check.py` validates structure not content).
- **O2 — Task 1.2 referenced non-existent contract block** — `ports.py` has only two `START_CONTRACT` blocks (OccupancyConfig, TaskExecutionEngine); `CloudProvisioner` is a Protocol with bare stubs, no per-method contract. An implementer would grep for a non-existent block.

### 🟡 Addressed (folded in before freeze)
- **M1 — Task 6.1 stale MODULE_MAP** — `test_domain_model.py:32` MODULE_MAP line for `TestProviderSelection` and line 60 import would be left orphaned. Folded in: remove import, remove MODULE_MAP line, bump CHANGE_SUMMARY.
- **M2 — Tasks 6.2-6.5, 7.1, 7.2 missing CHANGE_SUMMARY bumps** — `proposal.md:48` commits to CHANGE_SUMMARY bumps on touched files. All six test files have `START_CHANGE_SUMMARY` blocks. Folded in: each task now ends with "bump `START_CHANGE_SUMMARY`".
- **M3 — Task 6.3 stale method name/docstring** — `test_cloud_provisioner_impl.py:529,530` reference the deleted type. Folded in: rename method, rewrite docstring.
- **M4 — Task 6.3 dead assertions** — lines 540-541 (`assert result.name == "provider"`, `assert result.username == "root"`) would be dead after rewrite to `assert result == "provider"`. Folded in: explicit removal.

### 🟢 Verification matrix (all pass)
- Coverage: every file in `proposal.md` Impact maps to exactly one task. No missing work, no scope creep.
- Dependency ordering: domain (1) → infra (2,3) → app (4) → graph (5) → tests (6,7) → static checks (8) → test runs (9). Sane.
- Granularity: all 26 tasks ≤2h.
- Static checks section: `zuban check`, `ruff check` + `ruff format --check`, `lint-imports`, `openspec validate`, `grace_check.py` — all six present (matches AGENTS.md Verification).
- Test runs: `-m unit`, `-m integration`, `-m e2e` — all present (matches AGENTS.md Verification).
- Verified accurate against code: `manager.py:134-135` matches D3; `postgres.py:316,321,324` matches task 3.2; `insert_tmp.sql` matches task 3.1 verbatim; test line refs `~313,~391` and `~121,~160,~211,~260` all confirmed.

### 🔴 Fixed
(none — first-pass review)

---

## tasks Round 2 — 2026-06-24

### 🔴 Fixed
- **O1** — Task 2.1 now includes "update the `START_CONTRACT: CloudProvisionerImpl.select_provider` PURPOSE (drop 'wrap result in ProviderSelection') and OUTPUTS to `str | None`".
- **O2** — Task 1.2 dropped the nonexistent contract-block clause; added clarifying note that `CloudProvisioner` is a Protocol with bare stubs, no per-method `START_CONTRACT`.
- **M1** — Task 6.1 now includes removing the import, removing the MODULE_MAP line, and bumping CHANGE_SUMMARY.
- **M2** — Tasks 6.2, 6.3, 6.4, 6.5, 7.1, 7.2 now all end with "bump `START_CHANGE_SUMMARY`".
- **M3** — Task 6.3 now includes method rename and docstring rewrite.
- **M4** — Task 6.3 now explicitly lists the three dead assertions to drop and the replacement.
- No new issues introduced. Granularity, checkbox format, grouping, dependency order, baseline consistency all intact.

### 🔴 Outstanding
(none — batch frozen, change is apply-ready)