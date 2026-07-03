## Context

`schema.sql` defines two `SERIAL PRIMARY KEY` columns:
- `yascheduler_nodes.node_id` (`schema.sql:25`; added to legacy DBs by migration `002_add_node_id.sql` via `ALTER TABLE ... ADD COLUMN node_id SERIAL PRIMARY KEY`)
- `yascheduler_tasks.task_id` (`schema.sql:35`)

`SERIAL` is PostgreSQL-specific, creates a loose sequence (`<table>_<col>_seq`) not bound to the column, and silently accepts explicit PK inserts. `GENERATED ALWAYS AS IDENTITY` (SQL:2003, PG10+) is the standard idiom and binds the sequence to the column; `ALWAYS` additionally rejects explicit inserts without `OVERRIDING SYSTEM VALUE`.

The application never inserts PKs explicitly (verified: `task/insert.sql` omits `task_id`; no `INSERT INTO ... (node_id|task_id)` anywhere; even tests omit PKs). `RETURNING node_id`/`RETURNING task_id` reads are unaffected — identity columns are still `INTEGER`. `NodeId`/`TaskId` wrap `int(row[...])` unchanged.

The repo has no declared PG version floor, but the integration testcontainer is `postgres:16-alpine` (archived `2026-05-23-test-integration-db`), so PG≥16 is the de-facto floor. `ALTER COLUMN ... ADD GENERATED AS IDENTITY` on an existing column requires PG12+; satisfied.

Three DB cohorts converge via the migration edit procedure (db-migrations spec L190-206):
- **Fresh** DB: snapshot has identity columns; seeded to `'005'`; migration 005 skipped.
- **Legacy** DB (has `yascheduler_nodes`, tracker empty): snapshot is a `CREATE TABLE IF NOT EXISTS` no-op; migration 005 converts SERIAL→identity via `ALTER`.
- **Modern** DB (tracker at `'004'`): runs only migration 005.

## Goals / Non-Goals

**Goals:**
- Snapshot DDL uses `GENERATED ALWAYS AS IDENTITY` for both PKs.
- Legacy/intermediate DBs convert via a forward-only migration that preserves existing PK values and seeds the new identity sequence above current `MAX`.
- `ALWAYS` rejects future explicit-PK-insert bugs.
- `docs/BUGS.md` orphan note removed.

**Non-Goals:**
- Switching ip-keyed mutators (`WHERE ip =`) to `WHERE node_id =` (deferred per `add-node-id-identity` design L57-60).
- Declaring a repo-wide PG version floor beyond what this migration needs (PG12+ is implicit in the migration; formalizing it is a separate concern).
- Touching `allocated_node_id` FK definition, sequence names elsewhere, or any domain/CLI code.
- Backfilling or re-numbering existing rows.

## Decisions

### D1: `GENERATED ALWAYS` (not `BY DEFAULT`)
**Choice:** `ALWAYS`.
**Rationale:** The app never inserts PKs explicitly; `ALWAYS` adds a real guard (rejects explicit inserts without `OVERRIDING SYSTEM VALUE`) that `BY DEFAULT` (== SERIAL semantics) and `SERIAL` both lack. This is the only non-cosmetic benefit of the transition; choosing `BY DEFAULT` would forfeit it.
**Alternatives:** `BY DEFAULT` — behaviorally identical to SERIAL for this app, zero guard. Rejected.

### D2: Declare PG≥12 as the floor for this migration (not a repo-wide floor)
**Choice:** The migration 005 uses `ALTER COLUMN ... ADD GENERATED ALWAYS AS IDENTITY`, which requires PG12+. The repo's de-facto floor is PG16 (testcontainer), so this is satisfied. We do NOT formally declare a repo-wide PG version floor in a spec — we note that migration 005 requires PG12+ and rely on the existing testcontainer (PG16) to validate.
**Rationale:** Formalizing a floor is a separate cross-cutting concern; this change only needs the migration to run on the supported target. The testcontainer already proves PG16 works.
**Alternatives:** (a) Table-recreation approach valid on PG10-11 — rejected: more complex, more downtime, and no PG10-11 target exists. (b) Declare a repo-wide PG≥12 floor in `postgres-schema-apply` spec — rejected: scope creep.
### D3: Migration 005 mechanics

