# Review Log — cloud-init-rename-and-prune

## proposal Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast (against `explore-brief.md` baseline)

### Verdict: PASS

### 🔴 Fixed (issues from this round, now applied)
- (none — no Critical Issues raised)

### 🟡 Addressed (suggestions folded in)
- Added explicit TYPE_CHECKING import block cleanup bullet for the 5 provider/manager files (`manager.py`, `az.py`, `hetzner.py`, `upcloud.py`, `vastai.py`) — covered by the zero-match verification grep but now called out explicitly in "What Changes".
- Clarified `manager.py` constructor call update: `return CloudConfig(...)` at line 283 → `CloudInitConfig(...)` now explicitly listed, not just the return annotation.
- Normalized the isinstance-guard line-number reference: "lines 329-337" used consistently (the comment block 329-332 + the `if`/raise at 333-337); the bare `az.py:333` shorthand kept only in the top-level "What Changes" summary.

### 🔴 Outstanding
- (none)

### Frozen
`proposal.md` is frozen. Subsequent batches (design, specs, tasks) use it as the consistency baseline.

### Confirmed Captured Commitments (from brief)
- Three-part structure: rename Concept B / remove PCloudConfig / delete CloudCapacity
- Decided parameters: Optional-style not load-bearing; spec delta to existing `cloud-provisioner` capability; rename `M-CLOUD-CONFIG` → `M-CLOUD-INIT` (not a new node); `M-CLOUD-CONFIGS` (plural) untouched
- Variance mechanics: coordinated one-pass retyping of `CreateNodeCallable.__call__` + 5 provider signatures; D3a isinstance guard deleted as redundant
- Sequencing: AFTER `resolve-type-bridge-debt` archive (confirmed done)
- CloudCapacity not-public status + removal justification
- Cross-module data flow: all concrete, no Protocol indirection
- DOMAIN vs INFRA CloudConfig distinction correctly drawn; `cloud-config-protocol` spec NOT listed as modified
## design Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast (against frozen `proposal.md` + `explore-brief.md`)

### Verdict: PASS with notes (fixes applied, round 2 pending)

### 🔴 Fixed (issues from this round, applied)
- (none — no Critical Issues raised)

### 🟡 Addressed (suggestions folded in)
- D5: corrected the factually-wrong "zero incoming `<depends>` edges" claim — `M-CLOUD-PROVISIONER` at `knowledge-graph.xml:703` depends on `M-CLOUD-CONFIG`. Rewrote D5 to name the single incoming edge and prescribe a word-boundary find-and-replace that catches the node definition, closing tag, and incoming edge without touching `M-CLOUD-CONFIGS` (plural). Updated the corresponding Risk entry to match.
- D5: added explicit acknowledgment of source-level `LINKS: M-CLOUD-CONFIG` references in `cloud_config.py:8` and `manager.py:265`, mapped to migration steps 1 and 2 respectively.
- Migration Plan step 1: added explicit atomic-commit instruction ("Steps 1 and 2 MUST land as a single atomic commit; the intermediate state after step 1 alone has broken imports; stage step 1, then apply step 2, then commit atomically").
- Added D7: spec deltas to `cloud-provisioner` and `package-facades` explicitly enumerated (previously only implied by D2/D4 cross-references).

### 🔴 Outstanding
- (none after fixes)

### Frozen
Pending round 2 confirmation. `design.md` will be frozen once @k-reviewer-fast confirms the D5 fix and the atomic-commit clarification resolve the round 1 notes.

## design Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast (against frozen proposal.md + explore-brief.md)

### Verdict: PASS

### 🔴 Fixed
- (none — no Critical Issues raised)

### 🟡 Addressed (suggestions folded in)
- D5 `<depends>` factual clarification: the "imports only stdlib" claim was true post-change but not pre-change (currently also imports `from .protocols import PCloudConfig`); reworded to distinguish timeframes and note the graph's pre-existing `none` entry becomes literally true after D2.
- D2 scope: explicitly added `manager.py:267` return annotation + `manager.py:283` constructor call to the Decision block; added clarifying sentence in the "one pass" rationale that manager.py items are retyped in the same pass (not for variance — they are returns, not callable params — but to avoid dangling references to the deleted Protocol / renamed class).

### 🔴 Outstanding
- (none)

### Frozen
`design.md` is frozen. Subsequent batches (specs, tasks) use it + frozen proposal.md as the consistency baseline.

### Technical Argument Soundness Confirmed
- D2 variance: symmetric-narrowing argument sound; one-pass-not-incremental justified by contravariance
- D3 death-proof: grep claims correct; `CloudCapacityExhaustedError` correctly excluded
- D4 redundancy: D3a guard premise vanishes after D2; trace is correct
- D5 graph ripple: zero incoming edges, zero CrossLinks confirmed; rename is pure relabel

