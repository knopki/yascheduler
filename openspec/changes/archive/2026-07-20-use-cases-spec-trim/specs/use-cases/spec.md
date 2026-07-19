# Delta: use-cases

## MODIFIED Requirements

### Requirement: SubmitTask use case

The system SHALL provide a `submit_task` async function that creates a new
task in the database after validating the engine and inputs. The function
SHALL return the generated `TaskId`.

#### Scenario: Successful task submission

- **WHEN** `submit_task(...)` is called with valid inputs
- **THEN** a `NewTask` is constructed, persisted via `uow.tasks.insert` → `Task`, saved, committed, and the `TaskId` is returned; the persisted task has status `TO_DO` and `remote_folder=None`

#### Scenario: Unsupported engine

- **WHEN** `submit_task(...)` is called with an `engine_name` not in the `EngineRepository`
- **THEN** `UnsupportedEngineError` is raised before any DB write

#### Scenario: Submit constructs NewTask, not Task

- **WHEN** `submit_task(...)` builds the pre-persistence record
- **THEN** it constructs `NewTask(...)` (no `task_id=0` sentinel, no `remote_folder`, no `error`)

#### Scenario: Submit does not construct TaskCreated

- **WHEN** `submit_task(...)` is inspected for `TaskCreated` construction or `with_event` / `record_event` calls
- **THEN** none are present; `TaskCreated` is attached by `uow.tasks.insert` internally

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free compatible machine or requests cloud provisioning.
Provider selection is delegated to `clouds.select_provider`. The
`allocation_lock` SHALL serialize the capacity-read through tmp-insert
sequence so concurrent `allocate_task` calls for overlapping capacity do not
over-provision. On any failure path inside the cloud-fallback critical
section, the tmp-node row SHALL be cleaned up via `uow.nodes.remove`.

#### Scenario: Successful allocation to a free machine

- **WHEN** `allocate_task(...)` is called and a free compatible machine exists
- **THEN** the task transitions TO_DO → RUNNING via `task.run(node.node_id, remote_folder)` (emitting `TaskAllocated` inline), the occupancy check is started, the task is saved and committed, and the function returns `True`

#### Scenario: No free machine matches, cloud-fallback attempted

- **WHEN** `allocate_task(...)` is called and no free compatible machine matches
- **THEN** the cloud-fallback path is attempted (tracker dedup, capacity check under `allocation_lock`, provider selection via `clouds.select_provider`, tmp-node insert, cloud allocation, final node persistence); the function returns `False` whether the cloud path initiated provisioning or no provider was available

#### Scenario: Duplicate allocation rejected by tracker

- **WHEN** `allocate_task(...)` is called for a `task_id` already in the `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns `False` and the cloud-fallback path returns immediately without inserting a tmp node or writing to the DB

#### Scenario: Unsupported engine rejected via task.reject

- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the use case calls `task.reject("unsupported engine")` (emitting `TaskFailed` inline), saves, commits, and the function returns `False`

#### Scenario: Empty-platforms engine short-circuits cloud-fallback

- **WHEN** `allocate_task(...)` is called for a task whose `engine.platforms` is empty and no free machine matched
- **THEN** the use case logs a warning and returns `False` without entering the cloud-fallback critical section

#### Scenario: Occupancy check started via occupancy_checker

- **WHEN** `allocate_task(...)` successfully starts a task on a machine
- **THEN** `occupancy_checker.start_occupancy_check(session, engine)` is called

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance and returns the disabled `Node` objects
so the orchestrator can delete the VMs. The system SHALL also provide a
`deallocate_node` async helper that performs the per-node teardown (SSH
disconnect, DB disable, cloud delete, DB remove) for a single node.

`deallocate_nodes` SHALL return `list[Node]`. The returned `Node` objects
SHALL each carry their `node_id` so the orchestrator can call
`deallocate_node(node, ...)` directly without a DB round-trip.

#### Scenario: Idle cloud node disabled

- **WHEN** `deallocate_nodes(...)` is called and an enabled cloud node's free-since timestamp exceeds its config's `idle_tolerance`
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the `Node` is included in the returned `list[Node]`

#### Scenario: Returns disabled Node objects carrying node_id

- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a `list[Node]` is returned; each returned `Node` is a disabled cloud node whose `node_id` is not in `busy_node_ids`

#### Scenario: Deallocate node brackets cloud delete with disable + remove

- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` is called for a cloud node
- **THEN** SSH disconnect runs first (only if `repository.contains(node.node_id)`), then `uow.nodes.disable` + commit, then `clouds.deallocate(node)`, then `uow.nodes.remove` + commit

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function that cleans up a
cloud node that never established its SSH connection, releasing any tracker
entries linked to that node. The function SHALL accept `node`, `clouds`,
`uow_factory`, and `tracker`.

