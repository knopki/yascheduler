## Why

The two PK columns (`yascheduler_nodes.node_id`, `yascheduler_tasks.task_id`) use `SERIAL`, a PostgreSQL-specific, non-standard legacy idiom. `GENERATED ALWAYS AS IDENTITY` (SQL:2003, PG10+) is the modern standard and additionally rejects explicit PK inserts — a future-bug guard the app currently lacks. The orphan note already in `docs/BUGS.md:53` flags this. No application code inserts PKs explicitly (verified: `task/insert.sql` omits `task_id`; no `INSERT INTO ... (node_id|task_id)` anywhere), so the transition is behavior-preserving for the app and `ALWAYS` is safe.

## What Changes

- `schema.sql` snapshot: `node_id SERIAL PRIMARY KEY` → `node_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`; same for `task_id`. Fresh DBs get the identity columns directly.
- New migration `005_serial_to_identity.sql`: converts existing `SERIAL` columns to `GENERATED ALWAYS AS IDENTITY` on legacy/intermediate DBs (drop default + owned sequence, add identity, restart the identity sequence above current `MAX`). Note: `ALTER COLUMN ... ADD GENERATED AS IDENTITY` on an existing column requires PostgreSQL 12+; the repo's de-facto floor is PG16 (testcontainer `postgres:16-alpine`), but no explicit floor is declared — design must either declare PG≥12 as part of this change or pick a migration approach valid on PG10-11.
- `schema.sql` DO block: `last_migration` CONSTANT `'004'` → `'005'`.
- `docs/BUGS.md`: remove the orphan note at L53 (captured by this change).
- Existing tests hardcoding `'004'`: `tests/integration/test_allocated_node_id_migration.py:396-397` asserts `"last_migration CONSTANT TEXT := '004'" in schema`; `tests/integration/test_migrations.py` has tracker-seed assertions tied to `'004'` (L24, L224, L367, L377) and synthetic migration files renumbered to avoid colliding with real `004_*`. Bumping to `'005'` requires updating these assertions and re-checking the synthetic-migration renumbering.

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `postgres-schema-apply`: snapshot DDL for `yascheduler_nodes.node_id` and `yascheduler_tasks.task_id` changes from `SERIAL PRIMARY KEY` to `INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`; `last_migration` CONSTANT bumped to `'005'`.

## Impact

- **Code**: `yascheduler/infra/persistence/sql/schema.sql` (snapshot DDL + `last_migration` constant), new `yascheduler/infra/persistence/sql/migrations/005_serial_to_identity.sql`, `docs/BUGS.md` (orphan note removal).
- **Tests**: `tests/integration/test_allocated_node_id_migration.py` (L396-397 `'004'` assertion → `'005'`), `tests/integration/test_migrations.py` (tracker-seed assertions L24/L224/L367/L377 + synthetic-migration renumbering review), unit test `tests/unit/test_migration_runner.py` (auto-detects constant drift; should pass unchanged once `last_migration` and the latest migration file agree on `'005'`).
- **No app/runtime behavior change**: repositories never insert PKs explicitly; `RETURNING node_id`/`RETURNING task_id` reads are unaffected (identity columns are still `int`, wrapped unchanged by `NodeId`/`TaskId`).
- **No CLI / public-API / config / domain change**.
- **Migration risk**: (a) legacy/intermediate DBs with populated `SERIAL` sequences require the new identity sequence to be seeded above current `MAX` (`ALTER COLUMN ... RESTART WITH`) to avoid PK conflicts; (b) the `ALTER COLUMN ... ADD GENERATED AS IDENTITY` syntax requires PG12+ — design must resolve the PG version floor. Fresh DBs are unaffected.