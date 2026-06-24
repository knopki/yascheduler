## proposal Round 1 — 2026-06-24

### 🔴 Fixed
- None blocked freeze.

### 🟡 Addressed
- `typing_extensions` dependency status mischaracterized (claimed "transitive via dev tooling"; actually declared in `pyproject.toml:39` with marker `python_version < '3.11'`) → rewrote Impact > Imports and Dependencies to state the declaration accurately and drop the self-contradicting "follow-up audit" hedge.
- Python 3.11+ runtime import gap: proposal was silent on how `Unpack`/`Self` import works on 3.11+ where `typing-extensions` is not installed → specified the import strategy: extend `yascheduler/shared/compat.py` with a version-branched `Unpack` re-export (mirroring the existing `Self`/`ParamSpec` pattern); `model.py` imports from `yascheduler.shared`. compat.py VERSION/MODULE_MAP/CHANGE_SUMMARY bump noted in Impact > Code.
- Return type inconsistency: What Changes used `-> Self`, Capabilities used `-> TaskContext` → unified to `-> Self` in the Capabilities bullet so the specs batch copies a consistent contract.

### ✅ Confirmed (brief commitments verified)
- Method name `replace` (not `evolve`/`update`/`with_overrides`).
- Signature `**overrides: Unpack[TaskContextOverrides]` (TypedDict, total=False).
- Return type `Self`.
- TypedDict = exactly 4 fields (`remote_folder`, `local_folder`, `error`, `extra`); YAGNI on the other 3.
- Drift-lock unit test committed.
- All 4 call sites migrate (submit_task.py:90, consume_task.py:98, model.py:237 Task.fail, model.py:259 Task.reject) — fail/reject internals ACCEPTED into scope.
- `dataclasses.replace` import stays in model.py for Task-level replace(self, ...).
- Lexical-scoping safety of bare `replace` in method body correctly described.
- Out-of-scope items faithful: no general evolve/with_overrides for Engine/Node/etc.; no Task-level migration; no validation guard; no extension to all 7 fields.
- Schema correct (Why / What Changes / Capabilities / Impact); Modified Capabilities reference real existing requirement names (`domain-entities`, `testing-unit`); no BREAKING markers; additive-only.

### 🔴 Outstanding
- None. Batch frozen.

## specs Round 1 — 2026-06-24

### 🔴 Fixed
- None.

### 🟡 Addressed
- None.

### ✅ Confirmed commitments
- Delta headers `## MODIFIED Requirements` on both files (not ADDED).
- Requirement names match live spec exactly: `TaskContext typed metadata` (domain-entities), `Domain entities lifecycle` (testing-unit).
- Existing scenarios fully preserved in MODIFIED blocks (no dropped scenarios — archive safety).
- Full requirement prose preserved before extension.
- `#### Scenario` format (4 hashtags) with WHEN/THEN on every scenario.
- `replace` scenario coverage: single-field, multi-field, original-unchanged, no-override equal copy, type-checker rejects unknown kwargs, drift-lock on field set, additive-only.
- `TaskContextOverrides` field set = exactly `{remote_folder, local_folder, error, extra}` in both deltas.
- Return type `Self` in domain-entities delta (consistent with frozen proposal/design).
- `openspec validate --changes task-context-replace` passes (exit 0).

### 🔴 Outstanding
- None. Batch frozen.

### 🔴 Fixed
- None blocked freeze.

### 🟡 Addressed
- Migration plan step 3 now explicitly notes the dead-import check for `submit_task.py`/`consume_task.py` (`from dataclasses import replace` may become removable; `model.py` import stays for Task-level uses).
- `TypedDict` import source clarified in §D6: imported from `typing` (stdlib since 3.8); drift-lock test accesses only `__annotations__` keys, so `from __future__ import annotations` stringification is harmless.
- Knowledge-graph annotation prefix for `Unpack` in `M-SHARED` corrected from `<export-Unpack>` to `<type-Unpack>` to match the existing `<type-Self>`/`<type-ParamSpec>` convention.

