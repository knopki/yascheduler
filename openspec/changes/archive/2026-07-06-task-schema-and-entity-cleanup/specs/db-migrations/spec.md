# Delta: db-migrations

## ADDED Requirements

### Requirement: Migration 006 renames label column to title

The system SHALL provide a migration `006_rename_label_to_title.sql` that
executes `ALTER TABLE yascheduler_tasks RENAME COLUMN label TO title;`. The
migration SHALL be a single SQL statement in its own transaction. `title` is
a non-reserved PostgreSQL keyword and is valid as a column name without
quoting. The domain field `Task.label` and the JSON/dict key `"label"` are
unchanged — only the database column is renamed.

#### Scenario: Migration 006 renames the column
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `005`
- **THEN** the migration `006_rename_label_to_title.sql` is applied, executing `ALTER TABLE yascheduler_tasks RENAME COLUMN label TO title;`, and `006` is recorded in `yascheduler_migrations`

#### Scenario: Migration 006 is idempotent-safe via tracker
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `006` or higher
- **THEN** migration `006_rename_label_to_title.sql` is NOT re-applied (the tracker filters it out)

### Requirement: Migration 007 adds created_at and updated_at with a trigger

The system SHALL provide a migration `007_add_created_updated_at.sql` that
adds two columns and installs a trigger function plus trigger. The migration
SHALL:

1. `ALTER TABLE yascheduler_tasks ADD COLUMN IF NOT EXISTS created_at
   TIMESTAMPTZ NOT NULL DEFAULT NOW();`
2. `ALTER TABLE yascheduler_tasks ADD COLUMN IF NOT EXISTS updated_at
   TIMESTAMPTZ NOT NULL DEFAULT NOW();`
3. `CREATE OR REPLACE FUNCTION yascheduler_touch_updated_at() RETURNS trigger
   AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;`
4. `DROP TRIGGER IF EXISTS yascheduler_tasks_touch_updated_at ON
   yascheduler_tasks;`
5. `CREATE TRIGGER yascheduler_tasks_touch_updated_at BEFORE UPDATE ON
   yascheduler_tasks FOR EACH ROW EXECUTE FUNCTION
   yascheduler_touch_updated_at();`

The trigger function sets `NEW.updated_at = NOW()` on every `UPDATE` (there is
no MySQL-style `ON UPDATE` clause in PostgreSQL; a trigger is the standard
mechanism). `created_at` has `DEFAULT NOW()` and is not touched by the trigger
(inserts populate it via the default; updates never change it). `updated_at`
also has `DEFAULT NOW()` so inserts populate it without the trigger (the
trigger only fires on `UPDATE`). The `CREATE OR REPLACE FUNCTION` and
`DROP TRIGGER IF EXISTS` make the migration re-runnable in manual/admin
contexts (the tracker normally prevents re-runs).

#### Scenario: Migration 007 adds columns and trigger
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `006`
- **THEN** `created_at` and `updated_at` columns are added to `yascheduler_tasks` (both `TIMESTAMPTZ NOT NULL DEFAULT NOW()`), the function `yascheduler_touch_updated_at()` is created, and the trigger `yascheduler_tasks_touch_updated_at` is installed as `BEFORE UPDATE ... FOR EACH ROW`

#### Scenario: Trigger sets updated_at on UPDATE
- **WHEN** an `UPDATE` statement modifies a row in `yascheduler_tasks`
- **THEN** the `BEFORE UPDATE` trigger fires and sets `updated_at = NOW()` on the row, regardless of whether the application explicitly set `updated_at`

#### Scenario: created_at is not changed by UPDATE
- **WHEN** an `UPDATE` statement modifies a row in `yascheduler_tasks`
- **THEN** the `created_at` column retains its original value (the trigger only sets `updated_at`)

#### Scenario: Insert populates both timestamps via DEFAULT
- **WHEN** an `INSERT` statement omits `created_at` and `updated_at`
- **THEN** both columns are populated by `DEFAULT NOW()` (the trigger does not fire on INSERT)

### Requirement: Migration 008 converts status to a PostgreSQL enum

The system SHALL provide a migration `008_status_to_enum.sql` that creates a
PostgreSQL enum type and converts the `status` column from `SMALLINT` to the
enum. The migration SHALL:

1. `CREATE TYPE task_status AS ENUM ('TO_DO', 'RUNNING', 'DONE');`
2. `ALTER TABLE yascheduler_tasks ALTER COLUMN status TYPE task_status USING
   CASE status WHEN 0 THEN 'TO_DO' WHEN 1 THEN 'RUNNING' WHEN 2 THEN 'DONE' END;`
