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
(see the "Bootstrap DO block" requirement). `schema.sql` reflects the post-010
column set (see `schema.sql` for exact DDL).

#### Scenario: Schema applies cleanly on empty database
- **WHEN** `apply_schema(config)` is called with a valid `PostgresDbConfig` pointing to an empty PostgreSQL database
- **THEN** the DO block creates `yascheduler_migrations` and seeds it with `last_migration = '010'` (because `yascheduler_nodes` is absent), all tables from `schema.sql` are created with their latest columns, and the function returns without error

#### Scenario: Schema applies cleanly on legacy database
- **WHEN** `apply_schema(config)` is called on a database that has `yascheduler_nodes` but not `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and does NOT seed it (because `yascheduler_nodes` exists), `CREATE TABLE IF NOT EXISTS` skips existing tables, and the function returns without error; subsequent `apply_migrations(config)` advances the database from its current migration to `010`

#### Scenario: Schema snapshot has no inline ALTERs
- **WHEN** `schema.sql` is inspected for `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
- **THEN** none are present (schema evolution is expressed via migrations in `sql/migrations/`, not inline ALTERs)

### Requirement: Error reporting on existing schema

The system SHALL catch `DatabaseError` when tables already exist, print
"Database already initialized!", and re-raise the exception.

#### Scenario: Database already initialized
- **WHEN** `apply_schema(config)` is called on a database where tables already exist
- **THEN** "Database already initialized!" is printed and `DatabaseError` is raised

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
- **WHEN** a new migration is added
- **THEN** the `last_migration` CONSTANT in the DO block is updated to the new `prefix_id` (one manual edit in `schema.sql`)

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

The primary-key columns `yascheduler_nodes.node_id` and
`yascheduler_tasks.task_id` SHALL be declared as
`INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY` (SQL:2003 identity
columns, PostgreSQL 10+). They SHALL NOT be declared as `SERIAL PRIMARY KEY`.
The `GENERATED ALWAYS` clause rejects explicit inserts of the PK value
without `OVERRIDING SYSTEM VALUE`, guarding against a class of future bugs.

The `CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement SHALL reflect the
final shape as defined in `schema.sql` (see that file for exact DDL). The
`task_status` enum type SHALL be created in `schema.sql` before the
`CREATE TABLE yascheduler_tasks` statement. The `yascheduler_touch_updated_at()`
trigger function and the `yascheduler_tasks_touch_updated_at` trigger SHALL
be created in `schema.sql` after the `CREATE TABLE yascheduler_tasks`
statement (so a fresh database gets the trigger without running migration
007).

`schema.sql` SHALL include the full column set for both tables, the
`task_status` enum, the trigger function, and the trigger — see `schema.sql`
for exact DDL.

#### Scenario: schema.sql has no inline ALTER TABLE ADD COLUMN
- **WHEN** `schema.sql` is inspected for `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
- **THEN** none are present (schema evolution is expressed via migration files, not inline ALTERs)
