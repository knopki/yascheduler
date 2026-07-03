# PostgreSQL Schema Application

## Purpose

Define the synchronous `apply_schema()` function that reads `schema.sql` and applies it transactionally to a PostgreSQL database via pg8000.

## Requirements

### Requirement: Transactional schema application

The system SHALL provide a synchronous function `apply_schema(config: PostgresDbConfig)`
that reads `schema.sql` via `load_query("schema")` and executes it within a
`BEGIN/COMMIT` transaction using pg8000. On failure, the function SHALL execute
`ROLLBACK` and re-raise the exception. `schema.sql` is the full latest
snapshot of the database schema: every `CREATE TABLE` statement includes all
current columns, and no inline `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
statements appear (schema evolution is expressed via migrations, not via
inline `ALTER`s in `schema.sql`).

`schema.sql` SHALL begin with a DO block (before any `CREATE TABLE`) that
bootstraps the `yascheduler_migrations` tracker table using three-case logic
(see the "Bootstrap DO block" requirement).

#### Scenario: Schema applies cleanly on empty database
- **WHEN** `apply_schema(config)` is called with a valid `PostgresDbConfig` pointing to an empty PostgreSQL database
- **THEN** the DO block creates `yascheduler_migrations` and seeds it with the `last_migration` CONSTANT (because `yascheduler_nodes` is absent), all tables from `schema.sql` are created with their latest columns, and the function returns without error

#### Scenario: Schema applies cleanly on legacy database
- **WHEN** `apply_schema(config)` is called on a database that has `yascheduler_nodes` but not `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and does NOT seed it (because `yascheduler_nodes` exists), `CREATE TABLE IF NOT EXISTS` is a no-op for existing tables, and the function returns without error (subsequent `apply_migrations` will bring the legacy DB up to the latest version)

#### Scenario: Schema applies cleanly on modern database
- **WHEN** `apply_schema(config)` is called on a database that already has `yascheduler_migrations`
- **THEN** the DO block is a no-op (the `to_regclass` guard is false), `CREATE TABLE IF NOT EXISTS` is a no-op, and the function returns without error

#### Scenario: Partial failure is rolled back
- **WHEN** `apply_schema(config)` is called and SQL execution fails mid-way
- **THEN** no tables are created (transaction is rolled back) and the exception is re-raised

### Requirement: Error reporting on existing schema

The system SHALL catch `DatabaseError` when tables already exist, print
"Database already initialized!", and re-raise the exception.

#### Scenario: Database already initialized
- **WHEN** `apply_schema(config)` is called on a database where tables already exist
- **THEN** "Database already initialized!" is printed and `DatabaseError` is raised

### Requirement: Connection lifecycle

The function SHALL open a pg8000 native connection from the `PostgresDbConfig`,
execute the schema transaction, and close the connection. No connection pooling
or async is involved.

#### Scenario: Connection is closed after success
- **WHEN** `apply_schema(config)` completes successfully
- **THEN** the pg8000 connection is closed

#### Scenario: Connection is closed after failure
- **WHEN** `apply_schema(config)` raises an exception
- **THEN** the pg8000 connection is closed

### Requirement: schema.sql begins with a bootstrap DO block

`schema.sql` SHALL begin with a PL/pgSQL DO block (before any `CREATE TABLE`
statement) that bootstraps the `yascheduler_migrations` tracker table. The DO
block SHALL:

1. Declare `last_migration` as a PL/pgSQL `CONSTANT TEXT` set to the
   `prefix_id` of the latest migration (the single manual edit point in
   `schema.sql`).
2. Guard on `to_regclass('yascheduler_migrations') IS NULL` (uses
   `search_path`, no hardcoded schema name).
3. Inside the guard: `EXECUTE` the `CREATE TABLE yascheduler_migrations
   (migration_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT
   NOW())` statement (DDL inside PL/pgSQL requires `EXECUTE`; a static
   `CREATE TABLE` in a DO block is not parsed).
4. After creating the tracker, check `to_regclass('yascheduler_nodes') IS
   NULL`. If true (fresh database), `INSERT INTO yascheduler_migrations
   (migration_id) VALUES (last_migration)`. If false (legacy database with
   `yascheduler_nodes` but no tracker), do NOT seed.

The DO block MUST appear before any `CREATE TABLE IF NOT EXISTS
yascheduler_nodes` statement, because the presence of `yascheduler_nodes` is
the signal distinguishing a fresh database (seed to latest) from a legacy
database (no seed, run all migrations via `apply_migrations`). If the
`CREATE TABLE IF NOT EXISTS` ran first, a fresh database would always have
`yascheduler_nodes`, erasing the signal.

#### Scenario: Fresh database is seeded to the latest migration
- **WHEN** `apply_schema(config)` runs on a database with neither `yascheduler_migrations` nor `yascheduler_nodes`
- **THEN** the DO block creates `yascheduler_migrations`, inserts a row with `migration_id = last_migration`, and subsequent `apply_migrations` skips all migrations

#### Scenario: Legacy database is not seeded
- **WHEN** `apply_schema(config)` runs on a database with `yascheduler_nodes` but no `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and inserts no seed row; subsequent `apply_migrations` finds `MAX(migration_id) IS NULL` and applies all migrations

#### Scenario: Modern database skips the DO block
- **WHEN** `apply_schema(config)` runs on a database that already has `yascheduler_migrations`
- **THEN** the `to_regclass('yascheduler_migrations') IS NULL` guard is false, the DO block is a no-op, and the tracker is left untouched

#### Scenario: last_migration is a single edit point
- **WHEN** a new migration `005_...` is added
- **THEN** the `last_migration` CONSTANT in the DO block is updated to `"005"` (one manual edit in `schema.sql`)

### Requirement: schema.sql is the full latest snapshot with no inline ALTERs

`schema.sql` SHALL be the full latest snapshot of the database schema: every
`CREATE TABLE` statement includes all current columns, and no inline
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements appear. Schema
evolution is expressed via migration files under
`infra/persistence/sql/migrations/`, not via inline `ALTER`s in `schema.sql`.

The `username` and `port` columns of `yascheduler_nodes` SHALL be present in
the `CREATE TABLE yascheduler_nodes` statement (they are part of the latest
snapshot). The two `ALTER TABLE ... ADD COLUMN IF NOT EXISTS username/port`
statements that previously appeared in `schema.sql` are removed; they are
expressed as the first migration file instead.

The `allocated_node_id` column of `yascheduler_tasks` SHALL be present in the
`CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement as
`allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET
NULL` (nullable; added by migration 004, included in the snapshot so a fresh
database has it without running the migration). The DO block's
`last_migration` CONSTANT SHALL be `'004'` (the `prefix_id` of the latest
migration file).

#### Scenario: CREATE TABLE includes all current columns
- **WHEN** `schema.sql` is inspected
- **THEN** `CREATE TABLE IF NOT EXISTS yascheduler_nodes` includes `node_id`, `ip`, `port`, `username`, `ncpus`, `enabled`, `cloud` columns; `CREATE TABLE IF NOT EXISTS yascheduler_tasks` includes `task_id`, `label`, `metadata`, `ip`, `status`, `allocated_node_id` columns (where `allocated_node_id` is `INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL`)

#### Scenario: No inline ALTER statements
- **WHEN** `schema.sql` is inspected
- **THEN** no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements appear (all schema evolution is via migration files)

#### Scenario: last_migration constant is 004
- **WHEN** the `schema.sql` DO block is inspected
- **THEN** the `last_migration` CONSTANT is `'004'` (matching the `prefix_id` of `004_add_allocated_node_id.sql`, the latest migration file)
