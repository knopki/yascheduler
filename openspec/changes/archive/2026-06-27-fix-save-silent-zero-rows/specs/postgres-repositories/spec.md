## MODIFIED Requirements

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