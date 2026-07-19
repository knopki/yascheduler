# Delta: db-migrations

## MODIFIED Requirements

### Requirement: Migration runner applies pending migrations sequentially

The system SHALL provide a synchronous function
`apply_migrations(config: PostgresDbConfig)` that opens a pg8000 connection
from the config, reads the last applied migration id from the
`yascheduler_migrations` tracker (`NULL` when the tracker is empty), scans
the migrations directory for `*.sql` and `*.py` files, filters to those whose
`prefix_id` is greater than the last applied id (or all files when the last
applied id is `NULL`), and applies them in string-sorted filename order, each
in its own transaction.

`prefix_id` is the token before the first `_` in the filename.

#### Scenario: Fresh tracker applies all migrations
- **WHEN** `apply_migrations(config)` is called on a database where `yascheduler_migrations` exists and is empty (or `MAX(migration_id)` returns `NULL`)
- **THEN** every migration file in the migrations directory is applied in string-sorted `prefix_id` order, each recorded in `yascheduler_migrations` after success

#### Scenario: Non-empty tracker applies only pending migrations
- **WHEN** `apply_migrations(config)` is called on a database where `MAX(migration_id)` returns a non-NULL value
- **THEN** only migration files with `prefix_id > last_applied` are applied, in string-sorted order

### Requirement: SQL migrations execute as a multi-statement string

For a `*.sql` migration file, the runner SHALL apply the file inside a single
transaction: the migration's SQL text is executed as a multi-statement string
in one round-trip, a row is inserted into `yascheduler_migrations` with the
migration's `prefix_id` as `migration_id`, and the transaction commits. On any
error during execution, the runner SHALL roll back (best-effort) and re-raise;
the tracker row is NOT inserted for the failed migration.

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

After `migration.migrate()` returns, the runner SHALL record the migration in
`yascheduler_migrations` and commit. The tracker record SHALL land in both the
normal case (migrate's work and the tracker row commit atomically together)
and the `self.commit()`-closed case (when migrate closed the runner's
transaction for a non-transactional operation and did not reopen one).

As a defensive guard, if the tracker record commit raises a
`DatabaseError`, the runner SHALL retry the record once in a fresh
transaction. A non-transient failure (e.g. a duplicate-`prefix_id` primary-key
violation) is re-raised by the retry.

On any other error during `migrate()` or the tracker recording, the runner
SHALL roll back (best-effort) and re-raise; the tracker row is NOT inserted
for the failed migration.

#### Scenario: Normal Python migration records tracker atomically
- **WHEN** `migration.migrate()` returns successfully with the runner's transaction still open
- **THEN** the tracker `INSERT` and `COMMIT` happen inside the same transaction as `migrate()`, committing atomically

#### Scenario: Python migration with self.commit() still records tracker
- **WHEN** `migration.migrate()` calls `self.commit()` (closing the runner's transaction) and does not reopen one
- **THEN** the tracker `INSERT` still records the migration, and the trailing `COMMIT` is a no-op warning

#### Scenario: Tracker INSERT retries on transient DatabaseError
- **WHEN** the tracker record commit raises a transient `DatabaseError`
- **THEN** the runner opens a fresh transaction, retries the record, and commits

#### Scenario: Python migration failure rolls back and is not recorded
- **WHEN** `migrate()` or the tracker recording raises an error
- **THEN** the runner rolls back (best-effort) and re-raises, and no tracker row is inserted for the failed migration

### Requirement: Migrations directory and file format

The system SHALL load migrations from the migrations directory. Migration
filenames SHALL match the pattern `{prefix_id}_{rest}.{sql,py}`, where
`prefix_id` is the token before the first `_`, is unique across all migration
files (`.sql` and `.py` combined), and determines application order by string
sort on the filename.

The `prefix_id` format is NOT fixed by this spec (e.g. `001`, `20260701120000`,
or any other token is acceptable); only the uniqueness, before-first-`_`, and
string-sortability constraints are required.

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

#### Scenario: Adding a schema-changing migration
- **WHEN** a developer adds a migration `002_add_status_index.sql` that creates an index
- **THEN** the developer creates the file, updates `last_migration` to `"002"` in `schema.sql`, and (if the migration changes a table's columns) updates the `CREATE TABLE` snapshot

#### Scenario: Adding a data-only migration
- **WHEN** a developer adds a migration `003_backfill_metadata.py` that only transforms existing rows (no DDL change)
- **THEN** the developer creates the file and updates `last_migration` to `"003"` in `schema.sql`; no `schema.sql` DDL edit is needed

### Requirement: Migration system is forward-only

The migration system SHALL be forward-only. Once a migration is recorded in
`yascheduler_migrations`, the tracker row SHALL persist (the runner applies
pending migrations in `prefix_id` order on every invocation).

#### Scenario: No down/rollback path
- **WHEN** a migration has been applied and recorded in `yascheduler_migrations`
- **THEN** there is no runner mechanism to reverse it; the tracker row is never deleted by the runner

#### Scenario: No generation tool
- **WHEN** a developer adds a migration
- **THEN** the developer writes the migration file and updates `schema.sql` by hand; no tool generates either
