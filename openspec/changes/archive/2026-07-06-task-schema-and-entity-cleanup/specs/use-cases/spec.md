# Delta: use-cases

## MODIFIED Requirements

### Requirement: QueryTasks use case

The system SHALL provide a `query_tasks` async function that returns
domain `Task` aggregates matching a jobs- or statuses-based read query,
alongside a `dict[NodeId, Node]` of the nodes allocated to those tasks (for
the caller to project a nested `node` field). The function SHALL accept
`jobs: Sequence[TaskId] | None` (was `Sequence[int] | None`), `statuses:
Sequence[TaskStatus] | None`, and `uow_factory: Callable[[], AbstractUnitOfWork]`.
It SHALL raise `ValueError` if both `jobs` and `statuses` are supplied. It
SHALL open a single Unit of Work, dispatch to `uow.tasks.list_by_status(set(statuses))`
when `statuses` is non-empty or `uow.tasks.list_by_jobs(list(jobs))` (a
`list[TaskId]`) when `jobs` is non-empty, and return `([], {})` when neither
is non-empty (truthiness semantics, matching `yascheduler.client.queue_get_tasks_async`'s
existing dispatch). It SHALL NOT call `uow.commit` (read-only). It SHALL NOT
import from `yascheduler.infra` at runtime.

Within the same single UoW, after fetching tasks, the use case SHALL
batch-load the nodes allocated to those tasks via
`uow.nodes.get_by_ids(list({t.allocated_node_id for t in tasks if
t.allocated_node_id is not None}))` (a single batch round-trip), building
`nodes_by_id: dict[NodeId, Node]`. When no task has an `allocated_node_id`
(all tasks are unallocated), the use case SHALL skip the `get_by_ids` call
and return `(tasks, {})`. The use case SHALL return the tuple
`(tasks, nodes_by_id)`.

The return type widens from `list[Task]` to `tuple[list[Task], dict[NodeId,
Node]]`. This is the only signature change. The use case does NOT project
the nested `node` dict — that is the caller's concern (the
`Yascheduler` facade's `_task_to_dict` projects it; see the `package-facades`
capability). The use case opens the UoW; the facade does not open its own
UoW.

The public `Yascheduler.queue_get_tasks_async(jobs: list[int])` facade is the
sole `int`/`TaskId` boundary on this path: it wraps `[TaskId(i) for i in jobs]`
before calling `query_tasks(jobs=[TaskId(...)], ...)`. The facade unpacks the
returned tuple and forwards `nodes_by_id` to `_task_to_dict`.

#### Scenario: Query by statuses dispatches to list_by_status and loads nodes
- **WHEN** `query_tasks(jobs=None, statuses=[TaskStatus.RUNNING], uow_factory=f)` is called and a RUNNING task with `allocated_node_id=NodeId(7)` exists
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_status({TaskStatus.RUNNING})` is awaited, `uow.nodes.get_by_ids([NodeId(7)])` is awaited (a single batch round-trip), the UoW closes without `commit`, and the returned tuple is `(list[Task], {NodeId(7): Node(...)})`

#### Scenario: Query by jobs dispatches to list_by_jobs and loads nodes
- **WHEN** `query_tasks(jobs=[TaskId(1), TaskId(2), TaskId(3)], statuses=None, uow_factory=f)` is called and tasks with `allocated_node_id` set exist
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_jobs([TaskId(1), TaskId(2), TaskId(3)])` is awaited, `uow.nodes.get_by_ids([...])` is awaited with the distinct non-None `allocated_node_id` values, the UoW closes without `commit`, and the returned tuple is `(list[Task], dict[NodeId, Node])`

#### Scenario: Both jobs and statuses raises ValueError
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** `ValueError` is raised and no UoW is opened

#### Scenario: Neither jobs nor statuses returns empty tuple
- **WHEN** `query_tasks(jobs=None, statuses=None, uow_factory=f)` is called
- **THEN** `([], {})` is returned and no UoW is opened

#### Scenario: All tasks unallocated returns empty nodes dict
- **WHEN** `query_tasks(jobs=None, statuses=[TaskStatus.TO_DO], uow_factory=f)` is called and all matching tasks have `allocated_node_id=None`
- **THEN** the UoW is opened, `uow.tasks.list_by_status({TaskStatus.TO_DO})` is awaited, `uow.nodes.get_by_ids` is NOT called (the set of `allocated_node_id` is empty), and the returned tuple is `(list[Task], {})`

#### Scenario: Use case does not commit
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` runs to completion successfully
- **THEN** `uow.commit()` is never called (read-only use case); the UoW context manager closes the connection without committing

#### Scenario: Distinct allocated_node_ids are batch-loaded once
- **WHEN** `query_tasks` fetches tasks with `allocated_node_id` values `[NodeId(7), NodeId(7), NodeId(8), None]`
- **THEN** `uow.nodes.get_by_ids([NodeId(7), NodeId(8)])` is called exactly once with the deduplicated non-None node ids (NOT once per task; NOT including `None`)

#### Scenario: Use case does not import from infra at runtime
- **WHEN** the `query_tasks.py` module is inspected
- **THEN** no `from yascheduler.infra...` import appears at runtime (only under `TYPE_CHECKING` if needed for type hints)