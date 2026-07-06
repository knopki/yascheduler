# Database Migrations

## Purpose

Define the forward-only database migration system: the `apply_migrations()`
runner, the `Migration` base class for `.py` migrations, the
`yascheduler_migrations` tracker table, the `sql/migrations/` file format,
and the migration edit procedure. The runner is called by `yainit` (and the
test fixtures) immediately after `apply_schema()`, bringing legacy and
intermediate databases up to the latest snapshot in `schema.sql`.

## Requirements

### Requirement: Migration runner applies pending migrations sequentially

The system SHALL provide a synchronous function
`apply_migrations(config: PostgresDbConfig)` that opens a pg8000 native
connection from the config, reads the last applied migration id from
`SELECT MAX(migration_id) FROM yascheduler_migrations` (`NULL` when the
tracker is empty), scans the `infra/persistence/sql/migrations/` directory
for `*.sql` and `*.py` files named `{prefix_id}_{rest}.{sql,py}`, filters to
those whose `prefix_id` is greater than the last applied id (or all files when
the last applied id is `NULL`), and applies them in string-sorted filename
order, each in its own transaction. `prefix_id` is the token before the first
`_` in the filename.

#### Scenario: Fresh tracker applies all migrations
- **WHEN** `apply_migrations(config)` is called on a database where `yascheduler_migrations` exists and is empty (or `MAX(migration_id)` returns `NULL`)
- **THEN** every migration file in `migrations/` is applied in string-sorted `prefix_id` order, each recorded in `yascheduler_migrations` after success

#### Scenario: Non-empty tracker applies only pending migrations
- **WHEN** `apply_migrations(config)` is called on a database where `MAX(migration_id)` returns a non-NULL val

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
- **THEN** subsequent `apply_migrations(config)` finds `MAX(migration_id) = '009'` and applies no pending migrations (all four are already applied via schema.sql)ue `L`
- **THEN** only migration files whose `prefix_id > L` are applied, in string-sorted order

#### Scenario: Tracker absent is treated defensively as apply-all
- **WHEN** `apply_migrations(config)` is called on a database where `yascheduler_migrations` does not exist
- **THEN** the function treats the tracker as empty (last applied id = NULL) and applies all migrations, rather than raising. This is a defensive path: the tracker is normally created by `apply_schema`'s DO block, and `apply_migrations` is only called after `apply_schema`; the defensive behavior keeps the runner from crashing if that ordering is ever violated

#### Scenario: Each migration runs in its own transaction
- **WHEN** `apply_migrations(config)` applies a sequence of migrations
- **THEN** each migration is wrapped in its own `BEGIN/COMMIT`; the success or failure of one migration does not affect the transaction state of the next

### Requirement: SQL migrations execute as a multi-statement string

For a `*.sql` migration file, the runner SHALL read the file text, open a
transaction with `BEGIN`, execute the full SQL text in a single
`conn.run(sql_text)` call (pg8000 native Simple Query, which executes a
`;`-separated multi-statement string in one round-trip), insert a row into
`yascheduler_migrations` with the migration's `prefix_id` as `migration_id`,
and `COMMIT`. On any error during execution, the runner SHALL `ROLLBACK`
(best-effort) and re-raise; the tracker row is NOT inserted for the failed
migration.

#### Scenario: SQL migration applies and is recorded
- **WHEN** a `*.sql` migration file with `prefix_id = "001"` is applied successfully
- **THEN** a row `("001", <timestamp>)` exists in `yascheduler_migrations` and the migration's SQL is committed

#### Scenario: SQL migration failure rolls back and is not recorded
- **WHEN** a `*.sql` migration file's SQL raises an error mid-execution
- **THEN** the transaction is rolled back (best-effort), the error is re-raised, and no row for that `prefix_id` is inserted into `yascheduler_migrations`

### Requirement: Python migrations use a Migration base class with injected dependencies

The system SHALL provide a `Migration` base class (in
`infra/persistence/migration_base.py`, NOT under `migrations/`) with an
`__init__(self, config: PostgresDbConfig, conn: pg8000.native.Connection, log: logging.Logger)`
that stores all three as instance attributes (`self.config`, `self.conn`,
`self.log`), a `migrate(self) -> None` method that raises `NotImplementedError`,
and `begin()` / `commit()` helper methods that delegate to
`self.conn.run("BEGIN")` / `self.conn.run("COMMIT")`. A `*.py` migration file
SHALL define exactly one subclass of `Migration` (excluding `Migration`
itself) and implement `migrate(self)`. The runner instantiates the subclass
with `(config, conn, log)` and calls `migrate()`.

