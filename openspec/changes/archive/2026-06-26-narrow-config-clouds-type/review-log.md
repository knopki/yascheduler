# Review Log — narrow-config-clouds-type

## proposal Round 1 — 2026-06-26

### 🔴 Fixed

(Empty — first pass.)

### 🟡 Addressed

(Empty — first pass.)

### 🔴 Outstanding

**None — batch is clean for freeze.**

The proposal is factually accurate, internally consistent, and fully captures the commitments from the explore brief. Specific verification points:

1. **Historical accuracy.** The proposal correctly states that the prior `2026-06-26-resolve-type-bridge-debt` rejected A1 because `list[ConfigCloud] → Sequence[CloudConfig]` failed under writable-vs-frozen mismatch (design.md:137-142), and that D1 removed that mismatch. The same D1 that enabled the 2 upcast removals also makes A1 viable — the proposal's core thesis is sound.

2. **Code-level correctness.** Every source reference was verified against the actual tree:
   - `config.py:42` currently typed `Sequence[CloudConfig]` → narrowed to `Sequence[ConfigCloud]` under A1.
   - `di.py:165` (`cast("ConfigCloud", cfg)`) and `di.py:194-201` (`cast("list[ConfigCloud]", [...])`) are the only `cast(` calls in `entrypoints/` (confirmed via grep).
   - `cast` is not used elsewhere in `di.py`; the import can be dropped cleanly (confirmed via full-file read).
   - The DTOs already explicitly inherit `CloudConfig` (confirmed in `cloud_configs.py:62,88,106,122`); `ConfigCloud` Union is defined at line 144.
   - `config_parser.py` already imports `ConfigCloud` via the deep path `yascheduler.infra.cloud.cloud_configs` (line 73), so the same deep-path import in `config.py` is consistent with existing patterns.

3. **Spec deltas correctly identified.** The three specs requiring deltas (`config-aggregate`, `cloud-config-protocol`, `dependency-injection`) are the right set. The existing `cloud-config-protocol` spec's "Retained downcasts" Scenario (lines 127-135) must be replaced and merged with the "No upcast bridges" Scenario (lines 121-125) into a single "No cast bridges" Scenario — the proposal correctly describes this.

4. **Layers contract.** The new `TYPE_CHECKING`-only `entrypoints → infra.cloud.cloud_configs` edge in `config.py` is permitted (`entrypoints > infra`). The existing `exclude_type_checking_imports = true` (confirmed at `pyproject.toml:119`) means `uv run lint-imports` is unaffected.

5. **Knowledge graph.** `M-CLOUD-CONFIGS` is already in `M-ENTRYPOINTS-CONFIG`'s `<depends>` (confirmed at `config.py:6`). No graph entry changes needed.

6. **Public surface.** `Config.clouds` is not part of any stabilized surface per AGENTS.md. Confirmed no `isinstance` checks against `Config` exist in production code.

Minor items intentionally omitted from the proposal (not required, not serious):
- The mapping table and cross-module data flow are in the explore brief; the proposal conveys the same information in prose.
- The rejected alternatives (B, C) are documented in the brief; the proposal doesn't repeat them, which is appropriate for a forward-looking change document.

Recommendation: **APPROVE** — freeze the proposal.

## design+specs Round 2 — 2026-06-26

### 🔴 Fixed
- D3 regression test false-positive on comment tokens (Round 1 blocker) — resolved by switching from plain string `"cast(" not in source` to AST-based checks (`ast.parse` + `ast.walk`): `ast.ImportFrom` from `typing` binding `cast`, `ast.Call` with bare-name `cast`, and `ast.Call` with `typing.cast` attribute. Comments and string literals are not visited by `ast.walk`, so the `CHANGE_SUMMARY` `PREVIOUS_CHANGE` tokens (verbatim `cast("ConfigCloud", cfg)`, `cast("list[ConfigCloud]", [...])`) do not trip the test. Spec Scenarios in `cloud-config-protocol` and `dependency-injection` deltas updated to describe the AST approach.
- `assert` → `raise AssertionError` in D3 ImportFrom branch for consistency with the two Call branches (under `python -O` `assert` is silently disabled; `raise AssertionError` is not).

### 🟡 Addressed
- All 6 verification points confirmed sound: AST soundness, reintroduction coverage (including `from typing import cast as _c` caught by ImportFrom check via `alias.name`), post-implementation parse correctness, spec-D3 consistency, D5-D3 consistency, no new issues.
- Exotic evasion paths (`getattr(typing, "cast")(...)`, `import typing; c = typing.cast; c(...)`) not caught — acceptable, code-review territory.

### 🔴 Outstanding
None — batch is clean for freeze.

## tasks Round 1 — 2026-06-26

### 🔴 Fixed

(Leave empty — first pass.)

### 🟡 Addressed

(Leave empty — first pass.)

### 🔴 Outstanding

None — batch is clean for freeze.

Verification against all 8 criteria:

1. **Coverage of D1–D5.** Every design decision has matching tasks:
   - D1 (narrow Config.clouds) → 1.1–1.4
   - D2 (drop casts + cast import) → 2.1–2.5
   - D3 (AST regression test) → 3.1–3.2
   - D4 (spec deltas) → correctly absent from tasks (already created as artifacts)
   - D5 (CHANGE_SUMMARY updates) → 1.4, 2.5

2. **Spec coverage.** Every normative Scenario in the 3 delta specs is satisfied by at least one task. No gap.

3. **Ordering.** 1.x → 2.x → 3.x → 4.x → 5.x → 6.x is correct. Task 2.1 explicitly notes it depends on D1 (the narrowed field type). Task 3.2 explicitly checks against post-task-2 di.py.

4. **Granularity.** All tasks are single-file edits or single-command runs, well under 2 hours.

5. **Verifiability.** Every verification command from the proposal's Impact-Verification section maps 1:1 to a task (4.1 zuban, 4.2 ruff check, 4.3 ruff format, 4.4 lint-imports, 4.5 rg cast, 5.1 pytest -m unit, 6.1 openspec validate, 6.2 grace_check). Plus explicit error-recovery steps (what to do if zuban flags a type error at Orchestrator call, what to do if AST test fails).

6. **No contradictions with frozen artifacts.** No task touches application-layer typing (design Non-Goals), SDK stub casts (Non-Goals), module renaming/relocating/splitting (Non-Goals), or D1 itself (Non-Goals). No task changes CLI, INI, DB schema, or AiiDA.

7. **Factual accuracy.** All line references verified against current source:
   - di.py:148–201 (both cast sites) — verified lines match
   - di.py line 28 (`from typing import TYPE_CHECKING, cast`) — correct
   - di.py:204–206 (upcast comment) — correct
   - `pyproject.toml:119` (`exclude_type_checking_imports = true`) — confirmed
   - `pyproject.toml:122–131` (layers contract) — confirmed
   - `ConfigCloud` importable from `yascheduler.infra.cloud.cloud_configs` — confirmed (same deep path as `config_parser.py:57–63`)
   - `config.py:18` (`from __future__ import annotations`) — confirmed

8. **Pre-existing unrelated invalid change.** Task 6.1 correctly instructs to ignore the unrelated `cloud-init-rename-and-prune` invalid item.

Recommendation: **APPROVE** — freeze the tasks.
