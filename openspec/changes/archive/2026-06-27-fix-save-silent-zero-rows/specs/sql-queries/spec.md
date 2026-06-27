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

### Requirement: Lazy SQL loading with caching

The system SHALL provide a `load_query(name: str) -> str` function that
reads `.sql` files from the package directory and caches the result
so each file is read at most once per process.

#### Scenario: First load reads from disk
- **WHEN** `load_query("task/get_by_id")` is called for the first time
- **THEN** the file `sql/task/get_by_id.sql` is read and its contents returned

#### Scenario: Subsequent load uses cache
- **WHEN** `load_query("task/get_by_id")` is called a second time
- **THEN** the file is NOT re-read; the cached string is returned

#### Scenario: Renamed partial-update query loads under new name
- **WHEN** `load_query("task/update_by_id")` is called
- **THEN** the file `sql/task/update_by_id.sql` is returned (the previous `load_query("task/upsert")` reference is updated to the new name)

### Requirement: pg8000 named parameter syntax

The system SHALL use `:param_name` syntax in SQL files for pg8000
parameter binding.

#### Scenario: Parameterized query
- **WHEN** a query file contains `WHERE task_id = :task_id`
- **THEN** the repository passes `task_id=42` and pg8000 binds the value