The `begin()` / `commit()` helpers exist for migrations needing
non-transactional operations (`CREATE INDEX CONCURRENTLY`, `VACUUM`): the
intended pattern is `self.commit()` to close the runner's transaction, run the
non-transactional command, then `self.begin()` to reopen a transaction.

#### Scenario: Migration subclass receives injected dependencies
- **WHEN** a `*.py` migration file defines `class MyMigration(Migration)` with a `migrate(self)` that uses `self.config`, `self.conn`, and `self.log`
- **THEN** the runner instantiates `MyMigration(config, conn, log)` and all three attributes are available inside `migrate()`

#### Scenario: Migration helpers control the transaction
- **WHEN** a `*.py` migration calls `self.commit()` then runs `CREATE INDEX CONCURRENTLY ...` then calls `self.begin()`
- **THEN** the `CREATE INDEX CONCURRENTLY` runs outside a transaction, and a new transaction is open when `migrate()` returns

#### Scenario: Migrations are not required to be idempotent
- **WHEN** a migration's correctness is considered
- **THEN** the system does NOT require the migration to be safe to re-apply; the tracker guards against re-application (each `prefix_id` is applied at most once per database)

### Requirement: Python migration class is discovered via inspect

For a `*.py` migration file, the runner SHALL load the module by file path
using `importlib.util.spec_from_file_location` + `module_from_spec` +
`exec_module` (NOT `importlib.import_module`, because migration filenames
frequently start with a digit and are not valid Python module names). The
runner SHALL then use `inspect.getmembers` (or equivalent) to find all
subclasses of `Migration` defined in the module, excluding `Migration`
itself.

#### Scenario: Exactly one subclass is accepted
- **WHEN** a `*.py` migration file defines exactly one subclass of `Migration`
- **THEN** the runner instantiates that subclass and calls `migrate()`

#### Scenario: Zero subclasses is an error
- **WHEN** a `*.py` migration file defines no subclass of `Migration`
- **THEN** the runner raises an error naming the file and stating that exactly one `Migration` subclass is required

#### Scenario: More than one subclass is an error
- **WHEN** a `*.py` migration file defines two or more subclasses of `Migration`
- **THEN** the runner raises an error naming the file and stating that exactly one `Migration` subclass is required

### Requirement: Python migration tracker recording is best-effort atomic

After `migration.migrate()` returns, the runner SHALL attempt to record the
migration in `yascheduler_migrations` by running
`INSERT INTO yascheduler_migrations (migration_id) VALUES (<prefix_id>)`
followed by `COMMIT` inside the same transaction as `migrate()` (the normal
case: migrate()'s work and the tracker record commit atomically together —
migrate() applied ⇔ tracker recorded).

If `migrate()` closed the runner's transaction by calling `self.commit()`
(for a non-transactional operation like `CREATE INDEX CONCURRENTLY`) and did
not reopen one, the tracker `INSERT` still records the migration: pg8000
native autocommits statements issued outside an open transaction, so the
`INSERT` autocommits and the trailing `COMMIT` is a no-op warning rather
than an error. The migration's data is already committed (by the migration's
own `self.commit()`), and the tracker record is committed in its own
autocommit transaction. The migration is still recorded as applied.

As a defensive guard, if the tracker `INSERT`/`COMMIT` raises a
`DatabaseError` for any transient reason, the runner SHALL open a fresh
`BEGIN`, retry the `INSERT`, and `COMMIT`. A non-transient failure (e.g. a
duplicate-`prefix_id` primary-key violation, which the uniqueness unit test
guards against) is re-raised by the retry.

On any other error during `migrate()` or the tracker recording, the runner
SHALL `ROLLBACK` (best-effort) and re-raise; the tracker row is NOT inserted
for the failed migration.

#### Scenario: Normal case records tracker atomically with migrate
- **WHEN** a `*.py` migration's `migrate()` returns with an open transaction (did not call `self.commit()`)
- **THEN** the runner's `INSERT tracker → COMMIT` runs in the same transaction as `migrate()`, so the migration's work and the tracker record are committed together

#### Scenario: Closed transaction still records the tracker
- **WHEN** a `*.py` migration's `migrate()` calls `self.commit()` (closing the runner's transaction) and returns without reopening
- **THEN** the runner's tracker `INSERT` still records the migration: pg8000 autocommits the INSERT (no open transaction) and the trailing COMMIT is a no-op warning, so no error is raised; the migration is recorded as applied

