# Database Migrations

## Purpose

Define the forward-only database migration system: the `apply_migrations()`
runner, the `Migration` base class for `.py` migrations, the
`yascheduler_migrations` tracker table, the migrations directory file format,
and the migration edit procedure. The runner is called by `yainit` (and test
fixtures) immediately after `apply_schema()`, bringing legacy and intermediate
databases up to the latest snapshot in `schema.sql`.

## Requirements

### Requirement: Migration runner applies pending migrations sequentially

The system SHALL provide a synchronous function
`apply_migrations(config: PostgresDbConfig)` that opens a pg8000 connection
from the config, reads the last applied migration id from
`SELECT MAX(migration_id) FROM yascheduler_migrations` (`NULL` when the
tracker is empty), scans the migrations directory for `*.sql` and `*.py` files
named `{prefix_id}_{rest}.{sql,py}`, filters to those whose `prefix_id` is
greater than the last applied id (or all files when the last applied id is
`NULL`), and applies them in string-sorted filename order, each in its own
transaction. `prefix_id` is the token before the first `_` in the filename.

#### Scenario: Fresh tracker applies all migrations
- **WHEN** `apply_migrations(config)` is called on a database where `yascheduler_migrations` exists and is empty (or `MAX(migration_id)` returns `NULL`)
- **THEN** every migration file in the migrations directory is applied in string-sorted `prefix_id` order, each recorded in `yascheduler_migrations` after success

#### Scenario: Non-empty tracker applies only pending migrations
- **WHEN** `apply_migrations(config)` is called on a database where `MAX(migration_id)` returns a non-NULL value
- **THEN** only migration files with `prefix_id > last_applied` are applied, in string-sorted order

### Requirement: Migration 006 renames label column to title

Migration 006 SHALL rename the `label` column to `title`.

#### Scenario: Migration 006 renames the column
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `005`
- **THEN** the migration `006_rename_label_to_title.sql` is applied and `006` is recorded in `yascheduler_migrations`

### Requirement: Migration 007 adds created_at and updated_at with a trigger

Migration 007 SHALL add `created_at` and `updated_at` columns with a trigger
function `yascheduler_touch_updated_at()` and trigger
`yascheduler_tasks_touch_updated_at`.

#### Scenario: Migration 007 adds columns and trigger
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `006`
- **THEN** `created_at` and `updated_at` columns are added to `yascheduler_tasks`, the function `yascheduler_touch_updated_at()` is created, and the trigger `yascheduler_tasks_touch_updated_at` is installed

### Requirement: Migration 008 converts status to a PostgreSQL enum

Migration 008 SHALL convert the `status` column to a PostgreSQL enum
`task_status` with labels `'TO_DO'`, `'RUNNING'`, `'DONE'`.

#### Scenario: Migration 008 creates the enum and converts the column
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `007`
- **THEN** the `task_status` enum type is created with labels `'TO_DO'`, `'RUNNING'`, `'DONE'`, and the `status` column is converted from `SMALLINT` to `task_status`

### Requirement: Migration 009 drops the allocated_ip column

Migration 009 SHALL drop the `allocated_ip` column from `yascheduler_tasks`.

#### Scenario: Migration 009 drops the column
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `008`
- **THEN** the `ip` column is dropped from `yascheduler_tasks`, and `009` is recorded in `yascheduler_migrations`

### Requirement: Migration 010 extracts metadata into typed columns and extra JSONB

Migration 010 SHALL extract metadata into typed columns (`engine`,
`remote_folder`, `local_folder`, `webhook_url`, `error`,
`webhook_custom_params`) and `extra` JSONB, dropping the `metadata` column.

