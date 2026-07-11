# Use Cases

## Purpose

Application-layer use cases that orchestrate domain operations for task
submission, allocation, consumption, and node deallocation.

## Requirements

### Requirement: SubmitTask use case

The system SHALL provide a `submit_task` async function that creates a new
task in the database after validating the engine and inputs. The function SHALL
return `TaskId`.

The function SHALL construct a `NewTask(label=label, engine=engine_name,
local_folder=metadata.get("local_folder"), webhook_url=metadata.get("webhook_url"),
webhook_custom_params=metadata.get("webhook_custom_params", {}),
extra=extra_dict)` (the pre-persistence shape — no `task_id`; `status` defaults
to `TaskStatus.TO_DO`, `allocated_node_id` defaults to `None`; `remote_folder`
and `error` are NOT on `NewTask`), persist it via
`uow.tasks.insert(new_task) -> Task` (the sole `NewTask → Task` conversion;
`insert` calls `materialize_task` internally to attach `TaskCreated` to the
returned `Task`'s `events`), then `save`, `commit`, and return `task.task_id`
(a `TaskId`).

The typed fields are extracted from the caller-supplied `metadata` dict;
`engine` is set from the `engine_name` argument. The `extra` dict carries the
input-file payloads (file contents as values, file names as keys) — every key
in the caller `metadata` that is not one of the six known typed fields
(`engine`, `remote_folder`, `local_folder`, `webhook_url`,
`webhook_custom_params`, `error`) goes into `extra`. `remote_folder` and
`error` are never set on `NewTask`: `remote_folder` is assigned at `run` time;
`error` is only ever set by `reject`/`fail`/`abandon` on a post-persistence
`Task`.

#### Scenario: Successful task submission
- **WHEN** `submit_task(...)` is called with valid inputs
- **THEN** a `NewTask` is constructed, persisted via `uow.tasks.insert` → `Task` (with `TaskCreated` in `events` via `materialize_task`), saved, committed, and the `TaskId` is returned; `remote_folder` is `None` on the persisted TO_DO task

#### Scenario: Unsupported engine
- **WHEN** `submit_task(...)` is called with an engine_name not in the EngineRepository
- **THEN** `UnsupportedEngineError` is raised

#### Scenario: submit_task constructs NewTask not Task
- **WHEN** `submit_task(...)` builds the pre-persistence record
- **THEN** it constructs `NewTask(...)` (no `task_id=0` sentinel, no `remote_folder`, no `error`)

#### Scenario: submit_task does not construct events
- **WHEN** `submit_task(...)` is inspected for `TaskCreated` construction or `with_event`/`record_event` calls
- **THEN** none are present; `TaskCreated` is attached by `materialize_task` inside `insert`

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function SHALL
accept `task_id: TaskId`, `uow_factory`, `repository: MachineRepository`
(Protocol type), `occupancy_checker: OccupancyChecker` (concrete collaborator
type), `clouds: CloudProvisioner` (Protocol type), `tracker: AllocationTracker`,
and `allocation_lock: asyncio.Lock`. It SHALL NOT import from
`yascheduler.infra` at runtime. It SHALL NOT accept `adapters` or `configs`
parameters — provider selection is delegated to the `clouds.select_provider`
port method.

The orchestrator reads task ids from `list_by_status -> [Task]` (each carrying
`TaskId`) and feeds `allocate_task(task_id=task.task_id, ...)`, so `TaskId`
flows end-to-end internally with no conversion. `tracker.add`/`discard(task_id)`
keys are `TaskId` (the tracker's internal `dict` becomes
`dict[TaskId, NodeId | None]`).

For the cloud-fallback path, the use case SHALL own the full flow:
tracker dedup (via `tracker.add(task_id)` with `node_id=None`, before any DB
write so the dedup gate precedes tmp-node insertion), capacity check, provider
selection (via `clouds.select_provider` port method returning `str | None`),
tmp-node insertion via `uow.nodes.insert` (NOT `add_tmp`), node-link patching
(via `tracker.set_node(task_id, tmp_node.node_id)` after the tmp node is
inserted), cloud allocation (via `clouds.allocate(selection, node)` returning a
`Node` reusing the tmp node's `node_id`), final node persistence via
`uow.nodes.update(node)` (a single UPDATE flipping `enabled=TRUE` and setting
`ip`/`ncpus`), and tmp-node cleanup on failure (`uow.nodes.remove(tmp_node_id)`).
The `allocation_lock` SHALL serialize the capacity-read + select + tmp-insert
sequence so two concurrent `allocate_task` calls for the same engine cannot
both provision a cloud node when only one slot is free. The `tracker.add` dedup
gate SHALL run outside the lock and before any DB write; `tracker.set_node`
SHALL run after `_select_and_insert_tmp` returns (outside the lock, since the
lock is released inside `_select_and_insert_tmp` before its caller receives the
result) — there is no `await` between `set_node` and the surrounding code, so
the `None` window for the entry's node link is a single synchronous step with
no concurrency surface.

The function SHALL read `task.engine` when matching the task against engines.
The use case SHALL reject an unsupported engine via
`task.reject("unsupported engine")` (a single atomic transition that emits
`TaskFailed` inline — no separate `with_event` call, no duplicated reason
string). The use case SHALL compute `remote_folder` from `task.task_id` and
transition the task via `task.run(node.node_id, remote_folder)` (a single
atomic transition that sets `allocated_node_id` + `remote_folder`, moves to
RUNNING, and emits `TaskAllocated` inline). No `TaskContext` indirection.

#### Scenario: Successful allocation to a free machine
- **WHEN** `allocate_task(...)` is called and a free compatible machine exists
- **THEN** the use case computes `remote_folder` from `task.task_id`, calls `task.run(node.node_id, remote_folder)` (transitioning TO_DO→RUNNING and emitting `TaskAllocated` inline), starts the occupancy check, saves, commits, and the function returns True

#### Scenario: No free machine matches, cloud-fallback attempted
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the cloud-fallback path is attempted (tracker dedup with `node_id=None`, capacity check, provider selection, tmp-node insert, `tracker.set_node` linking the task to the tmp node, cloud allocation, final persist); returns False if no provider available

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a `task_id` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without inserting a tmp node or writing to the DB

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the use case calls `task.reject("unsupported engine")` (emitting `TaskFailed` inline), saves, commits, and the function returns False

#### Scenario: Occupancy check started via occupancy_checker

- **WHEN** `allocate_task(...)` successfully starts a task on a machine
- **THEN** `occupancy_checker.start_occupancy_check(session, engine)` is called

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept `uow_factory`,
`config_clouds: Sequence[CloudConfig]`, and `idle_machines: dict[NodeId, float]`
(`NodeId` -> free_since monotonic timestamp). It SHALL NOT accept `repository`
or `operations` (the per-node SSH/cloud teardown lives in `deallocate_node`).

The per-node wrapper `deallocate_node(node, repository, clouds, uow_factory)`
SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(node)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

`deallocate_node` SHALL call `uow.nodes.disable(node.node_id)` and
`uow.nodes.remove(node.node_id)` (keying on `node_id`, not `ip`).
`clouds.deallocate(node)` SHALL take the whole `Node` and read `node.cloud`
(provider) and `node.hostname` (cloud host) internally. `deallocate_node` SHALL
call `repository.contains(node.node_id)` and `repository.disconnect(node.node_id)`
BEFORE the `if node.cloud:` guard, so SSH teardown is owned by
`deallocate_node` and runs regardless of whether the node is a cloud node.

`deallocate_nodes` SHALL iterate the enabled nodes returned by
`uow.nodes.list_enabled()` and call `uow.nodes.disable(node.node_id)` for
each node whose `node_id` is in `idle_machines` and whose `node_id` is not
in `busy_node_ids` (the node_ids of RUNNING tasks' `allocated_node_id`).

`deallocate_nodes` SHALL return `list[Node]`. Phase 2
(collect free disabled cloud nodes) SHALL return the `Node` objects it
reads from `uow.nodes.list_disabled()`, each carrying `node_id`.

`deallocate_nodes` phase 2 SHALL filter disabled nodes by
`node.node_id not in busy_node_ids and node.cloud`.

Internal log lines in both `deallocate_nodes` and `deallocate_node` SHALL
include both `node_id` and `hostname` for correlation.

#### Scenario: Idle cloud node disabled
- **WHEN** `deallocate_nodes(...)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the `Node` is included in the returned `list[Node]`

#### Scenario: Returns disabled Node objects carrying node_id
- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a `list[Node]` is returned; each `Node` carries its `node_id`, so the orchestrator can call `deallocate_node(node, ...)` directly without a DB round-trip

#### Scenario: Deallocate node brackets cloud delete with disable+remove
- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` is called for a cloud node
- **THEN** SSH disconnect runs first, then `uow.nodes.disable` + commit, then `clouds.deallocate(node)`, then `uow.nodes.remove` + commit

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function that cleans up a
cloud node that never established its SSH connection, releasing the originating
task to re-allocate on the next cycle. The function SHALL accept `node: Node`,
`clouds: CloudProvisioner` (Protocol type), `uow_factory: Callable[[],
AbstractUnitOfWork]`, and `tracker: AllocationTracker`. It SHALL NOT import
from `yascheduler.infra` at runtime (TYPE_CHECKING only).

The use case SHALL NOT call `repository.disconnect` — by construction the
node was never registered in the repository (that is why it is being
abandoned). The use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `node_id`, `hostname`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal.
2. Open a UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`, and
   in-memory filter for the task whose `allocated_node_id == node.node_id`.
   This read SHALL happen BEFORE the node-row removal in step 3 — the
   `allocated_node_id` FK is `ON DELETE SET NULL`, so removing the node row
   first would null `allocated_node_id` and the in-memory filter would no
   longer match. Hold the matching task(s) in memory.
3. Open a UoW, call `uow.nodes.remove(node.node_id)`, and commit. Failure here
   SHALL be logged at `error` level with `node_id`, `hostname`, and the exception and
   re-raised.
4. If exactly one matching task was found in step 2, call
   `tracker.discard(task.task_id)`. If zero or multiple matched, no `discard`
   is called.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle. The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly.

Internal log lines SHALL include both `node_id` and `hostname` for correlation.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released
- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a cloud node with one matching TO_DO task
- **THEN** `clouds.deallocate(node)` is called, `uow.nodes.remove(node.node_id)` is called and committed, `tracker.discard(task.task_id)` is called, and the function returns without raising

#### Scenario: Cloud deletion failure does not block DB cleanup
- **WHEN** `clouds.deallocate(node)` raises an exception
- **THEN** the exception is logged, `uow.nodes.remove(node.node_id)` is still called and committed, and the function continues to the stuck-task lookup

#### Scenario: No matching TO_DO task skips tracker discard
- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_node_id == node.node_id`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and finalises or defers the task. The function SHALL
accept `task_id: TaskId`, `session: MachineSession` (resolved by the
orchestrator via `repository.get_session(task.allocated_node_id)`),
`output_downloader: OutputDownloader` (concrete collaborator type, for
`download_outputs`), `engines: EngineRepository`, `uow_factory: Callable[[], AbstractUnitOfWork]`,
`local_tasks_dir: Path`, and `tracker: AllocationTracker`. It SHALL NOT import
`SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime.

The function SHALL return `bool`: `True` when the task is finalised (DONE
status applied, remote directory cleaned, in-flight
allocation slot released via `tracker.discard(task_id)`); `False` when the
task is deferred for retry (status unchanged, remote directory preserved,
in-flight allocation slot NOT released).

The function SHALL receive the `session` directly (resolved by the
orchestrator from `task.allocated_node_id` via
`repository.get_session(node_id)`) and delegate SFTP download with retry and
error classification to `output_downloader.download_outputs(session, ...)`.
`download_outputs` receives `task_id=task.task_id` (a `TaskId`); it uses the
value for logging and remote folder naming, where `TaskId.__str__` renders
the bare integer. The function SHALL receive `(local_folder, remote_folder,
transient_errors, permanent_errors)` from `download_outputs` (a 4-tuple of
typed values) and branch on them:

- When `permanent_errors` is non-empty OR `transient_errors` is empty (full
  success, permanent-only errors, or both transient and permanent errors),
  the function SHALL finalise: on permanent errors it SHALL continue
  downloading the remaining available files first, then apply the terminal
  transition — `task.fail(error_details, local_folder=local_folder or
  task.local_folder, remote_folder=remote_folder or task.remote_folder)` (or
  `task.complete(local_folder=str(store_folder), remote_folder=remote_folder
  or task.remote_folder)` on full success with no permanent errors). Both
  transitions set the folders AND emit the matching event (`TaskFailed` or
  `TaskCompleted`) inline. Save via `uow.tasks.save()`, commit, call
  `tracker.discard(task_id)`, and return `True`. When both `permanent_errors`
  and `transient_errors` are non-empty, permanent takes priority and the
  function finalises with `task.fail()`.
- When `transient_errors` is non-empty AND `permanent_errors` is empty, the
  function SHALL defer: leave the task in `RUNNING` (no status change, no
  save, no event, no `tracker.discard`), and return `False` so the
  orchestrator re-consumes the task on the next producer cycle.

The `error_details` for the `TaskFailed` path SHALL be formatted via the
error column format contract: `"Download error: <path>: <msg>, <path>: <msg>"`
(combined `permanent_errors + transient_errors`); entries with `path=None`
render as bare `"<msg>"`.

The function SHALL call `task.fail(error_msg,
local_folder=local_folder or task.local_folder, remote_folder=remote_folder
or task.remote_folder)` or `task.complete(local_folder=str(store_folder),
remote_folder=remote_folder or task.remote_folder)` directly — no prior
`with_download_results(...)` step. The terminal transitions do NOT touch
`extra`.

The function SHALL read `task.remote_folder`, `task.engine`, and
`task.local_folder` directly from the typed fields. The assertion
`assert task.remote_folder is not None` SHALL guard the `task.remote_folder`
read (the task is RUNNING — `run` assigned `remote_folder` at allocate time).
No `TaskContext` indirection.

#### Scenario: Successful consumption
- **WHEN** `consume_task(...)` is called and `download_outputs` returns empty `transient_errors` and empty `permanent_errors`
- **THEN** `task.complete(local_folder=str(store_folder), remote_folder=...)` is called (emitting `TaskCompleted` inline), the task is saved, committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Permanent download error finalises with DONE+error
- **WHEN** `download_outputs` returns non-empty `permanent_errors`
- **THEN** `task.fail(error_msg, local_folder=..., remote_folder=...)` is called (emitting `TaskFailed` inline, setting folders from partial download), the task is saved, committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Transient-only download error defers for retry
- **WHEN** `download_outputs` returns non-empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is left in `RUNNING`, no `tracker.discard` is called, and the function returns `False`

#### Scenario: consume_task reads typed fields not task.context
- **WHEN** `consume_task` is inspected for `task.context` references
- **THEN** none are present; reads use `task.remote_folder`, `task.engine`, `task.local_folder` directly

#### Scenario: consume_task does not call with_download_results or with_event
- **WHEN** `consume_task` is inspected for `with_download_results` or `with_event` calls
- **THEN** none are present; the terminal transitions `complete`/`fail` set the folders and emit the events inline

### Requirement: QueryTasks use case

The system SHALL provide a `query_tasks` async function that returns
domain `Task` aggregates matching a jobs- or statuses-based read query,
alongside a `dict[NodeId, Node]` of the nodes allocated to those tasks (for
the caller to project a nested `node` field). The function SHALL accept
`jobs: Sequence[TaskId] | None`, `statuses:
Sequence[TaskStatus] | None`, and `uow_factory: Callable[[], AbstractUnitOfWork]`.
It SHALL raise `ValueError` if both `jobs` and `statuses` are supplied. It
SHALL open a single Unit of Work, dispatch to `uow.tasks.list_by_status(set(statuses))`
when `statuses` is non-empty or `uow.tasks.list_by_jobs(list(jobs))` (a
`list[TaskId]`) when `jobs` is non-empty, and return `([], {})` when neither
is non-empty. It SHALL NOT call `uow.commit` (read-only). It SHALL NOT
import from `yascheduler.infra` at runtime.

Within the same single UoW, after fetching tasks, the use case SHALL
batch-load the nodes allocated to those tasks via
`uow.nodes.get_by_ids(list({t.allocated_node_id for t in tasks if
t.allocated_node_id is not None}))` (a single batch round-trip), building
`nodes_by_id: dict[NodeId, Node]`. When no task has an `allocated_node_id`
(all tasks are unallocated), the use case SHALL skip the `get_by_ids` call
and return `(tasks, {})`. The use case SHALL return the tuple
`(tasks, nodes_by_id)`.

The return type is `tuple[list[Task], dict[NodeId, Node]]`. The use case does
NOT project the nested `node` field into task dicts; that is the facade's
responsibility. It returns raw domain objects.

The public `Yascheduler.queue_get_tasks_async(jobs: list[int])` facade is the
sole `int`/`TaskId` boundary on this path: it wraps `[TaskId(i) for i in jobs]`
before calling `query_tasks(jobs=[TaskId(...)], ...)`.

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

The system SHALL provide an `AllocationTracker` class that maintains an
in-memory `dict[TaskId, NodeId | None]` of task_ids with in-flight cloud
allocations, mapping each tracked task to its provisioning tmp node (or
`None` between the dedup gate and the tmp-node insert).
The class SHALL expose:

- `add(task_id: TaskId, node_id: NodeId | None = None) -> bool` — returns
  True if newly added, False if already tracked. The optional `node_id`
  parameter defaults to `None` so the dedup gate can call `add(task_id)`
  before the tmp node exists.
- `set_node(task_id: TaskId, node_id: NodeId) -> None` — patches the node
  link into an existing entry. If the `task_id` is not tracked, the call
  SHALL be a no-op (defensive — the entry is added by `add` and removed by
  `discard`; `set_node` only runs on the success path between them).
- `discard(task_id: TaskId) -> None` — removes the entry by `task_id`
  (unchanged semantics; the `NodeId | None` value is discarded with it).
- `discard_by_node(node_id: NodeId) -> int` — removes ALL entries whose
  linked node matches `node_id` and returns the count removed. Returns 0 if
  no entry links to the node (no-op).
- `__contains__(task_id: TaskId) -> bool` — unchanged.

The tracker SHALL be constructed once by the orchestrator and injected into
the `allocate_task`, `consume_task`, and `abandon_node` use cases. It is
internal to the orchestrator and never crosses the public `Yascheduler`
facade boundary.

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
