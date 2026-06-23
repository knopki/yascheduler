## MODIFIED Requirements

### Requirement: SQL files organized by entity

The system SHALL store all SQL queries in `infra/persistence/sql/`
organized as `sql/<entity>/<operation>.sql`.

#### Scenario: Task query location
- **WHEN** a developer needs the SQL for getting a task by ID
- **THEN** it is found at `sql/task/get_by_id.sql`

#### Scenario: Node query location
- **WHEN** a developer needs the SQL for listing enabled nodes
- **THEN** it is found at `sql/node/list_enabled.sql`
