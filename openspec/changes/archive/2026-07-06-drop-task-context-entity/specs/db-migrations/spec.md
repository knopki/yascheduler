# Spec Delta: db-migrations

## ADDED Requirements

### Requirement: Migration 010 extracts metadata into typed columns and extra JSONB

The system SHALL provide a migration `010_extract_metadata_columns.sql` that
extracts the seven typed keys out of the `metadata` JSONB column into typed
columns, routes the remainder into a new `extra` JSONB column, applies NOT NULL
constraints and defaults, and drops `metadata`. The migration SHALL:

1. `ALTER TABLE yascheduler_tasks ADD COLUMN engine VARCHAR(64);`
2. `ALTER TABLE yascheduler_tasks ADD COLUMN remote_folder VARCHAR(1024);`
3. `ALTER TABLE yascheduler_tasks ADD COLUMN local_folder VARCHAR(1024);`
4. `ALTER TABLE yascheduler_tasks ADD COLUMN webhook_url VARCHAR(2048);`
5. `ALTER TABLE yascheduler_tasks ADD COLUMN error TEXT;`
6. `ALTER TABLE yascheduler_tasks ADD COLUMN webhook_custom_params JSONB;`
7. `ALTER TABLE yascheduler_tasks ADD COLUMN extra JSONB;`
8. `UPDATE yascheduler_tasks SET engine = COALESCE(metadata->>'engine', ''),
   remote_folder = metadata->>'remote_folder',
   local_folder = metadata->>'local_folder',
   webhook_url = metadata->>'webhook_url',
   error = metadata->>'error',
   webhook_custom_params = COALESCE(metadata->'webhook_custom_params',
   '{}'::jsonb), extra = COALESCE(metadata - 'engine' - 'remote_folder' -
   'local_folder' - 'webhook_url' - 'error' - 'webhook_custom_params',
   '{}'::jsonb);`
9. `ALTER TABLE yascheduler_tasks ALTER COLUMN engine SET NOT NULL;`
10. `ALTER TABLE yascheduler_tasks ALTER COLUMN webhook_custom_params SET
    NOT NULL;`
11. `ALTER TABLE yascheduler_tasks ALTER COLUMN webhook_custom_params SET
    DEFAULT '{}'::jsonb;`
12. `ALTER TABLE yascheduler_tasks ALTER COLUMN extra SET NOT NULL;`
13. `ALTER TABLE yascheduler_tasks ALTER COLUMN extra SET DEFAULT
    '{}'::jsonb;`
14. `ALTER TABLE yascheduler_tasks DROP COLUMN metadata;`

Extraction type rules:
- `->>` (text extraction) for the five string columns (`engine`, `remote_folder`,
  `local_folder`, `webhook_url`, `error`) — yields `text`, assignable to
  `VARCHAR(n)` / `TEXT`.
- `->` (arrow, JSONB extraction) for `webhook_custom_params` and the `extra`
  computation — preserves JSONB type. `COALESCE(..., '{}'::jsonb)` handles a
  missing key (NULL JSONB) by substituting the empty object.
- `engine = COALESCE(metadata->>'engine', '')` — a missing `engine` defaults to
  the empty string (matches the domain `from_metadata` coercion
  `str(metadata.get("engine", ""))`); legacy rows with `engine=""` are
  acceptable (the column is NOT NULL but `''` is a valid non-null string).
- `extra = COALESCE(metadata - <six known keys>, '{}'::jsonb)` — the `metadata -
  'k1' - 'k2' - ...` operator subtracts the six known keys from the JSONB object,
  leaving whatever remains (input-file payloads, any future extras). `COALESCE`
  handles the `metadata IS NULL` edge case defensively (should not occur
  post-009, but defensive).

NOT NULL and DEFAULT are applied AFTER the backfill UPDATE so the UPDATE can
populate all rows first; applying NOT NULL before backfill would fail on the
NULL values in not-yet-populated rows. The DEFAULTs on
`webhook_custom_params` and `extra` are set as a DB-level safety net for future
inserts that omit those columns (the domain layer always supplies explicit
values, but the DB-level default is the safety net).

`error` values in existing rows (legacy `str(dict)` format from the old
download path, e.g. `"{'/remote/1.out': 'No such file'}"`) are passed through
verbatim by `metadata->>'error'` extraction — the migration does NOT reformat
existing rows. Only new writes follow the error column format contract (see
the `domain-entities` delta).

The migration runs in its own transaction; on failure it rolls back and the DB
is unchanged (the columns are added but `metadata` is not yet dropped).
`schema.sql` is updated to reflect the post-010 column set, and the
`last_migration` CONSTANT is bumped from `'009'` to `'010'`.

#### Scenario: Migration 010 adds and backfills typed columns
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `009` on a row with `metadata = {"engine": "cp2k", "local_folder": "/l", "webhook_custom_params": {"parent": 42}, "input.in": "ATOMS ..."}`
- **THEN** the row gains `engine='cp2k'`, `remote_folder=NULL`, `local_folder='/l'`, `webhook_url=NULL`, `error=NULL`, `webhook_custom_params='{"parent": 42}'::jsonb`, `extra='{"input.in": "ATOMS ..."}'::jsonb`, and the `metadata` column is dropped

