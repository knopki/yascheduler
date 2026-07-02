## MODIFIED Requirements

### Requirement: TaskRepository port

The system SHALL define a `TaskRepository` Protocol with async methods:
`get(task_id: TaskId) -> Task | None`, `save(task: Task) -> None`,
`insert(new_task: NewTask) -> Task`,
`list_by_status(statuses: set[TaskStatus], *, limit: int | None = None) -> list[Task]`,
`list_by_jobs(job_ids: list[TaskId]) -> list[Task]`,
`update_status(task_id: TaskId, status: TaskStatus) -> None`,
`list_ids_by_ip_and_status(ip: str, status: TaskStatus) -> list[TaskId]`,
`count_by_status() -> Mapping[TaskStatus, int]`.

`insert` takes `NewTask` (pre-persistence) and returns `Task` (post-persistence,
carrying the generated `TaskId`); it is the sole `NewTask → Task` conversion
site. `get`, `update_status`, `list_ids_by_ip_and_status` (return), and
`list_by_jobs` (input) use `TaskId` — the domain is type-safe end-to-end. The
public `Yascheduler` facade (see `package-facades`) is the sole `int`/`TaskId`
boundary: it wraps `TaskId(int)` on input and extracts `.value` on output.

The `TaskRepository` Protocol SHALL define an async `list_by_status` method
with an optional `limit` parameter for bounded queries. `save`,
`list_by_status`, and `count_by_status` are unchanged in signature (they
take/return `Task` / mappings, which carry `TaskId` internally).

#### Scenario: Repository method signatures are async
- **WHEN** a class implements `TaskRepository` with matching async method signatures
- **THEN** it satisfies the Protocol structurally

#### Scenario: List tasks by status without limit
- **WHEN** `list_by_status({TaskStatus.TO_DO})` is called
- **THEN** returns all tasks with TO_DO status (each `Task` carries a `TaskId`)

#### Scenario: List tasks by status with limit
- **WHEN** `list_by_status({TaskStatus.TO_DO}, limit=10)` is called
- **THEN** returns at most 10 tasks with TO_DO status

#### Scenario: insert converts NewTask to Task
- **WHEN** `insert(new_task)` is called with a `NewTask` (no `task_id`)
- **THEN** a `Task` carrying the DB-generated `TaskId` is returned (the sole `NewTask → Task` conversion)

#### Scenario: get takes TaskId
- **WHEN** `get(TaskId(42))` is called
- **THEN** returns a `Task` (with `task_id: TaskId`) or `None`

#### Scenario: update_status takes TaskId
- **WHEN** `update_status(TaskId(42), TaskStatus.RUNNING)` is called
- **THEN** the status of the task with `task_id=42` is updated (the `TaskId` is the key)

#### Scenario: list_ids_by_ip_and_status returns TaskIds
- **WHEN** `list_ids_by_ip_and_status("10.0.0.1", TaskStatus.RUNNING)` is called
- **THEN** returns a `list[TaskId]` (not `list[int]`); the caller feeds them directly to `update_status(TaskId, ...)`

#### Scenario: list_by_jobs takes TaskIds
- **WHEN** `list_by_jobs([TaskId(1), TaskId(2), TaskId(3)])` is called
- **THEN** returns tasks whose `task_id` is in the given list of `TaskId`s