## MODIFIED Requirements

### Requirement: SQL files organized by entity

The system SHALL store all SQL queries in `infra/persistence/sql/`
organized as `sql/<entity>/<operation>.sql`.

The task partial-update query (formerly `sql/task/upsert.sql`) SHALL be
named `sql/task/update_by_id.sql`, reflecting that it is an `UPDATE ...
WHERE task_id = :task_id ... RETURNING task_id` statement (a partial update
keyed by `task_id`), not an upsert. The task status-update query
`sql/task/update_status.sql` SHALL include a `RETURNING task_id` clause so
the repository can detect a 0-row outcome.

The node create query `sql/node/insert.sql` SHALL be an
`INSERT INTO yascheduler_nodes (...) VALUES (...) RETURNING node_id`
statement, so `PostgresNodeRepository.insert` can return the persisted
`Node` carrying the generated `NodeId` (mirroring
`sql/task/insert.sql RETURNING task_id`). The node by-id lookup SHALL live
at `sql/node/get_by_id.sql`. Every node SELECT (`get_by_ip`, `list_all`,
`get_by_ips`, `list_enabled`, `list_disabled`, `get_by_id`) SHALL include
`node_id` in its column list. `sql/node/list_all.sql` SHALL include
`ORDER BY node_id` for deterministic listing.

#### Scenario: Task query location
- **WHEN** a developer needs the SQL for getting a task by ID
- **THEN** it is found at `sql/task/get_by_id.sql`

#### Scenario: Task partial-update query location
- **WHEN** a developer needs the SQL for updating a task's mutable columns by `task_id`
- **THEN** it is found at `sql/task/update_by_id.sql` and contains `UPDATE yascheduler_tasks SET label = :label, status = :status, ip = :ip, metadata = :metadata WHERE task_id = :task_id RETURNING task_id`

#### Scenario: Task status-update query returns task_id
- **WHEN** `sql/task/update_status.sql` is executed against a row whose `task_id` exists
- **THEN** the statement returns the `task_id` of the updated row via `RETURNING task_id`, enabling the repository to detect a 0-row outcome

#### Scenario: Node query location
- **WHEN** a developer needs the SQL for listing enabled nodes
- **THEN** it is found at `sql/node/list_enabled.sql`

#### Scenario: Node by-id lookup location
- **WHEN** a developer needs the SQL for getting a node by its primary key
- **THEN** it is found at `sql/node/get_by_id.sql` and contains `WHERE node_id = :node_id`

#### Scenario: Node insert returns node_id
- **WHEN** `sql/node/insert.sql` is executed
- **THEN** it is an `INSERT ... VALUES (...) RETURNING node_id` statement, so the repository returns the persisted `Node`

#### Scenario: Node SELECTs include node_id
- **WHEN** any of `sql/node/get_by_ip.sql`, `list_all.sql`, `get_by_ips.sql`, `list_enabled.sql`, `list_disabled.sql`, `get_by_id.sql` is inspected
- **THEN** the column list includes `node_id` (so `_row_to_node` always receives it)

#### Scenario: Node list_all is ordered by node_id
- **WHEN** `sql/node/list_all.sql` is inspected
- **THEN** it contains `ORDER BY node_id` (deterministic listing for CLI output)
