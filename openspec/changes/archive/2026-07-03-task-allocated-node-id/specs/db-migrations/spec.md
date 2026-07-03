## ADDED Requirements

### Requirement: Migration 004 adds allocated_node_id with backfill

The system SHALL include a migration file
`infra/persistence/sql/migrations/004_add_allocated_node_id.sql` that adds the
`allocated_node_id` column to `yascheduler_tasks` and backfills it for all
existing tasks.

The migration SHALL execute, in one transaction:

1. `ALTER TABLE yascheduler_tasks ADD COLUMN allocated_node_id INTEGER
   REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL` — nullable FK;
   deleting a node nulls the task's `allocated_node_id` (the task row and
   `allocated_ip` are preserved).
2. `UPDATE yascheduler_tasks t SET allocated_node_id = (SELECT n.node_id FROM
   yascheduler_nodes n WHERE n.ip = t.ip) WHERE t.ip IS NOT NULL` — backfills
   `allocated_node_id` for every task with a non-NULL `ip` by joining on `ip`.
   Tasks with `ip IS NULL` (unallocated TO_DO) stay `allocated_node_id = NULL`.

The migration assumes `ip` is unique-or-NULL at migration time (the duplicate-IP
feature is not yet in production use). For a legacy deployment that already has
duplicate IPs, the `SELECT n.node_id ... WHERE n.ip = t.ip` subquery returns
one row arbitrarily (Postgres does not guarantee which); those rows get a
best-effort `allocated_node_id` and the read path (still ip until Surface A) is
unaffected.

The migration's `prefix_id` is `"004"`. It SHALL be recorded in
`yascheduler_migrations` after successful application. The `schema.sql` DO
block's `last_migration` CONSTANT SHALL be bumped from `'003'` to `'004'`
(see the `postgres-schema-apply` capability). The `schema.sql`
`CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement SHALL include the
`allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET
NULL` column (the latest snapshot includes all current columns).

#### Scenario: Migration 004 applies on a database with existing tasks
- **WHEN** `apply_migrations(config)` runs on a database at migration `003` with tasks having non-NULL `ip` values
- **THEN** the `ALTER TABLE` adds the nullable `allocated_node_id` column, the `UPDATE` backfills `allocated_node_id` by joining `yascheduler_nodes.ip = yascheduler_tasks.ip`, and a row `("004", <timestamp>)` is inserted into `yascheduler_migrations`

#### Scenario: Migration 004 leaves unallocated tasks with NULL allocated_node_id
- **WHEN** `apply_migrations(config)` runs and a task has `ip IS NULL` (unallocated TO_DO)
- **THEN** the `UPDATE` does not touch that row (the `WHERE t.ip IS NOT NULL` guard excludes it); its `allocated_node_id` stays `NULL`

#### Scenario: Migration 004 is recorded in the tracker
- **WHEN** migration `004_add_allocated_node_id.sql` applies successfully
- **THEN** `yascheduler_migrations` contains a row with `migration_id = "004"`

#### Scenario: Migration 004 failure rolls back
- **WHEN** migration `004_add_allocated_node_id.sql` raises an error mid-execution (e.g. the ALTER fails)
- **THEN** the transaction is rolled back, the error is re-raised, no row with `migration_id = "004"` is inserted into `yascheduler_migrations`, and the `allocated_node_id` column is NOT added

#### Scenario: Fresh database seeds to 004 and skips the migration
- **WHEN** `apply_schema(config)` runs on an empty database (no `yascheduler_nodes`, no `yascheduler_migrations`)
- **THEN** the DO block creates `yascheduler_migrations` and seeds it with `migration_id = "004"` (the `last_migration` CONSTANT); subsequent `apply_migrations` finds `MAX(migration_id) = "004"` and skips migration `004` (the `CREATE TABLE` already included the `allocated_node_id` column)

#### Scenario: FK ON DELETE SET NULL nulls allocated_node_id when node is removed
- **WHEN** a node row is deleted (`uow.nodes.remove(node_id)`) and a task references that node via `allocated_node_id`
- **THEN** the task's `allocated_node_id` is set to `NULL` by the FK `ON DELETE SET NULL` action; the task row, its `allocated_ip`, and all other columns are preserved

#### Scenario: Backfill handles unique-ip legacy rows
- **WHEN** `apply_migrations(config)` runs on a database where every task's `ip` matches exactly one node's `ip` (unique-ip deployment)
- **THEN** every task with a non-NULL `ip` gets `allocated_node_id` set to the matching node's `node_id`; no ambiguity

#### Scenario: Backfill on a dup-ip legacy row is best-effort
- **WHEN** `apply_migrations(config)` runs on a database where a task's `ip` matches multiple nodes' `ip` (legacy dup-IP, pre-feature)
- **THEN** the `SELECT n.node_id ... WHERE n.ip = t.ip` subquery returns one row arbitrarily; the task gets a best-effort `allocated_node_id`; the read path (still ip) is unaffected