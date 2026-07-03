## MODIFIED Requirements

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
- **THEN** the DO block creates `yascheduler_migrations`, inserts a row with `migration_id = last_migration` (`'005'` after the serial-to-identity change), and subsequent `apply_migrations` skips all migrations

#### Scenario: Legacy database is not seeded
- **WHEN** `apply_schema(config)` runs on a database with `yascheduler_nodes` but no `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and inserts no seed row; subsequent `apply_migrations` finds `MAX(migration_id) IS NULL` and applies all migrations

#### Scenario: Modern database skips the DO block
- **WHEN** `apply_schema(config)` runs on a database that already has `yascheduler_migrations`
- **THEN** the `to_regclass('yascheduler_migrations') IS NULL` guard is false, the DO block is a no-op, and the tracker is left untouched

#### Scenario: last_migration is a single edit point
- **WHEN** a new migration `005_serial_to_identity.sql` is added
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

The primary-key columns `yascheduler_nodes.node_id` and
`yascheduler_tasks.task_id` SHALL be declared as
`INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY` (SQL:2003 identity
columns, PostgreSQL 10+). They SHALL NOT be declared as `SERIAL PRIMARY KEY`.
The `GENERATED ALWAYS` clause rejects explicit inserts of the PK value
without `OVERRIDING SYSTEM VALUE`, guarding against a class of future bugs.

#### Scenario: CREATE TABLE includes all current columns
- **WHEN** `schema.sql` is inspected
- **THEN** `CREATE TABLE IF NOT EXISTS yascheduler_nodes` includes `node_id`, `ip`, `port`, `username`, `ncpus`, `enabled`, `cloud` columns with `node_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`; `CREATE TABLE IF NOT EXISTS yascheduler_tasks` includes `task_id`, `label`, `metadata`, `ip`, `status`, `allocated_node_id` columns with `task_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`

#### Scenario: No inline ALTER statements
- **WHEN** `schema.sql` is inspected
- **THEN** no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements appear (all schema evolution is via migration files)

#### Scenario: Primary keys use identity columns, not SERIAL
- **WHEN** `schema.sql` is inspected
- **THEN** neither `yascheduler_nodes.node_id` nor `yascheduler_tasks.task_id` is declared `SERIAL`; both are declared `INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`