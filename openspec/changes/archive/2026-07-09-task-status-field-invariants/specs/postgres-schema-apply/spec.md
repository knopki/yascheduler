## MODIFIED Requirements

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
(see the "Bootstrap DO block" requirement). `schema.sql` reflects the post-011
column set and the `task_status_field_invariants` `CHECK` constraint on
`yascheduler_tasks` (see `schema.sql` for exact DDL).

#### Scenario: Schema applies cleanly on empty database
- **WHEN** `apply_schema(config)` is called with a valid `PostgresDbConfig` pointing to an empty PostgreSQL database
- **THEN** the DO block creates `yascheduler_migrations` and seeds it with `last_migration = '011'` (because `yascheduler_nodes` is absent), all tables from `schema.sql` are created with their latest columns and the `task_status_field_invariants` `CHECK` constraint on `yascheduler_tasks`, and the function returns without error

#### Scenario: Schema applies cleanly on legacy database
- **WHEN** `apply_schema(config)` is called on a database that has `yascheduler_nodes` but not `yascheduler_migrations`
- **THEN** the DO block creates `yascheduler_migrations` and does NOT seed it (because `yascheduler_nodes` exists), `CREATE TABLE IF NOT EXISTS` skips existing tables, and the function returns without error; subsequent `apply_migrations(config)` advances the database from its current migration to `011`

#### Scenario: Schema snapshot has no inline ALTERs
- **WHEN** `schema.sql` is inspected for `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
- **THEN** none are present (schema evolution is expressed via migrations in `sql/migrations/`, not inline ALTERs)

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

The `CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement SHALL include a
table-level `CHECK` constraint named `task_status_field_invariants` enforcing
the exhaustive per-status field contract:
`status='TO_DO' AND allocated_node_id IS NULL AND error IS NULL`, OR
`status='RUNNING' AND allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL`,
OR `status='DONE'`. A fresh database seeded to `last_migration = '011'` SHALL
have this constraint without running migration 011, identical in behavior to
a database that reached 011 via migrations.

`schema.sql` SHALL include the full column set for both tables, the
`task_status` enum, the `task_status_field_invariants` `CHECK` on
`yascheduler_tasks`, the trigger function, and the trigger — see `schema.sql`
for exact DDL.

#### Scenario: schema.sql has no inline ALTER TABLE ADD COLUMN
- **WHEN** `schema.sql` is inspected for `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
- **THEN** none are present (schema evolution is expressed via migration files, not inline ALTERs)

#### Scenario: Fresh database has the task_status_field_invariants CHECK
- **WHEN** `apply_schema(config)` runs on an empty database
- **THEN** the `task_status_field_invariants` `CHECK` constraint exists on `yascheduler_tasks` (visible in `information_schema.table_constraints` / `pg_constraint`) and enforces the exhaustive per-status field contract without requiring migration 011 to run