#### Scenario: Transient tracker error reopens a fresh transaction
- **WHEN** the tracker `INSERT`/`COMMIT` raises a transient `DatabaseError` (e.g. a deadlock)
- **THEN** the runner opens a fresh `BEGIN`, retries the `INSERT`, and `COMMIT`s; a non-transient failure re-raises and is handled by the outer ROLLBACK

#### Scenario: migrate failure rolls back and is not recorded
- **WHEN** a `*.py` migration's `migrate()` raises an error
- **THEN** the runner `ROLLBACK`s (best-effort), re-raises, and no tracker row is inserted for that `prefix_id`

### Requirement: Migrations directory and file format

The system SHALL load migrations from
`infra/persistence/sql/migrations/`. Migration filenames SHALL match the
pattern `{prefix_id}_{rest}.{sql,py}`, where `prefix_id` is the token before
the first `_`, is unique across all migration files (`.sql` and `.py`
combined), and determines application order by string sort on the filename.

The `prefix_id` format is NOT fixed by this spec (e.g. `001`, `20260701120000`,
or any other token is acceptable); only the uniqueness, before-first-`_`, and
string-sortability constraints are required.

Duplicate `prefix_id` detection is the responsibility of a unit test that
scans `migrations/` and asserts uniqueness, NOT of the runner. The runner
applies migrations; it does not validate `prefix_id` uniqueness.

#### Scenario: prefix_id is the token before the first underscore
- **WHEN** a migration file is named `001_add_username_port.sql`
- **THEN** its `prefix_id` is `"001"`

#### Scenario: String sort determines application order
- **WHEN** `migrations/` contains `001_....sql`, `010_....sql`, `002_....sql`
- **THEN** they are applied in the order `001`, `002`, `010` (string sort on the filename)

#### Scenario: prefix_id uniqueness is enforced by a unit test, not the runner
- **WHEN** two migration files share the same `prefix_id`
- **THEN** the runner does NOT detect this at runtime; a unit test that scans `migrations/` and asserts uniqueness SHALL fail

#### Scenario: prefix_id format is not fixed
- **WHEN** a migration file is named `20260701120000_add_index.sql`
- **THEN** its `prefix_id` is `"20260701120000"` and it is accepted (the spec does not require a specific format)

### Requirement: Migration edit procedure

When a new migration is added, three edits SHALL be made:

1. Create the migration file under `infra/persistence/sql/migrations/` with
   name `{prefix_id}_{rest}.sql` or `.py`.
2. Update the `last_migration` CONSTANT in the `schema.sql` DO block to the
   new `prefix_id`.
3. If the migration changes the schema (DDL), update the snapshot DDL in
   `schema.sql` (e.g. add a new column to the relevant `CREATE TABLE`).

Forgetting step 2 means a fresh database (seeded to the old `last_migration`)
will have the new migration re-applied on the next `yainit`; if the migration
is idempotent this is harmless, if not it fails loudly. Forgetting step 3
means a fresh database is missing the schema change. These steps are a
documented procedure; a unit test asserting the `schema.sql` CONSTANT matches
the latest migration file's `prefix_id` SHOULD exist to catch step 2 drift.

#### Scenario: Adding a schema-changing migration
- **WHEN** a developer adds a migration `002_add_status_index.sql` that creates an index
- **THEN** the developer creates the file, updates `last_migration` to `"002"` in `schema.sql`, and (if the migration changes a table's columns) updates the `CREATE TABLE` snapshot

#### Scenario: Adding a data-only migration
- **WHEN** a developer adds a migration `003_backfill_metadata.py` that only transforms existing rows (no DDL change)
- **THEN** the developer creates the file and updates `last_migration` to `"003"` in `schema.sql`; no `schema.sql` DDL edit is needed

### Requirement: Migration 004 adds allocated_node_id with backfill

The system SHALL include a migration file
`infra/persistence/sql/migrations/004_add_allocated_node_id.sql` that adds the
`allocated_node_id` column to `yascheduler_tasks` and backfills it for all
existing tasks.

The migration SHALL execute, in one transaction:

1. `ALTER TABLE yascheduler_tasks ADD COLUMN allocated_node_id INTEGER
   REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL` — nullable FK;
   deleting a node nulls the task's `allocated_node_id` (the task row and
   `allocated_ip` are preserved).
2. `UPDATE yascheduler_tasks t SET allocated_node_id = (SELECT n.node_id FROM
   yascheduler_nodes n WHERE n.ip = t.ip) WHERE t.ip IS NOT NULL` — backfills
   `allocated_node_id` for every task with a non-NULL `ip` by joining on `ip`.
   Tasks with `ip IS NULL` (unallocated TO_DO) stay `allocated_node_id = NULL`.

