## MODIFIED Requirements

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