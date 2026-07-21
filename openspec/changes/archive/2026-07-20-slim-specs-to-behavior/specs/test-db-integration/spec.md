## MODIFIED Requirements

### Requirement: Yascheduler query path integration against PostgreSQL

The project SHALL provide an integration test that exercises
`Yascheduler.queue_get_tasks` and `queue_get_task` against a real
PostgreSQL instance via testcontainers. The test SHALL submit a real task
via `Yascheduler().queue_submit_task(...)`, then query it back via both
`jobs=[task_id]` and `status=[0]` filters. The test SHALL assert the
public Mapping shape (keys exactly `{task_id, label, status, metadata,
node}`) and the expected values.

The test SHALL assert `status` by int value, by equality with a
`yascheduler.domain.TaskStatus` member, or by `.name`. The canonical
status type is `yascheduler.domain.TaskStatus`.

The test SHALL NOT patch any internal collaborator. It exercises the full
facade path through real Postgres.

#### Scenario: Query by jobs against real Postgres
- **WHEN** a task is submitted via `Yascheduler().queue_submit_task(...)` against the testcontainers Postgres and then `Yascheduler().queue_get_tasks(jobs=[task_id])` is called
- **THEN** the returned list contains one Mapping with exactly the five keys `{task_id, label, status, metadata, node}`, `task_id` matches, and `status` equals the TO_DO int value (0) or `domain.TaskStatus.TO_DO`

#### Scenario: Query by status against real Postgres
- **WHEN** the same task is queried via `Yascheduler().queue_get_tasks(status=[0])`
- **THEN** the task appears in the result with the correct five-key shape and matching `task_id`

#### Scenario: Single-task query returns Optional Mapping
- **WHEN** `Yascheduler().queue_get_task(task_id)` is called for an existing task
- **THEN** a single Mapping (not a list) with the five-key shape is returned; querying a non-existent id returns `None`
