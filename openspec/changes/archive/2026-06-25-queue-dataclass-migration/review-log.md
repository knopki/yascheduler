# Review Log — queue-dataclass-migration

## proposal Round 1 — 2026-06-25

**Reviewer**: `@k-reviewer-fast`
**Baseline**: `explore-brief.md` (no prior frozen artifacts)

### ✅ Captured
- All 10 brief commitments verified present and accurate: pilot scope,
  `@define` → `@dataclass(frozen=True)`, manual `__slots__` (S2) with correct
  3.9 rationale, `field(compare=False)` + P1 invariant, three tests (T1/T2/T3),
  spec deltas for `testing-infrastructure` (W2) and `testing-unit`,
  `UniqueQueue` unchanged, `attrs` dependency retained, Python version
  unchanged, no public-API impact (internal symbols).

### 🟡 Addressed (applied in this round)
- Knowledge-graph no-op statement was implied but not explicit → added an
  explicit bullet to the Impact section noting no `docs/knowledge-graph.xml`
  edit is required (M-QUEUE surface and `DEPENDS: none` unchanged; only
  file-local `CHANGE_SUMMARY` updated).

### 🔴 Outstanding
- None.

**Outcome**: batch **frozen**. Proceeding to `design.md`.

## design Round 1 — 2026-06-25

**Reviewer**: `@k-reviewer-fast`
**Baseline**: `explore-brief.md` + `proposal.md` (frozen)

### ✅ Captured
- All five decisions verified: D1 (S2 manual `__slots__`, 3.9 rationale, three
  rejected alternatives), D2 (P1 with accurate 3-row equality matrix),
  D3 (first-wins preserved), D4 (T1+T2+T3 with correct setups/assertions),
  D5 (W2 full contract for testing-infrastructure, declarative alignment for
  testing-unit).
- No contradictions with frozen proposal.md. No scope creep. No implementation
  code beyond short sketches.

### 🟡 Addressed (applied in this round)
- Risk mitigation #3 incorrectly claimed `ValueError` for a missing slot on a
  slotted frozen dataclass. Verified empirically: actual exception is
  `AttributeError: 'Foo' object has no attribute 'b'` at instance
  construction. Fixed wording + added "(Verified empirically on CPython 3.x.)".

### 🔴 Outstanding
- None.

**Outcome**: batch **frozen**. Proceeding to `specs/`.

## specs Round 1 — 2026-06-25

**Reviewer**: `@k-reviewer-fast`
**Baseline**: `explore-brief.md` + `proposal.md` + `design.md` (all frozen)

### ✅ Captured
- Both delta headers match source requirement names exactly
  (`UniqueQueue unit tests` / `UniqueQueue`).
- W2 full contract (all 4 points) present in both deltas: id-keyed dedup,
  equal-id-different-payload are duplicates, payload excluded from
  `__eq__`/`__hash__`, unhashable payload valid.
- All scenarios use exactly 4 hashtags. Each requirement has ≥1 scenario.
- T1/T2/T3 intent fully covered across the two deltas.
- Normative SHALL used throughout. No scope creep (only the `UniqueQueue`
  requirement touched in each spec; no new capability folders).

### 🟡 Addressed (applied in this round)
- testing-unit delta originally added 2 new scenarios, contradicting
  proposal.md's stated "no new scenario beyond what the prose already implies"
  for testing-unit. **Fixed by trimming testing-unit delta** to: (a) MODIFY the
  requirement prose (W2 invariant paragraph) + (b) keep the single original
  scenario, minimally reworded to mention "equal `id`". The two new scenarios
  remain in the testing-infrastructure delta (proposal did not constrain
  scenarios there). `openspec validate` re-passed after trim. Proposal remains
  frozen; no cascade unfreeze needed.

### 🔴 Outstanding
- None.

**Outcome**: batch **frozen**. Proceeding to `tasks.md`.

## tasks Round 1 — 2026-06-25

**Reviewer**: `@k-reviewer-fast`
**Baseline**: `explore-brief.md` + `proposal.md` + `design.md` + both spec deltas (all frozen)

### ✅ Captured
- All five design decisions (D1–D5) mapped to tasks; every proposal "What
  Changes" bullet covered; no orphan tasks.
- Granularity atomic (each task ≤2h, mostly minutes); ordering correct
  (class migration → tests → spec sync → verification).
- All seven AGENTS.md verification commands present (pytest, zuban, ruff ×2,
  lint-imports, grace_check, openspec validate).
- GRACE-lite compliance: VERSION bumps, CHANGE_SUMMARY entries, MODULE_MAP
  update, START_CONTRACT blocks on each new test.
- No scope creep: no task touches `config/*`, `infra/*`, `UniqueQueue` logic,
  `pyproject.toml`, `requires-python`, or `docs/knowledge-graph.xml`.
- Every task uses `- [ ]` checkbox format. Spec sync task requirement names
  match source spec headers verbatim.

### 🟡 Addressed (applied in this round)
- Task 1.2 originally said to place `__slots__` as "the first line of the
  class body" — that would orphan the `"""Async queue message"""` docstring
  and set `UMessage.__doc__ = None`. **Fixed**: amended task 1.2 to place
  `__slots__` immediately **after** the docstring, with an inline note
  explaining why.

### 🔴 Outstanding
- None.

**Outcome**: batch **frozen**. All `applyRequires` artifacts (proposal, design,
specs, tasks) are now complete and frozen. Change is ready for `/opsx-apply`.
