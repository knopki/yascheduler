# Review Log — migrate-cloud-from-attrs

## proposal Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast (against frozen explore-brief.md baseline)

### Verdict: GO

### Brief-coverage
- Scope: captured (spread across What Changes + Impact)
- Rejected alternatives: missing from proposal (consistent with SSH precedent; preserved in brief)
- Mechanical mapping table: captured (as bullet list)
- asdict divergence finding: captured (Impact > Behavior)
- Cross-module data flow: partial (key facts present; graph not reproduced — precedent-consistent)
- Canary test T1: captured (name, parent class, file, purpose)
- Spec delta: captured (MODIFIED, stale path fix, render scenario)
- Known risks/pitfalls: partial (risk #1 fully captured; #2/#3 branded "apply-time detail" in brief — acceptable omission)
- Static checks: missing (consistent with precedent proposals)

### 🔴 Fixed
- (none — pre-proposal 🔴 re: `replace()` type error was already captured in proposal before this round)

### 🟡 Addressed (declarative soft-add to frozen proposal.md)
- Clarified spec delta scope: explicitly note other stale paths in "Provider code relocated" are out of scope.
- Added note on trying to remove `# type: ignore[arg-type]` in cloud_config.py:41 when switching asdict.

### 🔴 Outstanding
- (none)

Batch frozen. Proceeding to design + specs.

## design Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast (against frozen proposal.md + explore-brief.md)

### Verdict: GO (single-round pass — no 🔴 outstanding)

### Proposal-coverage
All 10 "What Changes" + 6 "Impact" items captured across Decisions 1-7. No contradictions.

### Decision-quality
🟢 All 7 decisions explain WHY, not just WHAT. Precedents correctly cited (queue 1.7.0→1.8.0, ssh 1.0.1→1.1.0). Hybrid az.py rationale covers both directions (evolve MUST go / asdict MUST stay). Canary placement justified. Spec delta operation justified.

### 🔴 Fixed
- (none)

### 🟡 Addressed
- (none — reviewer noted design goes beyond proposal in specifying exact version table at Decision 6; this is a declarative addition, not decision-level)

### 🔴 Outstanding
- (none)

Batch frozen.

## specs Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast (against frozen proposal.md + design.md + existing main spec)

### Verdict: GO (single-round pass — no 🔴 outstanding)

### Delta-rules compliance
All 13 rules pass:
- `## MODIFIED Requirements` header ✓
- Full requirement block copied + edited ✓
- Header text matches main spec exactly ✓
- 2 scenarios (1 modified, 1 added), all 4-hashtag ✓
- WHEN/THEN(/AND) format ✓
- SHALL normative ✓
- "Provider code relocated" + "Optional provider SDKs" untouched (out of scope) ✓
- Matches proposal Capabilities declaration ✓

### 🔴 Fixed
- (none)

### 🟡 Addressed
- (none)

### 🔴 Outstanding
- (none)

Batch frozen. Proceeding to tasks.

## tasks Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast (against frozen proposal.md + design.md + specs/)

### Verdict: GO (single-round pass — no 🔴 outstanding)

### Format compliance
pass — 16 tasks (after 🟡 additions) all use `- [ ] N.M description`; groups use `## N. Group`; each task ≤ ~20 lines, < 2 hours.

### Coverage
All 17 proposal/design items covered. No gaps. No scope creep.

### 🔴 Fixed
- (none)

### 🟡 Addressed (declarative soft-add to frozen tasks.md)
- Reworded task 6.1 from "write" to "verify and finalize" (the delta file pre-exists from design round; verb clarity).
- Added group 8 "Non-goals verification" (8.1 pyproject untouched, 8.2 no out-of-scope files touched) — defense-in-depth matching SSH precedent.

### 🔴 Outstanding
- (none)

Batch frozen. All artifacts complete.