3. `ALTER TABLE yascheduler_tasks ALTER COLUMN status SET DEFAULT 'TO_DO';`

The `USING CASE` clause maps the existing integer values (0/1/2) to the enum
labels. Any out-of-range integer (e.g. 3) maps to NULL, which violates the
`NOT NULL` constraint and fails the migration (this is desirable — a corrupt
row surfaces early). The migration runs in its own transaction; on failure it
rolls back and the DB is unchanged. The default is updated to the enum label
`'TO_DO'` (was the int `0`). The Python `TaskStatus` remains an `IntEnum`
(`TO_DO=0, RUNNING=1, DONE=2`); the database now stores the enum label string,
and the persistence layer writes `task.status.name` and reads
`TaskStatus[row["status"]]` (see the `postgres-persistence` capability).

#### Scenario: Migration 008 creates the enum and converts the column
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `007`
- **THEN** the `task_status` enum type is created with labels `'TO_DO'`, `'RUNNING'`, `'DONE'`, and the `status` column is converted from `SMALLINT` to `task_status` via the `USING CASE` mapping (0→'TO_DO', 1→'RUNNING', 2→'DONE')

#### Scenario: Migration 008 fails on out-of-range status
- **WHEN** a row in `yascheduler_tasks` has `status = 3` (an out-of-range integer)
- **THEN** the `USING CASE` maps it to NULL, the `NOT NULL` constraint is violated, the migration fails, the transaction rolls back, and the DB is unchanged (column remains `SMALLINT`)

#### Scenario: Enum default is TO_DO after migration
- **WHEN** a new row is inserted into `yascheduler_tasks` without specifying `status`
- **THEN** the `status` column defaults to `'TO_DO'` (the enum label, was the int `0`)

### Requirement: Migration 009 drops the allocated_ip column

The system SHALL provide a migration `009_drop_allocated_ip.sql` that executes
`ALTER TABLE yascheduler_tasks DROP COLUMN IF EXISTS ip;`. The `ip` column (the
database column name for the domain `allocated_ip` field) is removed; the
`allocated_node_id` foreign key is the sole allocation signal. This is the
destructive, API-breaking migration and is ordered LAST (after the
additive/rename/transform migrations) so a rollback of the API break can
re-add the column without losing the enum/title/timestamp work.

#### Scenario: Migration 009 drops the column
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `008`
- **THEN** the `ip` column is dropped from `yascheduler_tasks`, and `009` is recorded in `yascheduler_migrations`

#### Scenario: Migration 009 is idempotent via IF EXISTS
- **WHEN** `apply_migrations(config)` runs and the `ip` column was already dropped (e.g. a manual admin drop)
- **THEN** `DROP COLUMN IF EXISTS ip` is a no-op and the migration succeeds

### Requirement: Migrations 006 through 009 are ordered and transactional

The system SHALL apply the four migrations (`006_rename_label_to_title.sql`,
`007_add_created_updated_at.sql`, `008_status_to_enum.sql`,
`009_drop_allocated_ip.sql`) in string-sorted filename order (006 before 007
before 008 before 009), each in its own transaction (per the "Migration runner
applies pending migrations sequentially" requirement). The ordering MUST be
chosen so that additive and rename migrations (006, 007) run first, the
data-transform migration (008) runs next, and the destructive column-drop
migration (009) runs last. A legacy database at migration `005` SHALL advance
to `009` by running all four in order; a fresh database initialized from
`schema.sql` (seeded to `last_migration = '009'`) SHALL skip all four. Each
migration MUST be its own transaction so a failure of one does not roll back
previously-committed migrations.

#### Scenario: Legacy database at 005 runs all four migrations
- **WHEN** `apply_migrations(config)` runs on a database with `MAX(migration_id) = '005'`
- **THEN** migrations 006, 007, 008, 009 are applied in order, each in its own transaction, and the tracker records all four

#### Scenario: Fresh database skips all four migrations
- **WHEN** `apply_schema(config)` runs on a fresh database and seeds `yascheduler_migrations` with `last_migration = '009'`
- **THEN** subsequent `apply_migrations(config)` finds `MAX(migration_id) = '009'` and applies no pending migrations (all four are filtered out)

#### Scenario: Migration failure rolls back that migration only
- **WHEN** migration `008_status_to_enum.sql` fails (e.g. an out-of-range status value)
- **THEN** the transaction for 008 rolls back, the DB remains at migration `007` (006 and 007 are already committed in their own transactions), and `008` is NOT recorded in the tracker