### Factual Errors Fixed
- D5 `<depends>` timeframe conflation (current vs post-change import set) — fixed

## specs Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast (against frozen proposal.md + design.md + existing main specs)

### Verdict: PASS

### 🔴 Fixed
- (none — no Critical Issues raised)

### 🟡 Addressed
- (none — no Suggestions raised)

### 🔴 Outstanding
- (none)

### Frozen
Both delta specs are frozen:
- `specs/cloud-provisioner/spec.md`
- `specs/package-facades/spec.md`

Subsequent batch (tasks) uses frozen proposal.md + design.md + specs as the consistency baseline.

### Header Match Verification
- `cloud-provisioner`: `### Requirement: CloudProvisionerImpl owns cloud-init rendering and SSH key management` — exact match with main spec line 143 ✓
- `package-facades`: `### Requirement: Extended facade contents (lazy publication driven by consumers)` — exact match with main spec line 425 ✓

### Block Completeness Verification
- `cloud-provisioner`: both existing scenarios preserved (1 edited in place for rename, 1 verbatim); 6 new scenarios added
- `package-facades`: all 9 sub-bullets + 9 existing scenarios preserved; 4 new scenarios added; cloud subpackage bullet block correctly gains `CloudInitConfig`, loses `PCloudConfig` from snapshot, gains 3 "SHALL NO LONGER" bullets

### Scenario Format Compliance
- All scenarios use exactly 4 hashtags (`####`)
- All requirements use SHALL/MUST normative language
- Every requirement has ≥1 scenario

### Domain vs Infra CloudConfig Distinction
- `package-facades` delta scenario "Cloud subpackage facade no longer re-exports the infra CloudConfig renderer" correctly distinguishes the infra renderer (removed from `infra/cloud` facade) from the domain Protocol (still importable from `yascheduler.domain`, NOT touched by this change)

## tasks Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast (against frozen proposal.md + design.md + both delta specs)

### Verdict: APPROVE WITH NOTES → PASS after fixes

### 🔴 Fixed
- (none Critical)

### 🟡 Addressed (3 suggestions folded in)
- Task 5.1: added explicit sub-task to update the `M-CLOUD-PROVISIONER` `<depends>` list at `docs/knowledge-graph.xml:703` (`M-CLOUD-CONFIG` → `M-CLOUD-INIT`). This was a real factual correction — the singular node IS referenced in `M-CLOUD-PROVISIONER`'s depends (line 703), which design.md D5 had previously and incorrectly claimed did not exist.
- Task 1.3: corrected parenthetical from "drops in task 2.1" (wrong — task 2.1 is `protocols.py`) to "drops in task 1.5" (the same D1 group task that drops the `from .protocols import PCloudConfig` import from `cloud_init.py`).
- Task 5.5: rewrote the verification regex from `depends>M-CLOUD-CONFIG\b` (did not match the actual XML format `<depends>...M-CLOUD-CONFIG, ...`) to `rg -n 'M-CLOUD-CONFIG\b' docs/knowledge-graph.xml` (correctly matches the node tag AND any depends edge; `\b` excludes `M-CLOUD-CONFIGS` plural).

### 🔴 Outstanding
- (none)

### Cross-artifact unfreeze triggered by Round 1
- design.md D5 was UNFROZEN to correct its "zero incoming edges" / "zero graph ripple" claims to "one incoming `<depends>` edge from `M-CLOUD-PROVISIONER` at line 703, updated in the same change; zero CrossLinks" / "minimal graph ripple". Re-frozen after correction.
- proposal.md's Knowledge graph Impact bullet was UNFROZEN to correct the same "zero incoming edges" factual error; reworded to "The single incoming `<depends>` edge (from `M-CLOUD-PROVISIONER` at line 703) is updated in the same change to reference `M-CLOUD-INIT`." Re-frozen.

### tasks Round 2 (consolidation) — 2026-06-26
- Folded redundant tasks 5.3 and 5.5 into a single task 5.3 (both ran the same `rg 'M-CLOUD-CONFIG\b'` grep expecting zero matches; 5.5 additionally checked `CrossLink.*M-CLOUD-CONFIG\b`, now merged into 5.3). Renumbered 5.4 (M-CLOUD-CONFIGS plural unchanged) to follow.

### Frozen
`tasks.md` is frozen. All four artifacts (proposal, design, specs, tasks) are frozen and apply-ready.

### Final Validation
- `openspec validate cloud-init-rename-and-prune --json` → `valid: true`, zero issues.
- `openspec status --change cloud-init-rename-and-prune` → 4/4 artifacts complete; ready for implementation.
