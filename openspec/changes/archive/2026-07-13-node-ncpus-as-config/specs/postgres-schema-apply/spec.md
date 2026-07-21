## MODIFIED Requirements

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

The `yascheduler_nodes.ncpus` column SHALL be declared `SMALLINT DEFAULT NULL`
and the `CREATE TABLE yascheduler_nodes` statement SHALL include a table-level
`CHECK` constraint named `node_ncpus_positive` enforcing
`(ncpus IS NULL OR ncpus > 0)`. The magic `0` sentinel is no longer a valid
stored value in the latest snapshot; `NULL` represents "no operator limit".

#### Scenario: schema.sql has no inline ALTER TABLE ADD COLUMN
- **WHEN** `schema.sql` is inspected for `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
- **THEN** none are present (schema evolution is expressed via migration files, not inline ALTERs)

#### Scenario: Fresh database has the task_status_field_invariants CHECK
- **WHEN** `apply_schema(config)` runs on a fresh database (neither `yascheduler_migrations` nor `yascheduler_nodes` exist) and the bootstrap seeds to the latest migration
- **THEN** the `task_status_field_invariants` `CHECK` constraint is present on `yascheduler_tasks`

#### Scenario: Fresh database has the node_ncpus_positive CHECK
- **WHEN** `apply_schema(config)` runs on a fresh database (neither `yascheduler_migrations` nor `yascheduler_nodes` exist) and the bootstrap seeds to the latest migration
- **THEN** the `node_ncpus_positive` `CHECK` constraint is present on `yascheduler_nodes`, enforcing `(ncpus IS NULL OR ncpus > 0)`

#### Scenario: Fresh database ncpus column is nullable
- **WHEN** the `CREATE TABLE yascheduler_nodes` statement in `schema.sql` is inspected after the latest migration
- **THEN** `ncpus` is declared `SMALLINT DEFAULT NULL` (the column accepts `NULL`; `0` is rejected by the CHECK)
