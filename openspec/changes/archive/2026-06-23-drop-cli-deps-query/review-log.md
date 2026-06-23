## proposal Round 1 — 2026-06-23

### 🟡 Addressed
- Citation inaccuracy: the "deferred follow-up" reference pointed vaguely at
  `review-log.md:360`; corrected to point at the prior change's `design.md`
  "Open follow-ups" section and `review-log.md` lines 41-42 (the actual
  locations of the deferred-cleanup note).

### 🔴 Outstanding
- None.

### Verdict
PASS — proposal frozen. Single minor (🟡) citation fix applied inline before
freeze. All factual claims verified against the codebase: zero production
callers, correct spec deltas enumerated, `CLIDeps` confirmed outside the
`AGENTS.md` public-interface stability list.

## design + specs Round 1 — 2026-06-23

### 🟡 Addressed
- D4 was over-ceremonial for a one-word XML attribute change (full decision
  block with implicit alternatives framing). Trimmed to a brief traceability
  note acknowledging the task-line is the real home for the action.

### 🔴 Outstanding
- None.

### Verdict
PASS — design.md + specs/dependency-injection + specs/testing-unit frozen as
a batch. Spec deltas match the baseline requirement headers exactly, both
scenarios use 4 hashtags, scope fences are correct, no scope creep.

## tasks Round 1 — 2026-06-23

### 🟡 Addressed
- Task 1.3 was misdirected: it pointed at the `START_MODULE_CONTRACT` SCOPE
  line (which doesn't contain `query`), missing the real target — the
  `START_CONTRACT: CLIDeps` PURPOSE line at di.py:64 ("...for CLI submit and
  query operations."). Rewrote 1.3 to edit the class contract PURPOSE as the
  primary action and keep the SCOPE-line check as a defensive no-op.
- Task 1.4 said "append a `START_CHANGE_SUMMARY` entry" but the block already
  exists. Rephrased to "update the existing block" to avoid a literal-minded
  implementer creating a duplicate.
- Added `uv run lint-imports` as task 4.3 (renumbered grace_check → 4.4,
  openspec validate → 4.5). No imports change, but the check is on the
  project's required list and is cheap to run.

### 🔴 Outstanding
- None.

### Verdict
PASS — tasks.md frozen. Checklist covers every proposal/design item, checkbox
format is parser-compliant, ordering is correct, verification now exercises
the four required commands relevant to this change (pytest unit, ruff,
lint-imports, grace_check, openspec validate).