#### Scenario: Migration 010 defaults missing engine to empty string
- **WHEN** `apply_migrations(config)` runs on a row with `metadata = {"local_folder": "/l"}` (no `engine` key)
- **THEN** the row gains `engine=''` (via `COALESCE(metadata->>'engine', '')`), the NOT NULL constraint passes (`''` is non-null), and the migration succeeds

#### Scenario: Migration 010 routes input-file payloads to extra
- **WHEN** `apply_migrations(config)` runs on a row with `metadata = {"engine": "cp2k", "input.in": "ATOMS", "input.xyz": "XYZ"}`
- **THEN** the row gains `extra='{"input.in": "ATOMS", "input.xyz": "XYZ"}'::jsonb` (the six known keys are subtracted; the input-file payloads remain)

#### Scenario: Migration 010 handles metadata with only known keys
- **WHEN** `apply_migrations(config)` runs on a row with `metadata = {"engine": "cp2k", "remote_folder": "/r"}`
- **THEN** the row gains `extra='{}'::jsonb` (subtracting all known keys from a metadata containing only known keys yields an empty object, which `COALESCE` returns as `'{}'::jsonb`)

#### Scenario: Migration 010 preserves legacy error format verbatim
- **WHEN** `apply_migrations(config)` runs on a row with `metadata = {"error": "{'/remote/1.out': 'No such file'}"}`
- **THEN** the row gains `error="{'/remote/1.out': 'No such file'}"` (verbatim `metadata->>'error'` passthrough; NOT reformatted to the new `"Download error: ..."` contract)

#### Scenario: Migration 010 is idempotent-safe via tracker
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `010` or higher
- **THEN** migration `010_extract_metadata_columns.sql` is NOT re-applied (the tracker filters it out)

#### Scenario: Migration 010 failure rolls back
- **WHEN** `apply_migrations(config)` runs `010_extract_metadata_columns.sql` and a statement raises (e.g. a NOT NULL violation on a backfill that missed a row)
- **THEN** the migration transaction rolls back, `010` is NOT recorded in `yascheduler_migrations`, and the DB is unchanged (the added columns may persist if the ALTERs committed before the failing statement, but `metadata` is not dropped)

## MODIFIED Requirements

### Requirement: Migrations 006 through 009 are ordered and transactional

The system SHALL apply the five migrations (`006_rename_label_to_title.sql`,
`007_add_created_updated_at.sql`, `008_status_to_enum.sql`,
`009_drop_allocated_ip.sql`, `010_extract_metadata_columns.sql`) in
string-sorted filename order (006 before 007 before 008 before 009 before 010),
each in its own transaction (per the "Migration runner applies pending
migrations sequentially" requirement). The ordering MUST be chosen so that
additive and rename migrations (006, 007) run first, the data-transform
migration (008) runs next, the destructive column-drop migration (009) runs
after the API break is settled, and the metadata-extraction migration (010)
runs last (it requires the post-009 schema: `title`, `task_status` enum,
`created_at`/`updated_at`, no `ip`). A legacy database at migration `005` SHALL
advance to `010` by running all five in order; a fresh database initialized
from `schema.sql` (seeded to `last_migration = '010'`) SHALL skip all five.
Each migration MUST be its own transaction so a failure of one does not roll
back previously-committed migrations.

#### Scenario: Legacy database at 005 runs all five migrations
- **WHEN** `apply_migrations(config)` runs on a database with `MAX(migration_id) = '005'`
- **THEN** migrations 006, 007, 008, 009, 010 are applied in order, each in its own transaction, and the tracker records all five

#### Scenario: Legacy database at 009 runs only migration 010
- **WHEN** `apply_migrations(config)` runs on a database with `MAX(migration_id) = '009'`
- **THEN** only migration `010_extract_metadata_columns.sql` is applied, and `010` is recorded in `yascheduler_migrations`

#### Scenario: Fresh database skips all five migrations
- **WHEN** `apply_schema(config)` runs on a fresh database and seeds `yascheduler_migrations` with `last_migration = '010'`
- **THEN** subsequent `apply_migrations(config)` finds `MAX(migration_id) = '010'` and applies no pending migrations (all five are already applied via schema.sql)

#### Scenario: Tracker records applied prefix ids
- **WHEN** `apply_migrations(config)` applies a sequence of migrations with prefix ids `L+1` through `010`
- **THEN** only migration files whose `prefix_id > L` are applied, in string-sorted order

#### Scenario: Tracker absent is treated defensively as apply-all
- **WHEN** `apply_migrations(config)` is called on a database where `yascheduler_migrations` does not exist
- **THEN** the function treats the tracker as empty (last applied id = NULL) and applies all migrations, rather than raising. This is a defensive path: the tracker is normally created by `apply_schema`'s DO block, and `apply_migrations` is only called after `apply_schema`; the defensive behavior keeps the runner from crashing if that ordering is ever violated

#### Scenario: Each migration runs in its own transaction
- **WHEN** `apply_migrations(config)` applies a sequence of migrations
- **THEN** each migration is wrapped in its own `BEGIN/COMMIT`; the success or failure of one migration does not affect the transaction state of the next