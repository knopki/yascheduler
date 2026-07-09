## ADDED Requirements

### Requirement: Migration 011 adds the task_status_field_invariants CHECK constraint

Migration 011 SHALL add a `CHECK` constraint named `task_status_field_invariants` to `yascheduler_tasks` enforcing the exhaustive per-status field contract; see
`yascheduler/infra/persistence/sql/migrations/011_task_status_field_check.sql`
for exact SQL. The constraint SHALL be:

```sql
ALTER TABLE yascheduler_tasks ADD CONSTRAINT task_status_field_invariants CHECK (
    (status = 'TO_DO'   AND allocated_node_id IS NULL     AND error IS NULL)
 OR (status = 'RUNNING' AND allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL)
 OR (status = 'DONE')
);
```

The migration SHALL NOT include a defensive pre-clean `UPDATE` before `ADD CONSTRAINT`: the audit confirmed no production path creates the forbidden states, so `ADD CONSTRAINT` succeeds on existing data; if that assumption breaks the constraint fails fast at migration time, surfacing the offending row rather than masking it.

#### Scenario: Migration 011 adds the CHECK constraint
- **WHEN** `apply_migrations(config)` runs with a last-applied id of `"010"`
- **THEN** the `ALTER TABLE yascheduler_tasks ADD CONSTRAINT task_status_field_invariants CHECK (...)` is applied, the constraint is visible in `information_schema.table_constraints`, and a row `("011", <timestamp>)` is inserted into `yascheduler_migrations`

#### Scenario: Migration 011 succeeds on clean production data
- **WHEN** `apply_migrations(config)` runs on a database where no row in `yascheduler_tasks` has a forbidden (status, allocated_node_id, error, remote_folder) combination
- **THEN** the `ADD CONSTRAINT` succeeds and the migration is recorded

#### Scenario: Migration 011 fails fast on a forbidden row
- **WHEN** `apply_migrations(config)` runs on a database where some row violates the CHECK (e.g. a `TO_DO` row with non-NULL `allocated_node_id`)
- **THEN** the `ADD CONSTRAINT` raises a violation error naming the offending row, the transaction is rolled back, and no row for `"011"` is inserted into `yascheduler_migrations`

#### Scenario: The CHECK refuses a forbidden insert after migration
- **WHEN** an `INSERT INTO yascheduler_tasks (status, allocated_node_id, error, remote_folder)` produces a row with `status='TO_DO'` and `allocated_node_id IS NOT NULL`
- **THEN** the insert raises a CHECK violation referencing `task_status_field_invariants`

#### Scenario: The CHECK refuses a forbidden update after migration
- **WHEN** an `UPDATE yascheduler_tasks SET allocated_node_id = NULL WHERE status='RUNNING'` is attempted on a RUNNING row
- **THEN** the update raises a CHECK violation referencing `task_status_field_invariants`

#### Scenario: The CHECK refuses a bare node DELETE that would orphan a RUNNING task
- **WHEN** a `DELETE FROM yascheduler_nodes` is issued on a node that still has a row in `yascheduler_tasks` with `status='RUNNING'` and `allocated_node_id = <that node's node_id>`
- **THEN** the `ON DELETE SET NULL` cascade attempts to set `allocated_node_id = NULL` on the RUNNING row, the `task_status_field_invariants` CHECK rejects it (RUNNING requires `allocated_node_id IS NOT NULL`), and the DELETE is rolled back

#### Scenario: Hard-remove path is unaffected by the CHECK
- **WHEN** `_remove_node_hard` flips each RUNNING task to `DONE` via `update_status(task_id, DONE)` and then calls `nodes.remove(node_id)`
- **THEN** the rows are `DONE` by the time the `ON DELETE SET NULL` cascade fires, `DONE` permits NULL `allocated_node_id`, and neither the `update_status` nor the `nodes.remove` raises a CHECK violation