# Spec Delta: postgres-schema-apply

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