**Choice:** For each of `yascheduler_tasks.task_id` and `yascheduler_nodes.node_id` (final form, verified empirically against `postgres:16-alpine`):
```sql
ALTER TABLE yascheduler_tasks
    ALTER COLUMN task_id DROP DEFAULT;
ALTER SEQUENCE yascheduler_tasks_task_id_seq OWNED BY NONE;
DROP SEQUENCE yascheduler_tasks_task_id_seq;
ALTER TABLE yascheduler_tasks
    ALTER COLUMN task_id ADD GENERATED ALWAYS AS IDENTITY;
SELECT setval(pg_get_serial_sequence('yascheduler_tasks', 'task_id'),
               (SELECT COALESCE(MAX(task_id), 0) FROM yascheduler_tasks) + 1,
               false);
```
**Rationale:** `DROP DEFAULT` removes the `nextval(seq)` default that SERIAL installed. The old SERIAL sequence (`<table>_<col>_seq`) is still `OWNED BY` the column after `DROP DEFAULT`; if it is left in place, `ADD GENERATED ALWAYS AS IDENTITY` creates a NEW sequence with a different name (e.g. `<table>_<col>_seq1`) and `pg_get_serial_sequence` keeps returning the old, now-unused sequence — so a subsequent `setval` would seed the wrong sequence and the next insert collides with existing rows (verified: duplicate-key violation). Disowning and dropping the old sequence first lets `ADD GENERATED ALWAYS AS IDENTITY` create a fresh identity sequence reusing the canonical `<table>_<col>_seq` name, which `pg_get_serial_sequence` then reports correctly. `setval(..., MAX+1, false)` sets the sequence so the next `nextval` returns `MAX+1` (the `false` flag means "the value just set is not the last returned; next call returns this value").
**Alternatives:** `ALTER COLUMN ... RESTART WITH <expr>` — rejected: `RESTART` accepts only an integer literal, not an expression; we need `MAX+1` which is dynamic. So `setval` after `ADD IDENTITY` is the correct pattern. `ADD GENERATED ALWAYS AS IDENTITY (SEQUENCE NAME <existing>)` to reuse the old sequence — rejected: PostgreSQL tries to CREATE the named sequence and fails with `relation already exists` (verified empirically).
**Correction note:** An earlier draft of this section (frozen then unfrozen during implementation) omitted the `ALTER SEQUENCE ... OWNED BY NONE; DROP SEQUENCE ...;` steps and claimed the old SERIAL sequence "persists as an orphaned sequence but is irrelevant". Empirical testing on PG16 proved this false: the old sequence name collides with the new identity sequence name, `pg_get_serial_sequence` returns the wrong sequence, and `setval` seeds the wrong one — the next insert collides. The disown+drop steps are mandatory.
**Edge case:** On a fresh DB, migration 005 is skipped (seeded to `'005'`), so the `setval` never runs there — fresh DBs get identity via the snapshot. On an empty legacy DB (`MAX` is NULL), `COALESCE(MAX, 0)+1 = 1`, `setval(..., 1, false)` — first insert gets id 1. Correct.

### D4: Snapshot DDL form
**Choice:**
```sql
node_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
task_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
```
**Rationale:** `INTEGER` (not `INT`) matches the existing migration 004 style (`allocated_node_id INTEGER REFERENCES ...`). `PRIMARY KEY` stays inline (no separate constraint name). Fresh DBs get identity directly.

## Risks / Trade-offs

- **[Risk] Legacy DB with a populated SERIAL sequence whose `lastval` > `MAX(id)` (e.g. a failed insert consumed a value)** → `setval(MAX+1, false)` resets below the sequence's current position. **Mitigation:** This is the desired behavior — the identity sequence starts at `MAX+1`, guaranteeing no collision with existing rows. Any "gaps" in the old sequence are discarded, which is acceptable (gaps are not a correctness property).
- **[Risk] The old SERIAL sequence is referenced by a dependent object** → verified: no code references `_task_id_seq`/`_node_id_seq`, no `nextval`/`currval`/`setval` elsewhere. Safe.
- **[Risk] `ALTER ... ADD GENERATED AS IDENTITY` fails on PG10-11** → mitigated by D2 (testcontainer is PG16); no PG10-11 target exists.
- **[Trade-off] Existing rows keep their SERIAL-assigned ids; new inserts get identity-assigned ids starting at `MAX+1`.** No renumbering; no data movement. Acceptable.
- **[Trade-off] `ALWAYS` breaks any future code that inserts PKs explicitly.** This is the intended guard; the failure is loud (a clear PG error), not silent. Acceptable and desirable.