## MODIFIED Requirements

### Requirement: PostgresTaskRepository implements TaskRepository

The system SHALL provide a `PostgresTaskRepository` class that satisfies
the `TaskRepository` Protocol with async methods: `get`, `save`, `insert`,
`update_status`, `list_by_status`, `list_by_jobs`,
`list_ids_by_ip_and_status`, `count_by_status`.

`save(task)` and `update_status(task_id, status)` SHALL execute an
`UPDATE yascheduler_tasks ... WHERE task_id = :task_id ... RETURNING task_id`
statement, passing `task_id=task.task_id.value` / `task_id=task_id.value` as the
SQL param (pg8000 cannot adapt a `TaskId` dataclass — the `.value` unwrap is
required). When the UPDATE affects 0 rows (the targeted `task_id` does not
exist), they SHALL raise `TaskRowNotFoundError` (defined in
`yascheduler/infra/persistence/exceptions.py`, taking `task_id: TaskId`). The
row-existence check SHALL happen BEFORE `save()` appends the task to the UoW's
`_saved_tasks` list, so a raise never leaves an orphan task in `_saved_tasks`
that `publish_events` would later dispatch events for.

`insert(new_task: NewTask) -> Task` SHALL run `task/insert.sql ... RETURNING
task_id, label, ip, status, metadata` (already present) and return
`_row_to_task(rows[0])` — which wraps `TaskId(int(row["task_id"]))`. The
`new_task.task_id` is ignored (there is none — `NewTask` has no identity); the
DB generates the id. Returning the full `Task` (not just `TaskId`) avoids a
second `get` round-trip in `submit_task`.

`get(task_id: TaskId)` SHALL pass `task_id=task_id.value` to
`task/get_by_id.sql`. `list_ids_by_ip_and_status` SHALL return
`[TaskId(int(row["task_id"])) for row in rows]`. `list_by_jobs(job_ids:
list[TaskId])` SHALL pass `[tid.value for tid in job_ids]` as the SQL param and
return `[self._row_to_task(r) for r in rows]`. `_row_to_task` SHALL wrap
`TaskId(int(row["task_id"]))` when building each `Task`.

#### Scenario: Get task by ID
- **WHEN** `get(TaskId(42))` is called and a row with task_id=42 exists
- **THEN** returns a `Task` domain object with `task_id=TaskId(42)` and matching fields mapped from DB columns

#### Scenario: Get non-existent task
- **WHEN** `get(TaskId(999))` is called and no such row exists
- **THEN** returns `None`

#### Scenario: Save task updates all columns
- **WHEN** `save(task)` is called with an existing `task.task_id` (a `TaskId`)
- **THEN** all columns (label, status, ip, metadata) are updated in the DB row; the SQL param is `task.task_id.value`

#### Scenario: Save non-existent task raises
- **WHEN** `save(task)` is called with a `task.task_id` (a `TaskId`) that does not exist in `yascheduler_tasks`
- **THEN** `TaskRowNotFoundError` is raised (carrying the `TaskId`) and the task is NOT appended to the UoW's `_saved_tasks` list

#### Scenario: Insert returns Task with generated TaskId
- **WHEN** `insert(NewTask(label="job", context=ctx))` is called
- **THEN** a new row is inserted and a `Task` with the DB-generated `task_id=TaskId(int(row["task_id"]))` is returned (the `NewTask` had no `task_id`)

#### Scenario: Update status atomically
- **WHEN** `update_status(TaskId(42), TaskStatus.RUNNING)` is called and a row with task_id=42 exists
- **THEN** only the status column is updated; the SQL param is `task_id.value` (= 42)

#### Scenario: Update status non-existent task raises
- **WHEN** `update_status(TaskId(999), TaskStatus.RUNNING)` is called and no row with task_id=999 exists
- **THEN** `TaskRowNotFoundError` is raised (carrying `TaskId(999)`)

#### Scenario: List tasks by status
- **WHEN** `list_by_status({TaskStatus.TO_DO, TaskStatus.RUNNING})` is called
- **THEN** returns all tasks with those statuses, mapped to domain `Task` objects (each carrying a `TaskId`)

#### Scenario: List tasks by job IDs
- **WHEN** `list_by_jobs([TaskId(1), TaskId(2), TaskId(3)])` is called
- **THEN** returns tasks whose task_id is in the given list; the SQL param is `[1, 2, 3]` (the `.value` of each `TaskId`)

#### Scenario: List IDs by IP and status returns TaskIds
- **WHEN** `list_ids_by_ip_and_status("10.0.0.1", TaskStatus.RUNNING)` is called
- **THEN** returns a `list[TaskId]` (each `TaskId(int(row["task_id"]))`), NOT a `list[int]`

#### Scenario: Count tasks by status
- **WHEN** `count_by_status()` is called
- **THEN** returns a mapping of TaskStatus to task count

#### Scenario: _row_to_task wraps TaskId
- **WHEN** `_row_to_task(row)` is called with a row whose `task_id` is the int `7`
- **THEN** the returned `Task` has `task_id=TaskId(7)`