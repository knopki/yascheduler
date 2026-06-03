## ADDED Requirements

### Requirement: SQL files organized by entity

The system SHALL store all SQL queries in `adapters/persistence/sql/`
organized as `sql/<entity>/<operation>.sql`.

#### Scenario: Task query location
- **WHEN** a developer needs the SQL for getting a task by ID
- **THEN** it is found at `sql/task/get_by_id.sql`

#### Scenario: Node query location
- **WHEN** a developer needs the SQL for listing enabled nodes
- **THEN** it is found at `sql/node/list_enabled.sql`

### Requirement: Lazy SQL loading with caching

The system SHALL provide a `load_query(name: str) -> str` function that
reads `.sql` files from the package directory and caches the result with
`@functools.cache`.

#### Scenario: First load reads from disk
- **WHEN** `load_query("task/get_by_id")` is called for the first time
- **THEN** the file `sql/task/get_by_id.sql` is read and its contents returned

#### Scenario: Subsequent load uses cache
- **WHEN** `load_query("task/get_by_id")` is called a second time
- **THEN** the file is NOT re-read; the cached string is returned

### Requirement: pg8000 named parameter syntax

The system SHALL use `:param_name` syntax in SQL files for pg8000
parameter binding.

#### Scenario: Parameterized query
- **WHEN** a query file contains `WHERE task_id = :task_id`
- **THEN** the repository passes `task_id=42` and pg8000 binds the value

### Requirement: schema.sql as authoritative DDL

The system SHALL copy the DDL from `data/schema.sql` to
`adapters/persistence/sql/schema.sql` as the authoritative schema source.

#### Scenario: Schema file location
- **WHEN** a developer needs the current database schema
- **THEN** it is at `adapters/persistence/sql/schema.sql`
