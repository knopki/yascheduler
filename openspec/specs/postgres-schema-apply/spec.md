# PostgreSQL Schema Application

## Purpose

Define the synchronous `apply_schema()` function that reads `schema.sql` and applies it transactionally to a PostgreSQL database.

## Requirements

### Requirement: Transactional schema application

The system SHALL provide a synchronous function `apply_schema(config: PostgresDbConfig)`
that reads `schema.sql` and executes it within a `BEGIN/COMMIT` transaction.
On failure, the function SHALL execute `ROLLBACK` and re-raise the exception.

#### Scenario: Schema applies cleanly on empty database
- **WHEN** `apply_schema(config)` is called with a valid `PostgresDbConfig` pointing to an empty PostgreSQL database
- **THEN** the bootstrap logic creates `yascheduler_migrations` and seeds it to the latest migration (because `yascheduler_nodes` is absent), all tables from `schema.sql` are created with their latest columns and the `task_status_field_invariants` `CHECK` constraint on `yascheduler_tasks`, and the function returns without error

#### Scenario: Schema applies cleanly on legacy database
- **WHEN** `apply_schema(config)` is called on a database that has `yascheduler_nodes` but not `yascheduler_migrations`
- **THEN** the bootstrap logic creates `yascheduler_migrations` and does NOT seed it (because `yascheduler_nodes` exists), `CREATE TABLE IF NOT EXISTS` skips existing tables, and the function returns without error; subsequent `apply_migrations(config)` advances the database from its current state

### Requirement: Error reporting on existing schema

The system SHALL catch `DatabaseError` when tables already exist, print
"Database already initialized!", and re-raise the exception.

#### Scenario: Database already initialized
- **WHEN** `apply_schema(config)` is called on a database where tables already exist
- **THEN** "Database already initialized!" is printed and `DatabaseError` is raised

### Requirement: Bootstrap DO block

`schema.sql` SHALL begin with a DO block (before any `CREATE TABLE`
statement) that bootstraps the `yascheduler_migrations` tracker table. The DO
block SHALL distinguish three database states:

1. **Fresh database**: neither `yascheduler_migrations` nor `yascheduler_nodes` exist
   → create the tracker and seed it to the latest migration.
2. **Legacy database**: `yascheduler_nodes` exists but `yascheduler_migrations` does not
   → create the tracker but do NOT seed it (all migrations will run).
3. **Modern database**: `yascheduler_migrations` already exists
   → no-op.

The `last_migration` value SHALL be a single edit point in `schema.sql`,
updated when a new migration is added.

#### Scenario: Fresh database is seeded to the latest migration
- **WHEN** `apply_schema(config)` runs on a database with neither `yascheduler_migrations` nor `yascheduler_nodes`
- **THEN** the DO block creates `yascheduler_migrations`, inserts a row with the latest `migration_id`, and subsequent `apply_migrations` skips all migrations

#### Scenario: Legacy database is not seeded
- **WHEN** `apply_schema(config)` runs on a database with `yascheduler_nodes` but no `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and inserts no seed row; subsequent `apply_migrations` finds no migration rows and applies all migrations

#### Scenario: Modern database skips the DO block
- **WHEN** `apply_schema(config)` runs on a database that already has `yascheduler_migrations`
- **THEN** the DO block guard is false, the block is a no-op, and the tracker is left untouched

#### Scenario: last_migration is a single edit point
- **WHEN** a new migration is added
- **THEN** the `last_migration` value in the DO block is updated to the new migration identifier (one manual edit in `schema.sql`)

### Requirement: Full latest snapshot with no inline ALTERs

`schema.sql` SHALL be the full latest snapshot of the database schema: every
`CREATE TABLE` statement includes all current columns, and no inline
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements appear. Schema
evolution is expressed via migration files, not via inline `ALTER`s in
`schema.sql`.

The primary-key columns `yascheduler_nodes.node_id` and
`yascheduler_tasks.task_id` SHALL be declared as
`INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY` (SQL:2003 identity
columns, PostgreSQL 10+). They SHALL NOT be declared as `SERIAL PRIMARY KEY`.

The `task_status` enum type SHALL be created in `schema.sql` before the
`CREATE TABLE yascheduler_tasks` statement. The `yascheduler_touch_updated_at()`
trigger function and the `yascheduler_tasks_touch_updated_at` trigger SHALL
be created in `schema.sql` after the `CREATE TABLE yascheduler_tasks`
statement.

The `CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement SHALL include a
table-level `CHECK` constraint named `task_status_field_invariants` enforcing
the exhaustive per-status field contract:
`status='TO_DO' AND allocated_node_id IS NULL AND error IS NULL`, OR
`status='RUNNING' AND allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL`,
OR `status='DONE'`.

The `username` and `port` columns of `yascheduler_nodes` SHALL be present in
the `CREATE TABLE yascheduler_nodes` statement (they are part of the latest
snapshot).

#### Scenario: schema.sql has no inline ALTER TABLE ADD COLUMN
- **WHEN** `schema.sql` is inspected for `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
- **THEN** none are present (schema evolution is expressed via migration files, not inline ALTERs)

#### Scenario: Fresh database has the task_status_field_invariants CHECK
- **WHEN** `apply_schema(config)` runs on an empty database
- **THEN** the `task_status_field_invariants` `CHECK` constraint exists on `yascheduler_tasks` (visible in `information_schema.table_constraints` / `pg_constraint`) and enforces the exhaustive per-status field contract
