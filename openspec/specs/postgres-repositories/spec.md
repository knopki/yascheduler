# postgres-repositories

## Purpose

PostgreSQL-backed repository implementations satisfying domain TaskRepository and NodeRepository ports.

## Requirements

### Requirement: PostgresTaskRepository implements TaskRepository

The system SHALL provide a `PostgresTaskRepository` class that satisfies
the `TaskRepository` Protocol with async methods: `get`, `save`,
`list_by_status`.

#### Scenario: Get task by ID
- **WHEN** `get(42)` is called and a row with task_id=42 exists
- **THEN** returns a `Task` domain object with matching fields mapped from DB columns

#### Scenario: Get non-existent task
- **WHEN** `get(999)` is called and no such row exists
- **THEN** returns `None`

#### Scenario: Save task updates all columns
- **WHEN** `save(task)` is called with an existing task_id
- **THEN** all columns (label, status, ip, metadata) are updated in the DB row

#### Scenario: List tasks by status
- **WHEN** `list_by_status({TaskStatus.TO_DO, TaskStatus.RUNNING})` is called
- **THEN** returns all tasks with those statuses, mapped to domain `Task` objects

### Requirement: PostgresNodeRepository implements NodeRepository

The system SHALL provide a `PostgresNodeRepository` class that satisfies
the `NodeRepository` Protocol with async methods: `get`, `list_enabled`,
`list_disabled`, `add`, `add_tmp`, `update`, `enable`, `disable`, `remove`.

#### Scenario: Add and retrieve node
- **WHEN** `add(node)` is called followed by `get(ip)`
- **THEN** the returned Node matches the inserted values

#### Scenario: Enable and disable node
- **WHEN** `disable(ip)` is called on an enabled node, then `get(ip)`
- **THEN** `node.enabled` is False

#### Scenario: List enabled nodes
- **WHEN** `list_enabled()` is called with a mix of enabled and disabled nodes
- **THEN** returns only nodes with `enabled=True`

#### Scenario: Add temporary node
- **WHEN** `add_tmp(cloud, username)` is called
- **THEN** a node row is inserted with generated IP, given cloud and username

#### Scenario: Remove node
- **WHEN** `remove(ip)` is called
- **THEN** the node row is deleted from the database

### Requirement: JSONB metadata roundtrip

The system SHALL serialize `TaskContext` to/from JSONB metadata correctly
for all known fields (`engine`, `remote_folder`, `local_folder`, `webhook_url`,
`webhook_custom_params`, `error`) and preserve unknown keys in `extra`.

#### Scenario: Roundtrip known fields
- **WHEN** a Task with `context.engine="fleur"` and `context.webhook_url="https://..."` is saved and then retrieved
- **THEN** the retrieved TaskContext has the same values

#### Scenario: Preserve extra keys
- **WHEN** a TaskContext has `extra={"fort.9": "base64data"}` is saved and retrieved
- **THEN** `extra["fort.9"]` equals "base64data"

### Requirement: All methods are non-blocking

All repository methods SHALL be async and SHALL NOT block the event loop
during database operations.

#### Scenario: Async method does not block
- **WHEN** `get(task_id)` is called from an async context
- **THEN** the event loop is not blocked during the database call
