# postgres-repositories

## Purpose

PostgreSQL-backed repository implementations satisfying domain TaskRepository and NodeRepository ports.

## Requirements

### Requirement: PostgresTaskRepository implements TaskRepository

The system SHALL provide a `PostgresTaskRepository` class that satisfies
the `TaskRepository` Protocol with async methods: `get`, `save`, `insert`,
`update_status`, `list_by_status`, `list_by_jobs`,
`list_ids_by_ip_and_status`, `count_by_status`.

`save(task)` and `update_status(task_id, status)` SHALL execute an
`UPDATE yascheduler_tasks ... WHERE task_id = :task_id ... RETURNING task_id`
statement. When the UPDATE affects 0 rows (the targeted `task_id` does not
exist), they SHALL raise `TaskRowNotFoundError` (defined in
`yascheduler/infra/persistence/exceptions.py`). The row-existence check
SHALL happen BEFORE `save()` appends the task to the UoW's `_saved_tasks`
list, so a raise never leaves an orphan task in `_saved_tasks` that
`publish_events` would later dispatch events for.

#### Scenario: Get task by ID
- **WHEN** `get(42)` is called and a row with task_id=42 exists
- **THEN** returns a `Task` domain object with matching fields mapped from DB columns

#### Scenario: Get non-existent task
- **WHEN** `get(999)` is called and no such row exists
- **THEN** returns `None`

#### Scenario: Save task updates all columns
- **WHEN** `save(task)` is called with an existing task_id
- **THEN** all columns (label, status, ip, metadata) are updated in the DB row

#### Scenario: Save non-existent task raises
- **WHEN** `save(task)` is called with a `task.task_id` that does not exist in `yascheduler_tasks`
- **THEN** `TaskRowNotFoundError` is raised and the task is NOT appended to the UoW's `_saved_tasks` list

#### Scenario: Insert returns task with generated ID
- **WHEN** `insert(task)` is called with task_id=0
- **THEN** a new row is inserted and a Task with the DB-generated task_id is returned

#### Scenario: Update status atomically
- **WHEN** `update_status(42, TaskStatus.RUNNING)` is called and a row with task_id=42 exists
- **THEN** only the status column is updated; other fields are preserved

#### Scenario: Update status non-existent task raises
- **WHEN** `update_status(999, TaskStatus.RUNNING)` is called and no row with task_id=999 exists
- **THEN** `TaskRowNotFoundError` is raised

#### Scenario: List tasks by status
- **WHEN** `list_by_status({TaskStatus.TO_DO, TaskStatus.RUNNING})` is called
- **THEN** returns all tasks with those statuses, mapped to domain `Task` objects

#### Scenario: List tasks by job IDs
- **WHEN** `list_by_jobs([1, 2, 3])` is called
- **THEN** returns tasks whose task_id is in the given list

#### Scenario: List IDs by IP and status
- **WHEN** `list_ids_by_ip_and_status("10.0.0.1", TaskStatus.RUNNING)` is called
- **THEN** returns task IDs matching both IP and status

#### Scenario: Count tasks by status
- **WHEN** `count_by_status()` is called
- **THEN** returns a mapping of TaskStatus to task count

### Requirement: PostgresNodeRepository implements NodeRepository

The system SHALL provide a `PostgresNodeRepository` class that satisfies
the `NodeRepository` Protocol with async methods: `get`, `list_enabled`,
`list_disabled`, `list_all`, `add`, `add_tmp`, `update`, `enable`,
`disable`, `remove`, `get_by_ips`, `count_by_cloud`, `count_by_status`.

`add_tmp(cloud: str) -> str` inserts a tmp-node row with a generated IP,
`enabled=FALSE`, the given cloud, and `username` left to the DB default
(`yascheduler_nodes.username DEFAULT 'root'`). It SHALL NOT bind a
`:username` parameter; the `node/insert_tmp.sql` query lists only
`(ip, enabled, cloud)` columns.

#### Scenario: Add and retrieve node
- **WHEN** `add(node)` is called followed by `get(ip)`
- **THEN** the returned Node matches the inserted values

#### Scenario: Enable and disable node
- **WHEN** `disable(ip)` is called on an enabled node, then `get(ip)`
- **THEN** `node.enabled` is False

#### Scenario: List enabled nodes
- **WHEN** `list_enabled()` is called with a mix of enabled and disabled nodes
- **THEN** returns only nodes with `enabled=True` and valid IPs (containing ".")

#### Scenario: List all nodes
- **WHEN** `list_all()` is called
- **THEN** returns all nodes regardless of enabled status

#### Scenario: Add temporary node
- **WHEN** `add_tmp(cloud)` is called
- **THEN** a node row is inserted with generated IP, the given cloud, and `username` defaulting to `'root'` (from the DB column default, not a caller-supplied value)

#### Scenario: Update node fields
- **WHEN** `update(node)` is called with modified fields
- **THEN** all mutable fields are persisted

#### Scenario: Get nodes by IPs
- **WHEN** `get_by_ips(["10.0.0.1", "10.0.0.2"])` is called
- **THEN** returns a dict keyed by IP for matching nodes

#### Scenario: Count by cloud
- **WHEN** `count_by_cloud()` is called
- **THEN** returns a mapping of cloud provider name to node count

#### Scenario: Count by status
- **WHEN** `count_by_status()` is called
- **THEN** returns a mapping of enabled (bool) to node count

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

### Requirement: All methods avoid blocking the event loop

All repository methods SHALL be async and dispatch synchronous pg8000 calls
through a ThreadPoolExecutor to avoid blocking the event loop.

#### Scenario: Async method does not block
- **WHEN** `get(task_id)` is called from an async context
- **THEN** the event loop is not blocked during the database call