Cloud VM deletion (`clouds.deallocate(node)`) SHALL be best-effort: failures
SHALL be logged with `node_id`, `hostname`, `cloud`, and the exception; the
subsequent DB-row removal SHALL proceed regardless of the cloud-deletion
outcome. DB-row removal (`uow.nodes.remove(node.node_id)`) failure SHALL be
logged with `node_id`, `hostname`, and the exception and re-raised. Tracker
cleanup SHALL run via `tracker.discard_by_node(node.node_id)` after
successful DB-row removal; a returned count greater than 1 SHALL be logged
as an ambiguous-tracker warning.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released

- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a cloud node with one tracker entry linked to that node
- **THEN** `clouds.deallocate(node)` is called, `uow.nodes.remove(node.node_id)` is called and committed, `tracker.discard_by_node(node.node_id)` returns 1, and the function returns without raising

#### Scenario: Non-cloud node skips VM deletion

- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a node with `node.cloud is None`
- **THEN** `clouds.deallocate(node)` is NOT called, `uow.nodes.remove(node.node_id)` is still called and committed, and `tracker.discard_by_node(node.node_id)` is still called

#### Scenario: Cloud deletion failure does not block DB cleanup

- **WHEN** `clouds.deallocate(node)` raises an exception
- **THEN** the exception is logged (with `node_id`, `hostname`, `cloud`), `uow.nodes.remove(node.node_id)` is still called and committed, `tracker.discard_by_node(node.node_id)` is still called, and the function returns without raising

#### Scenario: DB-row removal failure is re-raised

- **WHEN** `uow.nodes.remove(node.node_id)` raises an exception
- **THEN** the exception is logged (with `node_id`, `hostname`) and re-raised; `tracker.discard_by_node(...)` is NOT called (it runs after the remove block)

#### Scenario: Ambiguous tracker entry count logs a warning

- **WHEN** `tracker.discard_by_node(node.node_id)` returns a count greater than 1 (corruption: multiple tracker entries linked to the same node)
- **THEN** an `AMBIGUOUS_TRACKER` warning is logged with `node_id`, `hostname`, and the count; the function returns without raising

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and finalises or defers the task. The function
SHALL return `bool`: `True` when the task is finalised (DONE applied, remote
directory cleaned, in-flight allocation slot released via
`tracker.discard(task_id)`); `False` when the task is deferred for retry
(status unchanged, remote directory preserved, in-flight allocation slot
preserved).

The function SHALL delegate SFTP download and error classification to
`output_downloader.download_outputs(session, ...)`. Finalise SHALL apply the
terminal transition (`task.complete(...)` on full success or `task.fail(...)`
on any permanent error) emitting the matching event (`TaskCompleted` or
`TaskFailed`) inline; defer SHALL leave the task in `RUNNING`.

#### Scenario: Successful consumption

- **WHEN** `consume_task(...)` is called and `download_outputs` returns empty `transient_errors` and empty `permanent_errors`
- **THEN** `task.complete(local_folder=str(store_folder), remote_folder=...)` is called (emitting `TaskCompleted` inline), the task is saved and committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Permanent download error finalises with fail

- **WHEN** `download_outputs` returns non-empty `permanent_errors`
- **THEN** `task.fail(error_msg, local_folder=..., remote_folder=...)` is called (emitting `TaskFailed` inline, setting folders from partial download), the task is saved and committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Transient-only download error defers for retry

- **WHEN** `download_outputs` returns non-empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is left in `RUNNING`, no `tracker.discard` is called, and the function returns `False`

### Requirement: QueryTasks use case

The system SHALL provide a `query_tasks` async function that returns domain
`Task` aggregates matching a jobs- or statuses-based read query, alongside a
`dict[NodeId, Node]` of the nodes allocated to those tasks. The function
SHALL raise `ValueError` if both `jobs` and `statuses` are supplied and SHALL
return `([], {})` when neither is supplied.

The return type is `tuple[list[Task], dict[NodeId, Node]]`. The use case
returns raw domain objects; projection of a nested `node` field into task
dicts is the responsibility of the public facade.

#### Scenario: Query by statuses dispatches to list_by_status

