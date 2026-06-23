## ADDED Requirements

### Requirement: Client queue-query unit verification

Tests SHALL verify that `Yascheduler.queue_get_tasks_async` (in
`yascheduler/client.py`) routes queries through the `deps_factory`-injected
`CLIDeps.uow_factory` and the `query_tasks` use case, then maps results to
the public six-key dict shape. Tests SHALL construct the client with a
`FakeCLIDeps`-returning `deps_factory` whose `uow_factory()` returns a
`FakeUnitOfWork` carrying a `FakeTaskRepository`.

#### Scenario: Status filter dispatches list_by_status
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(status=[0])` is called with `FakeTaskRepository.list_by_status` seeded to return a known Task
- **THEN** `list_by_status({domain.TaskStatus.TO_DO})` is awaited and the returned dict has exactly the keys `{task_id, label, ip, status, metadata, cloud}`

#### Scenario: Jobs filter dispatches list_by_jobs
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(jobs=[7])` is called
- **THEN** `list_by_jobs([7])` is awaited on the fake repository and results mapped to the six-key shape

#### Scenario: Both filters supplied raises ValueError
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(jobs=[1], status=[0])` is called
- **THEN** `ValueError` is raised

#### Scenario: Neither filter returns empty list
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async()` is called with no arguments
- **THEN** `[]` is returned without dispatching to the repository

#### Scenario: Returned dict shape and types are correct
- **WHEN** a Task with `allocated_ip=None` is seeded into the fake repository and queried
- **THEN** the returned dict has `ip == ""`, `status` is `isinstance(status, domain.TaskStatus)` (not a plain int), and `cloud is None`
