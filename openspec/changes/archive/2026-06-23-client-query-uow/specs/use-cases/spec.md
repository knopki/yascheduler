## ADDED Requirements

### Requirement: QueryTasks use case

The system SHALL provide a `query_tasks` async function that returns
domain `Task` aggregates matching a jobs- or statuses-based read query.
The function SHALL accept `jobs: Sequence[int] | None`, `statuses:
Sequence[TaskStatus] | None`, and `uow_factory: Callable[[],
AbstractUnitOfWork]`. It SHALL raise `ValueError` if both `jobs` and
`statuses` are supplied. It SHALL open a single Unit of Work, dispatch to
`uow.tasks.list_by_status(set(statuses))` when `statuses` is non-empty or
`uow.tasks.list_by_jobs(list(jobs))` when `jobs` is non-empty, and
return `[]` when neither is non-empty (truthiness semantics, matching
`yascheduler.client.queue_get_tasks_async`'s existing dispatch). It SHALL
NOT call `uow.commit` (read-only). It SHALL NOT import from
`yascheduler.adapters` at runtime.

#### Scenario: Query by statuses dispatches to list_by_status
- **WHEN** `query_tasks(jobs=None, statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_status({TaskStatus.TO_DO})` is awaited, the UoW closes without `commit`, and the returned `list[Task]` is forwarded to the caller

#### Scenario: Query by jobs dispatches to list_by_jobs
- **WHEN** `query_tasks(jobs=[1, 2, 3], statuses=None, uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_jobs([1, 2, 3])` is awaited, the UoW closes without `commit`, and the returned `list[Task]` is forwarded to the caller

#### Scenario: Both jobs and statuses supplied raises ValueError
- **WHEN** `query_tasks(jobs=[1], statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** `ValueError` is raised and no UoW is opened

#### Scenario: Neither jobs nor statuses returns empty list
- **WHEN** `query_tasks(jobs=None, statuses=None, uow_factory=f)` is called
- **THEN** `[]` is returned without dispatching to either repository method and without opening a UoW

#### Scenario: Use case is read-only
- **WHEN** `query_tasks(jobs=[1], statuses=None, uow_factory=f)` runs to completion successfully
- **THEN** `uow.commit()` is never called on the opened UoW