#### Scenario: Migration 010 adds and backfills typed columns
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `009` on a row with `metadata = {"engine": "cp2k", "local_folder": "/l", "webhook_custom_params": {"parent": 42}, "input.in": "ATOMS ..."}`
- **THEN** the row gains `engine='cp2k'`, `remote_folder=NULL`, `local_folder='/l'`, `webhook_url=NULL`, `error=NULL`, `webhook_custom_params='{"parent": 42}'::jsonb`, `extra='{"input.in": "ATOMS ..."}'::jsonb`, and the `metadata` column is dropped

### Requirement: SQL migrations execute as a multi-statement string

For a `*.sql` migration file, the runner SHALL read the file text, open a
transaction with `BEGIN`, execute the full SQL text as a multi-statement string
in one round-trip, insert a row into `yascheduler_migrations` with the
migration's `prefix_id` as `migration_id`, and `COMMIT`. On any error during
execution, the runner SHALL `ROLLBACK` (best-effort) and re-raise; the tracker
row is NOT inserted for the failed migration.

#### Scenario: SQL migration applies and is recorded
- **WHEN** a `*.sql` migration file with `prefix_id = "001"` is applied successfully
- **THEN** a row `("001", <timestamp>)` exists in `yascheduler_migrations` and the migration's SQL is committed

#### Scenario: SQL migration failure rolls back and is not recorded
- **WHEN** a `*.sql` migration file's SQL raises an error mid-execution
- **THEN** the transaction is rolled back (best-effort), the error is re-raised, and no row for that `prefix_id` is inserted into `yascheduler_migrations`

### Requirement: Python migrations use a Migration base class with injected dependencies

The system SHALL provide a `Migration` base class with an
`__init__(self, config: PostgresDbConfig, conn, log)` that stores all three as
instance attributes (`self.config`, `self.conn`, `self.log`), a
`migrate(self) -> None` method that raises `NotImplementedError`, and
`begin()` / `commit()` helper methods. A `*.py` migration file SHALL define
exactly one subclass of `Migration` (excluding `Migration` itself) and
implement `migrate(self)`. The runner instantiates the subclass with
`(config, conn, log)` and calls `migrate()`.

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

### Requirement: Python migration class discovery

The runner SHALL discover the `Migration` subclass in each `*.py` migration
file. Each file SHALL define exactly one `Migration` subclass. Zero subclasses
or more than one SHALL be treated as an error naming the file.

#### Scenario: Python migration file with one subclass is loaded
- **WHEN** the runner scans a `*.py` migration file that defines exactly one `Migration` subclass
- **THEN** the subclass is instantiated and `migrate()` is called

#### Scenario: Python migration file with zero or multiple subclasses errors
- **WHEN** the runner scans a `*.py` migration file that defines zero or more than one `Migration` subclass
- **THEN** an error is raised identifying the file

### Requirement: Python migration tracker recording