The migration assumes `ip` is unique-or-NULL at migration time (the duplicate-IP
feature is not yet in production use). For a legacy deployment that already has
duplicate IPs, the `SELECT n.node_id ... WHERE n.ip = t.ip` subquery returns
one row arbitrarily (Postgres does not guarantee which); those rows get a
best-effort `allocated_node_id` and the read path (still ip until Surface A) is
unaffected.

The migration's `prefix_id` is `"004"`. It SHALL be recorded in
`yascheduler_migrations` after successful application. The `schema.sql` DO
block's `last_migration` CONSTANT SHALL be bumped from `'003'` to `'004'`
(see the `postgres-schema-apply` capability). The `schema.sql`
`CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement SHALL include the
`allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET
NULL` column (the latest snapshot includes all current columns).

#### Scenario: Migration 004 applies on a database with existing tasks
- **WHEN** `apply_migrations(config)` runs on a database at migration `003` with tasks having non-NULL `ip` values
- **THEN** the `ALTER TABLE` adds the nullable `allocated_node_id` column, the `UPDATE` backfills `allocated_node_id` by joining `yascheduler_nodes.ip = yascheduler_tasks.ip`, and a row `("004", <timestamp>)` is inserted into `yascheduler_migrations`

#### Scenario: Migration 004 leaves unallocated tasks with NULL allocated_node_id
- **WHEN** `apply_migrations(config)` runs and a task has `ip IS NULL` (unallocated TO_DO)
- **THEN** the `UPDATE` does not touch that row (the `WHERE t.ip IS NOT NULL` guard excludes it); its `allocated_node_id` stays `NULL`

#### Scenario: Migration 004 is recorded in the tracker
- **WHEN** migration `004_add_allocated_node_id.sql` applies successfully
- **THEN** `yascheduler_migrations` contains a row with `migration_id = "004"`

#### Scenario: Migration 004 failure rolls back
- **WHEN** migration `004_add_allocated_node_id.sql` raises an error mid-execution (e.g. the ALTER fails)
- **THEN** the transaction is rolled back, the error is re-raised, no row with `migration_id = "004"` is inserted into `yascheduler_migrations`, and the `allocated_node_id` column is NOT added

#### Scenario: Fresh database seeds to 004 and skips the migration
- **WHEN** `apply_schema(config)` runs on an empty database (no `yascheduler_nodes`, no `yascheduler_migrations`)
- **THEN** the DO block creates `yascheduler_migrations` and seeds it with `migration_id = "004"` (the `last_migration` CONSTANT); subsequent `apply_migrations` finds `MAX(migration_id) = "004"` and skips migration `004` (the `CREATE TABLE` already included the `allocated_node_id` column)

#### Scenario: FK ON DELETE SET NULL nulls allocated_node_id when node is removed
- **WHEN** a node row is deleted (`uow.nodes.remove(node_id)`) and a task references that node via `allocated_node_id`
- **THEN** the task's `allocated_node_id` is set to `NULL` by the FK `ON DELETE SET NULL` action; the task row, its `allocated_ip`, and all other columns are preserved

#### Scenario: Backfill handles unique-ip legacy rows
- **WHEN** `apply_migrations(config)` runs on a database where every task's `ip` matches exactly one node's `ip` (unique-ip deployment)
- **THEN** every task with a non-NULL `ip` gets `allocated_node_id` set to the matching node's `node_id`; no ambiguity

#### Scenario: Backfill on a dup-ip legacy row is best-effort
- **WHEN** `apply_migrations(config)` runs on a database where a task's `ip` matches multiple nodes' `ip` (legacy dup-IP, pre-feature)
- **THEN** the `SELECT n.node_id ... WHERE n.ip = t.ip` subquery returns one row arbitrarily; the task gets a best-effort `allocated_node_id`; the read path (still ip) is unaffected


### Requirement: Migration system is forward-only

The migration system SHALL be forward-only. The runner SHALL apply pending
migrations in `prefix_id` order and SHALL NOT provide a migration rollback
("down") path, a migration generation tool, or a `schema.sql` generation tool.
Migrations are hand-written; the `schema.sql` snapshot is hand-maintained.
Once a migration is recorded in `yascheduler_migrations`, the runner SHALL
NOT delete that tracker row or reverse the migration.

#### Scenario: No down/rollback path
- **WHEN** a migration has been applied and recorded in `yascheduler_migrations`
- **THEN** there is no runner mechanism to reverse it; the tracker row is never deleted by the runner

#### Scenario: No generation tool
- **WHEN** a developer adds a migration
- **THEN** the developer writes the migration file and updates `schema.sql` by hand; no tool generates either