### ✅ Confirmed commitments
- All 12 brief/proposal commitments verified present (D1-D8 + call sites + import retention + Python compat + GRACE-lite).
- Lexical-scoping safety of bare `replace` correctly explained (resolves to module-level import, no recursion).
- Compat-shim strategy for `Unpack` symmetric with existing `Self`/`ParamSpec` pattern.
- Return type `Self` used consistently (no drift to `TaskContext`).
- Four call-site line numbers verified against source (consume_task.py:98 spans multiple lines — verified by direct read).
- Schema conforms: Context / Goals-Non-Goals / Decisions (with rationale + rejected alternatives) / Risks ([Risk] -> Mitigation) / Migration Plan / Open Questions ("None").

## specs Round 1 — 2026-06-24

### 🔴 Fixed
- None.

### 🟡 Addressed
- None.

### ✅ Confirmed commitments
- Delta headers `## MODIFIED Requirements` on both files (not ADDED).
- Requirement names match live spec exactly: `TaskContext typed metadata` (domain-entities), `Domain entities lifecycle` (testing-unit).
- Existing scenarios fully preserved in MODIFIED blocks (no dropped scenarios — archive safety).
- Full requirement prose preserved before extension.
- `#### Scenario` format (4 hashtags) with WHEN/THEN on every scenario.
- `replace` scenario coverage: single-field, multi-field, original-unchanged, no-override equal copy, type-checker rejects unknown kwargs, drift-lock on field set, additive-only.
- `TaskContextOverrides` field set = exactly `{remote_folder, local_folder, error, extra}` in both deltas.
- Return type `Self` in domain-entities delta (consistent with frozen proposal/design).
- `openspec validate --changes task-context-replace` passes (exit 0).

### 🔴 Outstanding
- None. Batch frozen.

## tasks Round 1 — 2026-06-24

### 🔴 Fixed
- None blocked freeze.

### 🟡 Addressed
- Tasks 3.2 and 3.5: replaced the `rg "replace\("` verification with a negative-lookbehind regex `rg "(?<!\.)replace\("` to exclude `.replace(` method calls (which would have caused false positives and confused the implementer into keeping a dead import). Added `ruff F401` as a safety net.
- Task 1.4: made the `shared/__init__.py` VERSION bump and CHANGE_SUMMARY update explicit (1.6.0 → 1.7.0, with LAST_CHANGE entry), with a fallback if the file carries no VERSION/CHANGE_SUMMARY.
- Task 5.6: refactored from a near-duplicate of 5.4 into an integration test that exercises `Task.fail("disk full")` end-to-end, verifying the migrated internal `self.context.replace(error=reason)` (model.py:237) is behavior-preserving. Avoids duplication with 5.4 while adding unique integration coverage.

### ✅ Confirmed commitments
- All D1-D8 design decisions have implementing tasks.
- All 4 call sites covered (3.1, 3.4, 3.7, 3.8).
- Dead-import removal with verification (3.2, 3.5) — now with correct regex.
- model.py `dataclasses.replace` import retention explicit (3.9).
- Knowledge-graph prefix `<type-Unpack>` (not `<export-Unpack>`) — consistent with existing `<type-Self>`/`<type-ParamSpec>`.
- GRACE markup tasks for compat.py (1.2-1.4), model.py (2.5-2.6), submit_task.py (3.3), consume_task.py (3.6).
- VERSION bumps match current file headers: compat.py 1.6.0→1.7.0, model.py 1.11.0→1.12.0, submit_task.py 1.2.0→1.3.0, consume_task.py 5.2.0→5.3.0.
- Spec scenario coverage complete: single-field (5.2), multi-field (5.3), original-unchanged (5.4), no-override equal copy (5.5), error-override-via-fail integration (5.6), drift-lock (5.7), chain-through-with_context (5.8). Type-checker rejection enforced statically by zuban (7.3).
- Ordering: compat (1) → model.py (2) → migration (3) → knowledge graph (4) → tests (5) → verify-behavior (6) → static checks (7) → final smoke (8).
- All files within proposal Impact scope; no DB/config/pyproject/AiiDA touched.
- Format `- [ ] N.M` under `## N. Group`; every task ≤2h.
- `openspec validate --changes task-context-replace` passes (exit 0); status 4/4 artifacts complete.

### 🔴 Outstanding
- None. Batch frozen. Change ready for `/opsx-apply`.