After `migration.migrate()` returns, the runner SHALL attempt to record the
migration in `yascheduler_migrations` by running
`INSERT INTO yascheduler_migrations (migration_id) VALUES (<prefix_id>)`
followed by `COMMIT` inside the same transaction as `migrate()` (the normal
case: migrate()'s work and the tracker record commit atomically together).

If `migrate()` closed the runner's transaction by calling `self.commit()`
(for a non-transactional operation like `CREATE INDEX CONCURRENTLY`) and did
not reopen one, the tracker `INSERT` still records the migration: statements
issued outside an open transaction autocommit, so the `INSERT` autocommits and
the trailing `COMMIT` is a no-op warning rather than an error.

As a defensive guard, if the tracker `INSERT`/`COMMIT` raises a
`DatabaseError` for any transient reason, the runner SHALL open a fresh
`BEGIN`, retry the `INSERT`, and `COMMIT`. A non-transient failure (e.g. a
duplicate-`prefix_id` primary-key violation) is re-raised by the retry.

On any other error during `migrate()` or the tracker recording, the runner
SHALL `ROLLBACK` (best-effort) and re-raise; the tracker row is NOT inserted
for the failed migration.

#### Scenario: Normal Python migration records tracker atomically
- **WHEN** `migration.migrate()` returns successfully with the runner's transaction still open
- **THEN** the `INSERT` into `yascheduler_migrations` and `COMMIT` happen inside the same transaction as `migrate()`, committing atomically

#### Scenario: Python migration with self.commit() still records tracker
- **WHEN** `migration.migrate()` calls `self.commit()` (closing the runner's transaction) and does not reopen one
- **THEN** the tracker `INSERT` autocommits, and the trailing `COMMIT` is a no-op warning

#### Scenario: Tracker INSERT retries on transient DatabaseError
- **WHEN** the tracker `INSERT`/`COMMIT` raises a transient `DatabaseError`
- **THEN** the runner opens a fresh `BEGIN`, retries the `INSERT`, and `COMMIT`s

#### Scenario: Python migration failure rolls back and is not recorded
- **WHEN** `migrate()` or the tracker recording raises an error
- **THEN** the runner `ROLLBACK`s (best-effort) and re-raises, and no tracker row is inserted for the failed migration

### Requirement: Migrations directory and file format

The system SHALL load migrations from the migrations directory. Migration
filenames SHALL match the pattern `{prefix_id}_{rest}.{sql,py}`, where
`prefix_id` is the token before the first `_`, is unique across all migration
files (`.sql` and `.py` combined), and determines application order by string
sort on the filename.

The `prefix_id` format is NOT fixed by this spec (e.g. `001`, `20260701120000`,
or any other token is acceptable); only the uniqueness, before-first-`_`, and
string-sortability constraints are required.

Duplicate `prefix_id` detection is the responsibility of a unit test that
scans the migrations directory and asserts uniqueness, NOT of the runner. The
runner applies migrations; it does not validate `prefix_id` uniqueness.

#### Scenario: prefix_id is the token before the first underscore
- **WHEN** a migration file is named `001_add_username_port.sql`
- **THEN** its `prefix_id` is `"001"`

#### Scenario: String sort determines application order
- **WHEN** the migrations directory contains `001_....sql`, `010_....sql`, `002_....sql`
- **THEN** they are applied in the order `001`, `002`, `010` (string sort on the filename)

#### Scenario: prefix_id uniqueness is enforced by a unit test, not the runner
- **WHEN** two migration files share the same `prefix_id`
- **THEN** the runner does NOT detect this at runtime; a unit test that scans the migrations directory and asserts uniqueness SHALL fail

#### Scenario: prefix_id format is not fixed
- **WHEN** a migration file is named `20260701120000_add_index.sql`
- **THEN** its `prefix_id` is `"20260701120000"` and it is accepted (the spec does not require a specific format)

### Requirement: Migration edit procedure

When a new migration is added, three edits SHALL be made:

1. Create the migration file in the migrations directory with name
   `{prefix_id}_{rest}.sql` or `.py`.
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

Migration 004 SHALL add the `allocated_node_id` column to `yascheduler_tasks`
and backfill it for all existing tasks by joining
`yascheduler_nodes.ip = yascheduler_tasks.ip`.

#### Scenario: Migration 004 applies on a database with existing tasks
- **WHEN** `apply_migrations(config)` runs on a database at migration `003` with tasks having non-NULL `ip` values
- **THEN** the `ALTER TABLE` adds the nullable `allocated_node_id` column, the `UPDATE` backfills `allocated_node_id` by joining `yascheduler_nodes.ip = yascheduler_tasks.ip`, and a row `("004", <timestamp>)` is inserted into `yascheduler_migrations`

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

### Requirement: Migration 011 adds the task_status_field_invariants CHECK constraint

Migration 011 SHALL add a `CHECK` constraint named
`task_status_field_invariants` to `yascheduler_tasks` enforcing the exhaustive
per-status field contract. The constraint SHALL be:

```sql
ALTER TABLE yascheduler_tasks ADD CONSTRAINT task_status_field_invariants CHECK (
    (status = 'TO_DO'   AND allocated_node_id IS NULL     AND error IS NULL)
 OR (status = 'RUNNING' AND allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL)
 OR (status = 'DONE')
);
```

The migration SHALL NOT include a defensive pre-clean `UPDATE` before `ADD
CONSTRAINT`: the audit confirmed no production path creates the forbidden
states, so `ADD CONSTRAINT` succeeds on existing data; if that assumption
breaks the constraint fails fast at migration time, surfacing the offending
row rather than masking it.

#### Scenario: Migration 011 adds the CHECK constraint
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `"010"`
- **THEN** the `ALTER TABLE yascheduler_tasks ADD CONSTRAINT task_status_field_invariants CHECK (...)` is applied, the constraint is visible in `information_schema.table_constraints`, and a row `("011", <timestamp>)` is inserted into `yascheduler_migrations`

#### Scenario: Migration 011 succeeds on clean production data
- **WHEN** `apply_migrations(config)` runs on a database where no row in `yascheduler_tasks` has a forbidden (status, allocated_node_id, error, remote_folder) combination
- **THEN** the `ADD CONSTRAINT` succeeds and the migration is recorded

#### Scenario: Migration 011 fails fast on a forbidden row
- **WHEN** `apply_migrations(config)` runs on a database where some row violates the CHECK (e.g. a `TO_DO` row with non-NULL `allocated_node_id`)
- **THEN** the `ADD CONSTRAINT` raises a violation error naming the offending row, the transaction is rolled back, and no row for `"011"` is inserted into `yascheduler_migrations`

#### Scenario: The CHECK refuses a forbidden insert after migration
- **WHEN** an `INSERT INTO yascheduler_tasks (status, allocated_node_id, error, remote_folder)` produces a row with `status='TO_DO'` and `allocated_node_id IS NOT NULL`
- **THEN** the insert raises a CHECK violation referencing `task_status_field_invariants`

#### Scenario: The CHECK refuses a forbidden update after migration
- **WHEN** an `UPDATE yascheduler_tasks SET allocated_node_id = NULL WHERE status='RUNNING'` is attempted on a RUNNING row
- **THEN** the update raises a CHECK violation referencing `task_status_field_invariants`

#### Scenario: The CHECK refuses a bare node DELETE that would orphan a RUNNING task
- **WHEN** a `DELETE FROM yascheduler_nodes` is issued on a node that still has a row in `yascheduler_tasks` with `status='RUNNING'` and `allocated_node_id = <that node's node_id>`
- **THEN** the `ON DELETE SET NULL` cascade attempts to set `allocated_node_id = NULL` on the RUNNING row, the `task_status_field_invariants` CHECK rejects it (RUNNING requires `allocated_node_id IS NOT NULL`), and the DELETE is rolled back

#### Scenario: Hard-remove path is unaffected by the CHECK
- **WHEN** `_remove_node_hard` flips each RUNNING task to `DONE` via `update_status(task_id, DONE)` and then calls `nodes.remove(node_id)`
- **THEN** the rows are `DONE` by the time the `ON DELETE SET NULL` cascade fires, `DONE` permits NULL `allocated_node_id`, and neither the `update_status` nor the `nodes.remove` raises a CHECK violation

### Requirement: Migration 012 renames ip to hostname and adds node fields

Migration 012 SHALL rename the `ip` column to `hostname` on
`yascheduler_nodes`, widen it to `VARCHAR(255)`, add `created_at`/`updated_at`
with a `BEFORE UPDATE` trigger (mirroring `yascheduler_tasks` migration 007),
add `jump_host`/`jump_port`/`jump_username` placeholder columns, add
`external_id` (backfilled from `hostname` only for rows with a non-empty
`cloud`), create the `NODE_STATUS` enum type with a single label `'OTHER'`
and add the `status` column, and add `NOT NULL` + `CHECK` constraints to the
`port` column.

The migration SHALL perform these steps in order:

1. `ALTER TABLE yascheduler_nodes RENAME COLUMN ip TO hostname`
2. `ALTER TABLE yascheduler_nodes ALTER COLUMN hostname TYPE VARCHAR(255)`
3. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
4. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
5. Create the `YASCHEDULER_TOUCH_UPDATED_AT` trigger function (if not already
   present from migration 007) and install the
   `yascheduler_nodes_touch_updated_at` trigger on `yascheduler_nodes`
6. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS jump_host VARCHAR(255)`
   (nullable)
7. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS jump_port INTEGER NOT NULL DEFAULT 22`
   + `CHECK (jump_port > 0 AND jump_port < 65536)`
8. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS jump_username VARCHAR(255) NOT NULL DEFAULT 'root'`
9. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS external_id VARCHAR(255)`
   (nullable)
10. `UPDATE yascheduler_nodes SET external_id = hostname WHERE cloud IS NOT NULL AND hostname <> ''`
    (backfill only for cloud nodes with a non-empty hostname)
11. `CREATE TYPE NODE_STATUS AS ENUM ('OTHER')` (idempotent via DO block)
12. `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS status NODE_STATUS NOT NULL DEFAULT 'OTHER'`
13. `ALTER TABLE yascheduler_nodes ALTER COLUMN port SET NOT NULL`
14. `ALTER TABLE yascheduler_nodes ADD CONSTRAINT node_port_range CHECK (port > 0 AND port < 65536)`

After the migration, `schema.sql` SHALL be updated: the `last_migration`
CONSTANT bumped from `'011'` to `'012'`, and the `yascheduler_nodes`
`CREATE TABLE` snapshot updated to include all new columns.

#### Scenario: Migration 012 renames ip to hostname
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `"011"`
- **THEN** the `ip` column is renamed to `hostname` on `yascheduler_nodes`, widened to `VARCHAR(255)`, and `"012"` is recorded in `yascheduler_migrations`

#### Scenario: Migration 012 adds created_at and updated_at with trigger
- **WHEN** migration 012 runs
- **THEN** `created_at` and `updated_at` columns are added to `yascheduler_nodes` with `DEFAULT NOW()`, and the `yascheduler_nodes_touch_updated_at` trigger is installed

#### Scenario: Migration 012 backfills external_id for cloud nodes only
- **WHEN** migration 012 runs on a database with a cloud node `hostname="10.0.0.1", cloud="aws"` and a static node `hostname="10.0.0.2", cloud=NULL`
- **THEN** the cloud node gets `external_id="10.0.0.1"` and the static node keeps `external_id=NULL`

#### Scenario: Migration 012 creates NODE_STATUS enum and status column
- **WHEN** migration 012 runs
- **THEN** the `NODE_STATUS` enum type is created with label `'OTHER'`, and the `status` column is added with `NOT NULL DEFAULT 'OTHER'`

#### Scenario: Migration 012 adds port constraints
- **WHEN** migration 012 runs
- **THEN** the `port` column gains `NOT NULL` and a `CHECK (port > 0 AND port < 65536)` constraint named `node_port_range`

#### Scenario: Migration 012 adds jump host fields
- **WHEN** migration 012 runs
- **THEN** `jump_host` (VARCHAR(255), nullable), `jump_port` (INTEGER NOT NULL DEFAULT 22, CHECK 0-65535), and `jump_username` (VARCHAR(255) NOT NULL DEFAULT 'root') columns are added

#### Scenario: Schema snapshot updated after migration 012
- **WHEN** the `schema.sql` `CREATE TABLE yascheduler_nodes` is inspected after migration 012
- **THEN** it includes `hostname VARCHAR(255)`, `created_at`/`updated_at`, `jump_host`/`jump_port`/`jump_username`, `external_id`, `status NODE_STATUS`, and the `port` CHECK constraint; the `last_migration` CONSTANT is `'012'`

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
