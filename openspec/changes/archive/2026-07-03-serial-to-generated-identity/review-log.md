# Review Log — serial-to-generated-identity

## proposal Round 1 — 2026-07-03

Reviewer: @k-reviewer-fast (against the verified explore-session facts; no prior frozen artifacts).

### 🟡 Addressed (fixed in this round)
- **SCOPE — Impact omitted test files hardcoding `'004'`**: `tests/integration/test_allocated_node_id_migration.py:396-397` asserts `"last_migration CONSTANT TEXT := '004'" in schema`; `tests/integration/test_migrations.py` has tracker-seed assertions tied to `'004'` and synthetic migrations renumbered to avoid colliding with real `004_*`. Added an explicit Tests bullet listing all affected files/assertions and the renumbering review.
- **RISK — PG version constraint**: `ALTER COLUMN ... ADD GENERATED AS IDENTITY` on an existing column requires PG12+; the repo's de-facto floor is PG16 (testcontainer `postgres:16-alpine`) but no floor is declared. Added the constraint to the migration bullet and the Migration risk section, deferring the resolution (declare PG≥12 vs. alternative migration approach) to design.
- **PRECISION — `setval` vs identity-column seeding**: after `ADD GENERATED ALWAYS AS IDENTITY`, the column is backed by a new implicit identity sequence; the canonical seed is `ALTER COLUMN ... RESTART WITH <val>`, not `setval`. Rephrased "setval above MAX" → "restart the identity sequence above current `MAX`" and noted `RESTART WITH` in the Migration risk.

### 🔴 Outstanding
_(none — no blocking issues found)_

### Verdict
APPROVE WITH NOTES. No 🔴 issues; three 🟡 addressed. Proposal is maximally short per user instruction, correctly scopes the single modified capability (`postgres-schema-apply`), and is internally consistent.

## design+specs Round 1 — 2026-07-03

Reviewer: @k-reviewer-fast (against frozen `proposal.md`).

### 🟢 Addressed (fixed this round)
- **design.md D3 — "old SERIAL sequence dropped automatically" imprecise**: `DROP DEFAULT` does not drop the sequence or clear its `OWNED BY`; the old SERIAL sequence persists as orphaned but irrelevant (the new identity sequence handles inserts; `pg_get_serial_sequence` reports the identity sequence). Rephrased the rationale. Also tightened the D3 self-correction presentation so the final form is unambiguously the canonical block and the discarded `DROP NOT NULL` draft is explicitly labeled.

### 🟡 Observations (no change requested)
- **design.md D3 self-correction readability**: the narrative presents a flawed draft then corrects it — kept as educational but the final form is now explicitly canonical.
- **delta spec scenario lists `allocated_node_id`/`node_id`**: these were absent from the original spec scenario (already outdated by migrations 002/004); cleaning up the inaccuracy in the MODIFIED block is reasonable, not scope creep.

### 🔴 Outstanding
_(none)_

### Verdict
APPROVE WITH NOTES. No 🔴 issues; one 🟢 accuracy nit fixed; two 🟡 observations noted. design.md and specs/postgres-schema-apply/spec.md are consistent with the frozen proposal, decision sound, delta spec well-formed (exact requirement-name matches, full blocks copied, 4-hashtag scenarios, WHEN/THEN). Batch frozen.

## tasks Round 1 — 2026-07-03

Reviewer: @k-reviewer-fast (against frozen proposal + design + specs).

### 🟡 Addressed (fixed this round)
- **Task 4.2 stale line numbers**: cited `L224 ["003","004"]`, `L367 ["004"]`, `L377 ["004"]` which don't match the current `test_migrations.py` (file has 373 lines; actual `'004'` assertions are spread across ~L125/L136/L180/L229/L269/L305/L355 and drift). Rephrased to "search all `'004'` occurrences" instead of brittle line numbers.

### Confirmation
All 6 proposal impact items covered (schema.sql snapshot ✓, migration 005 ✓, last_migration bump ✓, BUGS.md removal ✓, test assertions ✓, test_migration_runner auto-detect ✓). Migration form matches design D3 final. Synthetic-migration renumbering (`005_*`→`006_*`) correctly identified. New integration test feasible. GRACE check note accurate (SQL files ungoverned; `test_migrations.py` is governed so non-trivial). Checkbox format correct.

### 🔴 Outstanding
_(none)_

### Verdict
APPROVE WITH NOTES. No 🔴 issues; one 🟡 fixed. tasks.md is apply-ready. Change `serial-to-generated-identity` is complete and ready for `/opsx-apply`.