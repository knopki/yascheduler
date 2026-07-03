## 1. Migration 005

- [x] 1.1 Create `yascheduler/infra/persistence/sql/migrations/005_serial_to_identity.sql` with, for `yascheduler_tasks.task_id` and `yascheduler_nodes.node_id` (final form from design.md D3, corrected after empirical testing): `ALTER TABLE <t> ALTER COLUMN <c> DROP DEFAULT;` then `ALTER SEQUENCE <t>_<c>_seq OWNED BY NONE; DROP SEQUENCE <t>_<c>_seq;` (disown+drop the old SERIAL sequence so `ADD IDENTITY` reuses the canonical name); then `ALTER TABLE <t> ALTER COLUMN <c> ADD GENERATED ALWAYS AS IDENTITY;` then `SELECT setval(pg_get_serial_sequence('<t>', '<c>'), (SELECT COALESCE(MAX(<c>), 0) FROM <t>) + 1, false);`. Two statement groups total (one per table).
- [x] 1.2 Verify migration 005 is NOT idempotent (db-migrations spec L88-90 does not require idempotency; the tracker guards re-application). Confirm no `IF NOT EXISTS`/`IF EXISTS` guards are needed.

## 2. schema.sql snapshot

- [x] 2.1 In `yascheduler/infra/persistence/sql/schema.sql` DO block, change `last_migration CONSTANT TEXT := '004'` → `'005'`.
- [x] 2.2 In `yascheduler/infra/persistence/sql/schema.sql` `CREATE TABLE IF NOT EXISTS yascheduler_nodes`, change `node_id SERIAL PRIMARY KEY` → `node_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`.
- [x] 2.3 In `yascheduler/infra/persistence/sql/schema.sql` `CREATE TABLE IF NOT EXISTS yascheduler_tasks`, change `task_id SERIAL PRIMARY KEY` → `task_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`.
- [x] 2.4 Confirm `tests/unit/test_migration_runner.py` `test_schema_sql_last_migration_constant_matches_latest_migration` passes unchanged after the constant bump (it auto-detects drift; `'005'` must equal the max prefix_id in `migrations/`, which is now `005_serial_to_identity.sql`).

## 3. docs/BUGS.md

- [x] 3.1 Remove the orphan note at `docs/BUGS.md:53` (the dangling `GENERATED AS IDENTITY` line after H6).

## 4. Tests — update hardcoded `'004'` assertions

- [x] 4.1 In `tests/integration/test_allocated_node_id_migration.py:396-397`, change the assertion `"last_migration CONSTANT TEXT := '004'" in schema` → `"'005'"`.
- [x] 4.2 In `tests/integration/test_migrations.py`, update all tracker-seed assertions that reference `'004'` to `'005'` (search the file for every `'004'` occurrence in assertion/expected-list contexts — there are multiple, and exact line numbers drift; the current ones are around the `_tracker_rows(conn) == [...]` assertions and the LAST_CHANGE/PREVIOUS_CHANGE comments near the top). Update the L24/L25 LAST_CHANGE/PREVIOUS_CHANGE comments to record the bump (`'004'`→`'005'`, synthetic renumber `005_*`→`006_*`).
- [x] 4.3 In `tests/integration/test_migrations.py`, renumber the synthetic migration files `005_reopen.py` (L250) and `005_fail.sql` (L288) to `006_*` to avoid colliding with the real `005_serial_to_identity.sql`. Update any assertions that reference these synthetic names (search `005_reopen`/`005_fail` in the file). Confirm the synthetic migrations remain higher-prefix than the real ones so the pending-path tests still exercise the intended branches.
- [x] 4.4 Add a new integration test `test_migration_005_converts_serial_to_identity`: on a fresh testcontainer, manually `CREATE TABLE yascheduler_nodes (node_id SERIAL PRIMARY KEY, ...)` and `yascheduler_tasks (task_id SERIAL PRIMARY KEY, ...)` with the pre-005 column shape, insert a row with an explicit `node_id`/`task_id` value (e.g. via `INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.1')` letting SERIAL assign, then note the assigned id), seed `yascheduler_migrations` to `'004'`, run `apply_schema` + `apply_migrations`, assert: (a) the columns are now `GENERATED ALWAYS AS IDENTITY` (query `pg_attribute`/`pg_get_serial_sequence` or `information_schema.columns` where `is_identity = 'YES'` and `identity_generation = 'ALWAYS'`), (b) the identity sequence next value > the previously inserted id (no PK collision on the next insert), (c) a subsequent `INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.2')` succeeds and auto-assigns a unique id.
- [x] 4.5 Add a unit test `test_schema_sql_uses_identity_not_serial`: assert `schema.sql` contains `GENERATED ALWAYS AS IDENTITY` for both PK columns and does NOT contain `SERIAL PRIMARY KEY`.

## 5. Verification

- [x] 5.1 `uv run pytest -m unit` passes (including the new `test_schema_sql_uses_identity_not_serial` and the auto-detecting `test_migration_runner.py`).
- [x] 5.2 `uv run pytest -m integration` passes (including the updated `test_allocated_node_id_migration.py`, the renumbered `test_migrations.py`, and the new `test_migration_005_converts_serial_to_identity`).
- [x] 5.3 `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` pass (no code change beyond SQL/tests/BUGS.md, so these should be unaffected — run to confirm).
- [x] 5.4 `openspec validate --all --json` passes (specs delta is well-formed).
- [x] 5.5 `python3 scripts/grace_check.py` passes (no source module touched; if the migration file or schema.sql are under GRACE governance, ensure their MODULE_CONTRACT/anchors are unchanged or updated as needed — they are SQL data files, likely outside GRACE scope, but verify).