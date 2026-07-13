## ADDED Requirements

### Requirement: Migration 013 makes ncpus nullable with positive CHECK

Migration `013_ncpus_nullable.sql` SHALL make the `yascheduler_nodes.ncpus`
column's "no operator limit" representation honest by installing a positive-only
CHECK constraint and backfilling the legacy magic-`0` sentinel rows to `NULL`.
The column is already `SMALLINT DEFAULT NULL` (migration 012 / `schema.sql`), so
no type change is needed — only the constraint and the backfill.

The migration SHALL execute, in order:

1. `UPDATE yascheduler_nodes SET ncpus = NULL WHERE ncpus = 0`
2. `ALTER TABLE yascheduler_nodes ADD CONSTRAINT node_ncpus_positive CHECK (ncpus IS NULL OR ncpus > 0)`

The backfill runs FIRST because PostgreSQL's `ALTER TABLE ... ADD CONSTRAINT
... CHECK` validates all existing rows against the new constraint by default.
Running the ADD CONSTRAINT first would fail on any pre-migration row with
`ncpus = 0` (the legacy sentinel). Backfilling those rows to `NULL` first makes
the constraint application safe on databases with existing zero-valued rows.

The backfill targets ONLY rows with `ncpus = 0` (the legacy magic sentinel
meaning "unknown / discover at spawn"). Existing `NULL` rows (already
semantically "unknown") and `> 0` rows (operator-set static config OR
previously cloud-cached discovered values) SHALL be left untouched. A
previously cloud-cached `8` becomes, post-migration, semantically
"operator-set static config" — a correct conservative reading (a cached `8`
behaves identically to a configured `8`: used directly, no per-spawn
discovery). New cloud nodes created after this change store `NULL` and
discover at spawn via the session cache.

The `node_ncpus_positive` CHECK constraint mirrors the `node_port_range` /
`node_jump_port_range` pattern from migration 012: a named table-level CHECK
guarding a column's valid value domain. The `LATEST_MIGRATION` constant in the
migrations module SHALL be bumped from `'012'` to `'013'`.

The migration is **forward-only** (no down-script). Rollback safety: a
pre-migration binary reading a post-migration database sees `NULL` where it
expected `0`, but its `_row_to_node` `or 0` coalescence converts `NULL` back
to `0`, so the old binary keeps working — the sentinel round-trips. The
`node_ncpus_positive` CHECK is forward-compatible with the old binary (it only
forbids `0` and negatives, which the old binary never writes).

#### Scenario: Migration 013 installs the node_ncpus_positive CHECK
- **WHEN** migration `013_ncpus_nullable.sql` runs on a database whose `yascheduler_nodes.ncpus` has no `node_ncpus_positive` constraint
- **THEN** the `node_ncpus_positive` CHECK constraint is added, enforcing `(ncpus IS NULL OR ncpus > 0)`, and `"013"` is recorded in `yascheduler_migrations`

#### Scenario: Migration 013 backfills zero rows to NULL
- **WHEN** migration `013_ncpus_nullable.sql` runs on a database with rows `{ncpus=0}`, `{ncpus=8}`, `{ncpus=NULL}`
- **THEN** after the migration the rows are `{ncpus=NULL}`, `{ncpus=8}`, `{ncpus=NULL}` — only the `0` row changed; the `8` and the pre-existing `NULL` are untouched

#### Scenario: Migration 013 CHECK rejects future zero writes
- **WHEN** after migration `013` an `INSERT`/`UPDATE` attempts to store `ncpus=0` on `yascheduler_nodes`
- **THEN** the database rejects the write with a `node_ncpus_positive` CHECK violation

#### Scenario: Migration 013 CHECK rejects negative writes
- **WHEN** after migration `013` an `INSERT`/`UPDATE` attempts to store `ncpus=-1` on `yascheduler_nodes`
- **THEN** the database rejects the write with a `node_ncpus_positive` CHECK violation

#### Scenario: LATEST_MIGRATION constant bumped to 013
- **WHEN** the migrations module is inspected after this change
- **THEN** the `LATEST_MIGRATION` constant is `'013'` (was `'012'`)
