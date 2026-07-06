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
(see the "Bootstrap DO block" requirement). After the drop-task-context-entity
change, the DO block's `last_migration` CONSTANT is `'010'` (was `'009'`) and
`yascheduler_tasks` reflects the post-010 shape: `task_id`, `title`,
`engine VARCHAR(64) NOT NULL`, `remote_folder VARCHAR(1024)`, `local_folder
VARCHAR(1024)`, `webhook_url VARCHAR(2048)`, `error TEXT`,
`webhook_custom_params JSONB NOT NULL DEFAULT '{}'::jsonb`, `extra JSONB NOT
NULL DEFAULT '{}'::jsonb`, `status task_status NOT NULL DEFAULT 'TO_DO'`,
`allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE
SET NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `updated_at
TIMESTAMPTZ NOT NULL DEFAULT NOW()`. The `metadata` column is absent (dropped
by migration 010). The `ip` column is absent (dropped by migration 009).

#### Scenario: Schema applies cleanly on empty database
- **WHEN** `apply_schema(config)` is called with a valid `PostgresDbConfig` pointing to an empty PostgreSQL database
- **THEN** the DO block creates `yascheduler_migrations` and seeds it with `last_migration = '010'` (because `yascheduler_nodes` is absent), all tables from `schema.sql` are created with their latest columns (including the seven typed columns and `extra` JSONB on `yascheduler_tasks`, no `metadata` column), and the function returns without error

#### Scenario: Schema applies cleanly on legacy database
- **WHEN** `apply_schema(config)` is called on a database that has `yascheduler_nodes` but not `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and does NOT seed it (because `yascheduler_nodes` exists), `CREATE TABLE IF NOT EXISTS` skips existing tables, and the function returns without error; subsequent `apply_migrations(config)` advances the database from its current migration to `010`

#### Scenario: Schema snapshot has no inline ALTERs
- **WHEN** `schema.sql` is inspected for `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
- **THEN** none are present (schema evolution is expressed via migrations in `sql/migrations/`, not inline ALTERs)

#### Scenario: Schema snapshot includes the typed columns
- **WHEN** `schema.sql`'s `CREATE TABLE yascheduler_tasks` statement is inspected
- **THEN** it includes `engine VARCHAR(64) NOT NULL`, `remote_folder VARCHAR(1024)`, `local_folder VARCHAR(1024)`, `webhook_url VARCHAR(2048)`, `error TEXT`, `webhook_custom_params JSONB NOT NULL DEFAULT '{}'::jsonb`, `extra JSONB NOT NULL DEFAULT '{}'::jsonb`; the `metadata` column is absent; the `ip` column is absent

#### Scenario: last_migration constant is 010
- **WHEN** `schema.sql`'s DO block is inspected for the `last_migration` CONSTANT
- **THEN** the value is `'010'` (bumped from `'009'` by the drop-task-context-entity change)

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
   `schema.sql`). After the task-schema-and-entity-cleanup change, the value
   SHALL be `'009'` (was `'005'`).
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
- **THEN** the DO block creates `yascheduler_migrations`, inserts a row with `migration_id = last_migration` (`'009'` after the task-schema-and-entity-cleanup change), and subsequent `apply_migrations` skips all migrations

#### Scenario: Legacy database is not seeded
- **WHEN** `apply_schema(config)` runs on a database with `yascheduler_nodes` but no `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and inserts no seed row; subsequent `apply_migrations` finds `MAX(migration_id) IS NULL` and applies all migrations

#### Scenario: Modern database skips the DO block
- **WHEN** `apply_schema(config)` runs on a database that already has `yascheduler_migrations`
- **THEN** the `to_regclass('yascheduler_migrations') IS NULL` guard is false, the DO block is a no-op, and the tracker is left untouched

#### Scenario: last_migration is a single edit point
- **WHEN** a new migration `005_serial_to_identity.sql` is added
- **THEN** the `last_migration` CONSTANT in the DO block is updated to `"009"` (one manual edit in `schema.sql`)

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
final shape: columns `task_id INTEGER PRIMARY KEY GENERATED ALWAYS AS
IDENTITY`, `title VARCHAR(256)` (renamed from `label`), `metadata JSONB`,
`status task_status NOT NULL DEFAULT 'TO_DO'` (the PostgreSQL enum, was
`SMALLINT NOT NULL DEFAULT 0`), `allocated_node_id INTEGER REFERENCES
yascheduler_nodes(node_id) ON DELETE SET NULL`, `created_at TIMESTAMPTZ NOT
NULL DEFAULT NOW()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`. The
`ip` column SHALL NOT appear (dropped by migration 009). The
`task_status` enum type SHALL be created in `schema.sql` before the
`CREATE TABLE yascheduler_tasks` statement (via `CREATE TYPE task_status AS
ENUM ('TO_DO', 'RUNNING', 'DONE');`). The `yascheduler_touch_updated_at()`
trigger function and the `yascheduler_tasks_touch_updated_at` trigger SHALL
be created in `schema.sql` after the `CREATE TABLE yascheduler_tasks`
statement (so a fresh database gets the trigger without running migration
007).

#### Scenario: CREATE TABLE includes all current columns
- **WHEN** `schema.sql` is inspected
- **THEN** `CREATE TABLE IF NOT EXISTS yascheduler_nodes` includes `node_id`, `ip`, `port`, `username`, `ncpus`, `enabled`, `cloud` columns with `node_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`; `CREATE TABLE IF NOT EXISTS yascheduler_tasks` includes `task_id`, `title`, `metadata`, `status`, `allocated_node_id`, `created_at`, `updated_at` columns (the `ip` column is absent, the `label` column is renamed to `title`, `created_at`/`updated_at` are added, `status` is the `task_status` enum) with `task_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`

#### Scenario: schema.sql creates the task_status enum type
- **WHEN** `schema.sql` is inspected
- **THEN** a `CREATE TYPE task_status AS ENUM ('TO_DO', 'RUNNING', 'DONE');` statement appears before `CREATE TABLE IF NOT EXISTS yascheduler_tasks`

#### Scenario: schema.sql installs the updated_at trigger
- **WHEN** `schema.sql` is inspected
- **THEN** the `yascheduler_touch_updated_at()` function definition and the `CREATE TRIGGER yascheduler_tasks_touch_updated_at ... EXECUTE FUNCTION yascheduler_touch_updated_at()` statement appear after `CREATE TABLE IF NOT EXISTS yascheduler_tasks`

#### Scenario: No inline ALTER statements
- **WHEN** `schema.sql` is inspected
- **THEN** no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements appear (all schema evolution is via migration files)

#### Scenario: Primary keys use identity columns, not SERIAL
- **WHEN** `schema.sql` is inspected
- **THEN** neither `yascheduler_nodes.node_id` nor `yascheduler_tasks.task_id` is declared `SERIAL`; both are declared `INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`
