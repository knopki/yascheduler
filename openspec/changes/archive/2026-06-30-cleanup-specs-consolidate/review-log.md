# Review Log — cleanup-specs-consolidate

## proposal Round 1 — 2026-06-30
### 🔴 Fixed
- Baseline spec count was 36, actual is 35 → re-baselined all references to 35 → 31 (proposal Why/Net/AGENTS instruction + brief).
- package-facades: scope of removal widened from L487-489 to the entire `yascheduler/config/__init__.py SHALL re-export` block (L485-498) — the package is deleted, so keeping the parent block would orphan a new active defect.
- ssh-keys-loading: made explicit that the defensive `ConfigLocal SHALL NOT carry get_private_keys()` clause + its scenario are stripped too (stale SHALL-NOT about a renamed symbol).

### 🟡 Addressed
- Pulled the same `yascheduler.config` residue class into scope for 4 additional specs (cloud-providers, platform-adapters, dependency-injection, config-parser-assembly) for consistency with the proposal's stated principle. Modified list now 15 (was 11); net unchanged (35 − 5 + 1 = 31).

### 🔴 Outstanding
- (none pending — awaiting Round 2 confirmation)

## proposal Round 2 — 2026-06-30 (k-reviewer-fast)
### ✅ Round-1 fixes confirmed
- Count math 35 − 5 + 1 = 31 holds (Why L3, Net L96).
- package-facades full L485-498 block removal consistent across What-Changes + Modified.
- ssh-keys-loading defensive-clause stripping explicit.
- 4 pull-in specs present in Modified (cloud-providers, platform-adapters, dependency-injection, config-parser-assembly).
- Accounting reconciles: 15 Modified + 5 Removed + 1 New → 31.

### 🔴 Fixed
- L132 AGENTS.md line still said "32 final specs" (residual from pre-fix baseline) → corrected to "31"; grep-verified no remaining 32/36 references in proposal or brief.

### 🔴 Outstanding
- (none)

**Result:** proposal batch frozen. Proceeding to design.

## design Round 1 — 2026-06-30 (k-reviewer-fast)
### 🔴 Serious
- (none)

### 🟡 Fixed
- Context summary said "3 defect fixes" → corrected to "multiple defect fixes across 7 specs" (proposal lists 7 fix locations).
- "Residue strips across all 15 Modified specs" conflated edit types → rephrased to "edits across all 15 Modified specs (residue strips, old-name renames, merges, cli-commands trim)".

### ✅ Confirmed
- D1-D5 cover all proposal commitments; D2 principle testable; D3 preserves config-aggregate layering rule + handles testing de-dup; no contradiction with frozen proposal (cli-commands not split, abstract-uow not merged, no code touched); Non-Goals match brief; Risks cover failure modes; grace_check unaffected (openspec in _SKIP_DIRS).
- Non-actionable note: `docs/knowledge-graph.xml:1262` XML comment mentions "config-aggregate" (refers to the past change/migration name, not the spec); not a module record, not scanned by grace_check for spec names. Awareness only.

### 🔴 Outstanding
- (none)

**Result:** design batch frozen. Proceeding to specs.

## design UNFREEZE — 2026-06-30
### Reason
D1 asserted "full-file rewrite" representation, citing the `2026-06-28-cleanup-stale-specs`
precedent. Re-inspection of the precedent showed it actually used surgical
requirement-level deltas (`## MODIFIED/ADDED/REMOVED Requirements`, `### Requirement: <name>`)
with small files (domain-ports 49 lines, package-facades 108). The D1 rationale
("per-requirement deltas would be longer and unreadable") was factually wrong — deltas
are far shorter and more reviewable. Decision-level methodology change → unfreeze design
(specs/tasks not yet created, so no downstream cascade).

### Change applied
- D1 rewritten: delta representation with MODIFIED/ADDED/REMOVED sections, delta files
  are small; whole-capability removal expressed by listing all requirements under
  REMOVED. "Full-file rewrite" moved to the rejected-alternative slot.
- Goals bullet + Migration Plan step 1 reworded to match delta representation.
- Risk bullet "Full-file delta rewrite…" reworded to "A MODIFIED requirement's new
  text drifts from intent" (the apply-failure mode under delta representation).

### 🔴 Outstanding
- (none)

**Result:** design batch re-frozen (D1 corrected). Proceeding to specs.

## specs Round 1 — 2026-06-30 (k-reviewer-fast)
### 🔴 Serious
- (none)

### 🟡 Minor (not required)
- cloud-config "connect_grace is not parsed from INI" scenario retains "sole source" framing — acceptable current-state assertion.

### ✅ Confirmed
- Coverage: 21 delta files (1 New + 15 Modified + 5 Removed) match proposal 1:1.
- D2 residue-strip correct across all 15 modified specs; positive constraints preserved.
- All 6 category-A defect fixes applied (capacity scenario, ConfigLocal block, client.py path, ConfigDb×2, ConfigRemote).
- 3 merges preserve live requirements + layering rule; testing de-dup correct.
- Delta format consistent (MODIFIED/ADDED/REMOVED + exact-name headers).
- No live contract lost.

### Deviation accepted
- cli-commands: proposal promised shared exit-code extraction + ~1482→~800. Actual delta strips only the to_sync narrative from "CLI commands call use cases via DI". Accepted rationale: shared "Daemon and CLI exit-code contract" already exists; per-command exit-code requirements carry command-specific scenarios (not pure 0/1/2 duplication). cli-commands line reduction is therefore smaller than the aspirational ~800.

### 🔴 Outstanding
- (none)

**Result:** specs batch frozen. Proceeding to tasks.

## tasks Round 1 — 2026-06-30 (k-reviewer-fast)
### 🔴 Serious
- (none)

### 🟡 Fixed
- Split task 1.2 into 1.2 (14 deltas) + 1.3 (cli-commands, called out separately with the retained-per-command-scenarios rationale) for progress-tracking clarity.

### ✅ Confirmed
- Apply scope complete (21 deltas + 5 dir deletes + AGENTS.md + verification).
- No code/test/graph/pyproject edits requested (specs-only).
- Granularity ≤2h each.
- Verification grep covers all 9 removed symbols.

### 🔴 Outstanding
- (none)

**Result:** tasks batch frozen. Propose phase complete — all 4 artifacts (proposal, design, specs, tasks) frozen and `openspec validate --all --json` passing (37/37). Ready for `/opsx-apply`.
