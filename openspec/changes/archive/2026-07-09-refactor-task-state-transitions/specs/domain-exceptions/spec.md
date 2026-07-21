## MODIFIED Requirements

### Requirement: TaskError hierarchy

The system SHALL provide `TaskError(DomainError)` with subclasses:
`TaskNotTodoError`, `TaskNotRunningError`. Each SHALL take `task_id: TaskId`
(was `int`); the `f"task {task_id} ..."` message renders the bare integer via
`TaskId.__str__`, so the message text is unchanged in appearance.

`TaskAlreadyAllocatedError` and `TaskNotAllocatedError` are REMOVED. They
guarded the `TO_DO + allocated` intermediate state produced by the prior
`allocate_to` + `mark_running` two-step. With `run` collapsing allocation
and the `TO_DO→RUNNING` transition into one atomic method, allocation is
atomic with running and neither guard arises. The remaining
`TaskNotTodoError` (raised by `run` and `reject`) and `TaskNotRunningError`
(raised by `complete`, `fail`, `abandon`) cover all five transition guards.

#### Scenario: TaskNotTodoError carries TaskId
- **WHEN** `TaskNotTodoError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskNotRunningError carries TaskId
- **WHEN** `TaskNotRunningError(TaskId(42))` is raised
- **THEN** `e.task_id == TaskId(42)` and the message contains `"42"`

#### Scenario: TaskError messages render bare integer
- **WHEN** `str(TaskNotTodoError(TaskId(42)))` is evaluated
- **THEN** the result contains `"42"` (NOT `"TaskId(value=42)"`)