- **WHEN** `query_tasks(jobs=None, statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_status({TaskStatus.TO_DO})` is awaited, `uow.nodes.get_by_ids(...)` is called with the `allocated_node_id`s of the returned tasks, the UoW closes without `commit`, and the returned `(list[Task], dict[NodeId, Node])` tuple is forwarded to the caller

#### Scenario: Query by jobs dispatches to list_by_jobs

- **WHEN** `query_tasks(jobs=[TaskId(1), TaskId(2), TaskId(3)], statuses=None, uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_jobs([TaskId(1), TaskId(2), TaskId(3)])` is awaited, `uow.nodes.get_by_ids(...)` is called with the `allocated_node_id`s of the returned tasks, the UoW closes without `commit`, and the returned `list[Task]` is forwarded to the caller

#### Scenario: Both jobs and statuses supplied raises ValueError

- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** `ValueError` is raised and no UoW is opened

#### Scenario: Neither jobs nor statuses returns empty tuple

- **WHEN** `query_tasks(jobs=None, statuses=None, uow_factory=f)` is called
- **THEN** `([], {})` is returned without dispatching to either repository method and without opening a UoW

#### Scenario: Query returns nodes_by_id with resolved nodes

- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` is called and task 1 has `allocated_node_id=NodeId(1)`
- **THEN** `uow.nodes.get_by_ids([NodeId(1)])` is called, the returned dict `{NodeId(1): node}` is included in the `(tasks, nodes_by_id)` tuple

#### Scenario: Query skips get_by_ids when all tasks unallocated

- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` is called and task 1 has `allocated_node_id=None`
- **THEN** `uow.nodes.get_by_ids` is NOT called (no node IDs to resolve), and the return is `([task], {})`

#### Scenario: Use case is read-only

- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` runs to completion successfully
- **THEN** `uow.commit()` is never called on the opened UoW

### Requirement: AllocationTracker tracks in-flight cloud allocations

The system SHALL provide an `AllocationTracker` class that tracks task_ids
with in-flight cloud allocations. The class SHALL expose:

- `add(task_id: TaskId, node_id: NodeId | None = None) -> bool` — returns
  True if newly added, False if already tracked.
- `set_node(task_id: TaskId, node_id: NodeId) -> None` — links a node to a
  tracked task; no-op if the task is not tracked.
- `discard(task_id: TaskId) -> None` — removes the entry by `task_id`
  (no-op if absent).
- `discard_by_node(node_id: NodeId) -> int` — removes ALL entries whose
  linked node matches `node_id` and returns the count removed.
- `__contains__(task_id: TaskId) -> bool`.

#### Scenario: AllocationTracker is a dict[TaskId, NodeId|None] deduplication helper

- **WHEN** `tracker.add(TaskId(42))` is called for an untracked task_id
- **THEN** returns True and `TaskId(42)` is in `tracker`; a second `add(TaskId(42))` returns False; `discard(TaskId(42))` removes it; `discard` of an untracked id is a no-op

#### Scenario: set_node patches the node link into an existing entry

- **WHEN** `tracker.add(TaskId(42))` is called (returning True), then `tracker.set_node(TaskId(42), NodeId(7))` is called
- **THEN** `tracker.discard_by_node(NodeId(7))` returns 1 and `TaskId(42)` is no longer in `tracker`

#### Scenario: set_node on an untracked task is a no-op

- **WHEN** `tracker.set_node(TaskId(99), NodeId(7))` is called for a task_id that was never added
- **THEN** `tracker.discard_by_node(NodeId(7))` returns 0 and `TaskId(99)` is not in `tracker`

#### Scenario: discard_by_node removes the matching entry and returns the count

- **WHEN** `tracker.add(TaskId(1), NodeId(5))` and `tracker.add(TaskId(2), NodeId(6))` are called, then `tracker.discard_by_node(NodeId(5))` is called
- **THEN** returns 1, `TaskId(1)` is no longer in `tracker`, and `TaskId(2)` is still in `tracker`

#### Scenario: discard_by_node with no matching entry returns 0

- **WHEN** `tracker.discard_by_node(NodeId(99))` is called on a tracker with entries for other nodes
- **THEN** returns 0 and no entries are removed

#### Scenario: discard_by_node removes multiple entries for the same node

- **WHEN** two entries link to the same `NodeId(5)` (corruption state), then `tracker.discard_by_node(NodeId(5))` is called
- **THEN** returns 2 and both entries are removed (defensive — all matching entries cleaned)
