# Use Cases

## Purpose

Application-layer use cases that orchestrate domain operations for task
submission, allocation, consumption, and node deallocation.

## Requirements

### Requirement: SubmitTask use case

The system SHALL provide a `submit_task` async function that creates a new
task in the database after validating the engine and inputs. The function SHALL
return `TaskId` (was `int`).

The function SHALL construct a `NewTask(label=label, context=context)` (the
pre-persistence shape — no `task_id`; `status` defaults to `TaskStatus.TO_DO`,
`allocated_ip` defaults to `None`), persist it via
`uow.tasks.insert(new_task) -> Task` (the sole `NewTask → Task` conversion),
then `with_context(remote_folder based on task.task_id)` and
`with_event(TaskCreated, ...)`, `save`, `commit`, and return `task.task_id`
(a `TaskId`).

#### Scenario: Successful task submission
- **WHEN** `submit_task("my-job", ctx, "fleur", engines, uow_factory)` is called with valid inputs
- **THEN** a new Task is saved with status TO_DO and the `TaskId` is returned (the CLI prints `str(TaskId)` → bare integer; the public `Yascheduler.queue_submit_task` facade extracts `.value` to keep the public `-> int` contract)

#### Scenario: Unsupported engine
- **WHEN** `submit_task(...)` is called with an engine_name not in the EngineRepository
- **THEN** `UnsupportedEngineError` is raised

#### Scenario: Missing input file
- **WHEN** `submit_task(...)` is called with context missing a required input file
- **THEN** `MissingInputFileError` is raised

#### Scenario: submit_task constructs NewTask not Task
- **WHEN** `submit_task(...)` builds the pre-persistence record
- **THEN** it constructs `NewTask(label=label, context=context)` (no `task_id=0` sentinel); the `task_id=0` fiction is gone

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function SHALL
accept `task_id: TaskId` (was `int`), `uow_factory`, `repository:
MachineRepository` (Protocol type), `operations: MachineOperations` (Protocol
type), `clouds: CloudProvisioner` (Protocol type), `tracker: AllocationTracker`,
and `allocation_lock: asyncio.Lock`. It SHALL NOT import from `yascheduler.infra` at
runtime. It SHALL NOT accept `adapters` or `configs` parameters — provider
selection is delegated to the `clouds.select_provider` port method.

The orchestrator reads task ids from `list_by_status -> [Task]` (each carrying
`TaskId`) and feeds `allocate_task(task_id=task.task_id, ...)`, so `TaskId`
flows end-to-end internally with no conversion. Logging `"task_id=%s"` renders
the bare integer via `TaskId.__str__`. `tracker.add`/`discard(task_id)` keys
are `TaskId` (the tracker's internal `set` becomes `set[TaskId]`).

For the cloud-fallback path, the use case SHALL own the full flow:
tracker dedup, capacity check, provider selection (via
`clouds.select_provider` port method returning `str | None`), tmp-node
insertion via `uow.nodes.insert` (NOT `add_tmp`), cloud allocation (via
`clouds.allocate(selection)`), final node persistence, and tmp-node cleanup on
failure. The `allocation_lock` SHALL serialize the capacity-read + select +
tmp-insert critical section as a single UoW with commit before lock release.

The tmp-node handle is a `NodeId`, not a placeholder IP. The internal
`_TmpSelection` NamedTuple SHALL carry `name: str` and `node_id: NodeId` (NOT
`ip: str`). `_select_and_insert_tmp` SHALL call
`uow.nodes.insert(NewNode(cloud=selected_name, enabled=False)) -> Node` and
return `_TmpSelection(name=selected_name, node_id=tmp_node.node_id)`. The
`NewNode.ip=""` and `NewNode.ncpus=0` defaults supply the tmp-row's `ip` and
`ncpus` columns.

The tmp-node cleanup paths (`_cleanup_tmp_node_best_effort`,
`_allocate_cloud_node`, `_persist_node_with_cleanup`, `_provision_and_persist`)
SHALL take `tmp_node_id: NodeId` (NOT `tmp_ip: str`) and call
`uow.nodes.remove(tmp_node_id)` directly. The `uow.nodes.get(tmp_ip)` lookup
and its `if node is not None` None-branch SHALL NOT run — the `NodeId` is
already in hand from `insert`'s return. `remove(tmp_node_id)` is idempotent:
`DELETE WHERE node_id = :node_id` affecting 0 rows is a no-op, matching the
prior no-op-on-0-rows behavior (no rowcount check added). Failures in
best-effort cleanup are logged, not raised.

The final-persistence path (`_persist_node_with_cleanup`) SHALL
`uow.nodes.insert(node)` (the real `NewNode` from `clouds.allocate`, carrying
a real `ip` and `ncpus`), then `uow.nodes.remove(tmp_node_id)` (the tmp-row
cleanup), then commit, in one UoW. If the persist fails, the VM is
best-effort deallocated via `clouds.deallocate(cloud_name, node.ip)` and the
tmp-node is best-effort cleaned up via `_cleanup_tmp_node_best_effort`; the
original exception is re-raised.

#### Scenario: Allocate to free machine
- **WHEN** `allocate_task(task_id, engines, uow_factory, repository, operations, clouds, start_task_on_machine, tracker, allocation_lock)` is called (with `task_id: TaskId`) and a free compatible machine exists
- **THEN** the task is loaded via UoW (`uow.tasks.get(task_id)`), allocated via `task.allocate_to(ip)`, transitioned to RUNNING via `task.mark_running()`, saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called

#### Scenario: No free machine — cloud fallback with full ownership
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the use case calls `tracker.add(task_id)` (returns False → return immediately if already in-flight). Then opens a UoW under `allocation_lock`, reads `uow.nodes.list_all()`, calls `clouds.select_provider(platforms, counts)` (port method). If `selection is None`, calls `tracker.discard(task_id)` and returns False. Otherwise inserts a tmp-node via `uow.nodes.insert(NewNode(cloud=selection, enabled=False)) -> Node`, commits (lock released), calls `clouds.allocate(selection)` outside the lock, then opens a second UoW to persist the final Node and remove the tmp-node by `node_id`. Returns False.

#### Scenario: Tmp-node insertion uses insert not add_tmp
- **WHEN** the cloud-fallback critical section inserts a tmp-node
- **THEN** it calls `uow.nodes.insert(NewNode(cloud=selected_name, enabled=False))` (NOT `uow.nodes.add_tmp(...)`); the returned `Node.node_id` becomes the `_TmpSelection.node_id` cleanup handle

#### Scenario: Tmp-node cleanup removes by node_id directly
- **WHEN** any tmp-node cleanup path (`_cleanup_tmp_node_best_effort`, `_persist_node_with_cleanup`, or the `_allocate_cloud_node`/`_provision_and_persist` failure paths) runs
- **THEN** it calls `uow.nodes.remove(tmp_node_id)` directly with the `NodeId`; it does NOT call `uow.nodes.get(tmp_ip)` first; the `if node is not None` None-branch is gone; a 0-row DELETE is a no-op (idempotent)

#### Scenario: Cloud allocation failure cleans up tmp-node by node_id
- **WHEN** `clouds.allocate(selection)` raises `CloudAllocateError` or `CloudSetupError` after tmp-node insertion
- **THEN** the use case calls `_cleanup_tmp_node_best_effort(uow_factory, tmp_node_id, ...)` which calls `uow.nodes.remove(tmp_node_id)` and commits (no `get` lookup, no None-branch), calls `tracker.discard(task_id)`, and re-raises

#### Scenario: Final persistence removes tmp-node by node_id
- **WHEN** `_persist_node_with_cleanup` runs after `clouds.allocate` succeeded
- **THEN** it opens a UoW, calls `uow.nodes.insert(node)` (the real `NewNode`), calls `uow.nodes.remove(tmp_node_id)` (the tmp cleanup, no `get` lookup), and commits

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a `task_id: TaskId` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without creating a second VM

#### Scenario: Throttle returns None — no tmp-node inserted
- **WHEN** `clouds.select_provider(platforms, counts)` returns `None` because the selected provider's op semaphore is locked
- **THEN** the use case calls `tracker.discard(task_id)` and returns False (no tmp-node inserted, no exception raised)

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.reject("unsupported engine")`, saved, committed, and `TaskFailed` event is recorded (carrying `task_id: TaskId`)

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and finalises or defers the task. The function
SHALL accept `task_id: TaskId` (was `int`), `ip: str`, `repository:
MachineRepository` (Protocol type, for `get_session`), `operations:
MachineOperations` (Protocol type, for `download_outputs`), `engines:
EngineRepository`, `uow_factory: Callable[[], AbstractUnitOfWork]`,
`local_tasks_dir: Path`, and `tracker: AllocationTracker`. It SHALL NOT import
`SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime.

The function SHALL return `bool`: `True` when the task is finalised (DONE
status applied, remote directory cleaned by the operations, in-flight
allocation slot released via `tracker.discard(task_id)`); `False` when the
task is deferred for retry (status unchanged, remote directory preserved by
the operations, in-flight allocation slot NOT released).

The function SHALL resolve a `session` via `repository.get_session(ip)` and
delegate SFTP download with retry and error classification to
`operations.download_outputs(session, ...)`. `download_outputs` receives
`task_id=task.task_id` (a `TaskId`); it uses the value for logging and remote
folder naming, where `TaskId.__str__` renders the bare integer. The function
SHALL receive `(meta_add, transient_errors, permanent_errors)` from
`download_outputs` and branch on them:

- When `permanent_errors` is non-empty OR `transient_errors` is empty (full
  success, permanent-only errors, or both transient and permanent errors),
  the function SHALL finalise: on permanent errors it SHALL continue
  downloading the remaining available files first, then apply `task.fail(error_details)`
  (or `task.complete()` on full success with no permanent errors), save via
  `uow.tasks.save()`, commit, record the corresponding event (`TaskFailed` or
  `TaskCompleted`, both carrying `task_id: TaskId`), call
  `tracker.discard(task_id)`, and return `True`. When both `permanent_errors`
  and `transient_errors` are non-empty, permanent takes priority and the
  function finalises with `task.fail()`.
- When `transient_errors` is non-empty AND `permanent_errors` is empty, the
  function SHALL defer: leave the task in `RUNNING` (no status change, no
  save, no event, no `tracker.discard`), and return `False` so the
  orchestrator re-consumes the task on the next producer cycle.

#### Scenario: Successful consumption
- **WHEN** `consume_task(task_id, ip, repository, operations, engines, uow_factory, local_tasks_dir, tracker)` is called (with `task_id: TaskId`) on a completed task and `download_outputs` returns empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is loaded via UoW (`uow.tasks.get(task_id)`), output files are downloaded via `operations.download_outputs(session, ..., task_id=task.task_id)`, the task is transitioned via `task.complete()`, saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Permanent download error finalises with DONE+error
- **WHEN** `operations.download_outputs(session, ...)` returns empty `transient_errors` and non-empty `permanent_errors`
- **THEN** the task is transitioned via `task.fail(error_details)` (after the operations loop downloaded the remaining available files), saved, committed, a `TaskFailed` event (carrying `task_id: TaskId`) is recorded, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Transient-only download error defers for retry
- **WHEN** `operations.download_outputs(session, ...)` returns non-empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is left in `RUNNING` (no status change, no save, no event), `tracker.discard(task_id)` is NOT called, and the function returns `False` so the orchestrator re-consumes the task on the next producer cycle

#### Scenario: Mixed transient and permanent errors finalise with DONE+error
- **WHEN** `operations.download_outputs(session, ...)` returns both non-empty `transient_errors` and non-empty `permanent_errors`
- **THEN** permanent takes priority: the task is transitioned via `task.fail(error_details)`, saved, committed, a `TaskFailed` event (carrying `task_id: TaskId`) is recorded, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: No adapter imports at runtime
- **WHEN** `consume_task.py` is imported
- **THEN** it does NOT import `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

#### Scenario: No adapter imports at runtime
- **WHEN** `consume_task.py` is imported
- **THEN** it does NOT import `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept `uow_factory`
and `repository: MachineRepository` + `operations: MachineOperations`.

The per-node wrapper `deallocate_node(node, repository, operations, clouds,
uow_factory)` SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(cloud, ip)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

`deallocate_node` SHALL call `uow.nodes.disable(node.node_id)` and
`uow.nodes.remove(node.node_id)` (keying on `node_id`, not `ip`).
`clouds.deallocate(node.cloud, node.ip)` SHALL continue to take `ip`
(ip is the cloud host address, not node identity).

`deallocate_nodes` SHALL iterate `all_enabled_nodes.values()` and call
`uow.nodes.disable(node.node_id)` for each node to disable (the `Node` is
the dict value; today the loop uses the ip key — switch to the value).

Internal log lines SHALL include both `node_id` and `ip` for correlation.

#### Scenario: Idle cloud node disabled
- **WHEN** `deallocate_nodes(uow_factory, config_clouds, idle_machines)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the IP is returned for orchestrator-level SSH cleanup and cloud deallocation

#### Scenario: Non-cloud node skipped
- **WHEN** a non-cloud node is idle
- **THEN** it is not disabled and not included in returned IPs

#### Scenario: Returns disabled node IPs
- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a list of disabled node IPs is returned for the orchestrator to handle SSH disconnect and cloud deallocation

#### Scenario: Deallocate node brackets cloud delete with disable+remove
- **WHEN** `deallocate_node(node, repository, operations, clouds, uow_factory)` is called for a cloud node
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed, then `clouds.deallocate(node.cloud, node.ip)` is called, then the node is removed via `uow.nodes.remove(node.node_id)` and committed

#### Scenario: Internal logs include node_id and ip
- **WHEN** `deallocate_node` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function in
`yascheduler/application/abandon_node.py` that cleans up a cloud node that
never established its SSH connection, releasing the originating task to
re-allocate on the next cycle. The function SHALL accept `node: Node`,
`repository: MachineRepository` (Protocol type), `operations:
MachineOperations` (Protocol type), `clouds: CloudProvisioner` (Protocol
type), `uow_factory: Callable[[], AbstractUnitOfWork]`, and `tracker:
AllocationTracker`. It SHALL NOT import from `yascheduler.infra` at runtime
(TYPE_CHECKING only).

The use case SHALL NOT call `repository.disconnect` — by construction the
node was never registered in the repository (that is why it is being
abandoned). The use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node.cloud, node.ip)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `node_id`, `ip`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal.
2. Open a UoW, call `uow.nodes.remove(node.node_id)`, and commit. Failure here
   SHALL be logged at `error` level with `node_id`, `ip`, and the exception and
   re-raised.
3. Open a second UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`,
   and in-memory filter for the task whose `allocated_ip == node.ip`. If
   exactly one such task exists, call `tracker.discard(task.task_id)`. If
   zero or multiple match, no `discard` is called.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle. The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly.

Internal log lines SHALL include both `node_id` and `ip` for correlation.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released
- **WHEN** `abandon_node(node, repository, operations, clouds, uow_factory, tracker)` is called for a cloud node (`node.cloud` non-None) with one TO_DO task whose `allocated_ip == node.ip`
- **THEN** `clouds.deallocate(node.cloud, node.ip)` is called, `uow.nodes.remove(node.node_id)` is called and committed, `tracker.discard(task.task_id)` is called for the matching task, and the function returns without raising

#### Scenario: Non-cloud node skips VM deletion
- **WHEN** `abandon_node(...)` is called with `node.cloud is None`
- **THEN** `clouds.deallocate` is NOT called, `uow.nodes.remove(node.node_id)` is still called and committed, and the stuck-task lookup still runs

#### Scenario: Cloud deletion failure does not block DB cleanup
- **WHEN** `clouds.deallocate(node.cloud, node.ip)` raises an exception
- **THEN** the exception is logged at `error` level with `node_id`, `ip`, `cloud`, and the message, `uow.nodes.remove(node.node_id)` is still called and committed, and the function continues to the stuck-task lookup

#### Scenario: DB remove failure is re-raised
- **WHEN** `uow.nodes.remove(node.node_id)` or its commit raises an exception
- **THEN** the exception is logged at `error` level with `node_id`, `ip`, and the message, and the exception is re-raised

#### Scenario: Internal logs include node_id and ip
- **WHEN** `abandon_node` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields

#### Scenario: No matching TO_DO task
- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_ip == node.ip`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran

#### Scenario: Multiple matching TO_DO tasks is logged not fatal
- **WHEN** the stuck-task lookup finds more than one TO_DO task with `allocated_ip == node.ip`
- **THEN** a warning is logged, `tracker.discard` is NOT called (ambiguous which task to release), the VM deletion + DB removal still ran, and the function returns without raising

#### Scenario: No adapter imports at runtime
- **WHEN** `abandon_node.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

### Requirement: Use cases importable from application

The system SHALL expose all use cases from `yascheduler.application`. No use
case SHALL import adapter-specific types (`AllSSHRetryExc`, `SFTPRetryExc`,
`SFTPError`) from `yascheduler.infra` at runtime.

#### Scenario: Import use case
- **WHEN** `from yascheduler.application.submit_task import submit_task` is executed
- **THEN** the function is available

#### Scenario: No adapter runtime imports in use cases
- **WHEN** any use case module is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, or `SFTPError` from `yascheduler.infra` at runtime

### Requirement: QueryTasks use case

The system SHALL provide a `query_tasks` async function that returns
domain `Task` aggregates matching a jobs- or statuses-based read query.
The function SHALL accept `jobs: Sequence[TaskId] | None` (was
`Sequence[int] | None`), `statuses: Sequence[TaskStatus] | None`, and
`uow_factory: Callable[[], AbstractUnitOfWork]`. It SHALL raise `ValueError` if
both `jobs` and `statuses` are supplied. It SHALL open a single Unit of Work,
dispatch to `uow.tasks.list_by_status(set(statuses))` when `statuses` is
non-empty or `uow.tasks.list_by_jobs(list(jobs))` (a `list[TaskId]`) when
`jobs` is non-empty, and return `[]` when neither is non-empty (truthiness
semantics, matching `yascheduler.client.queue_get_tasks_async`'s existing
dispatch). It SHALL NOT call `uow.commit` (read-only). It SHALL NOT import
from `yascheduler.infra` at runtime.

The public `Yascheduler.queue_get_tasks_async(jobs: list[int])` facade is the
sole `int`/`TaskId` boundary on this path: it wraps `[TaskId(i) for i in jobs]`
before calling `query_tasks(jobs=[TaskId(...)], ...)`.

#### Scenario: Query by statuses dispatches to list_by_status
- **WHEN** `query_tasks(jobs=None, statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_status({TaskStatus.TO_DO})` is awaited, the UoW closes without `commit`, and the returned `list[Task]` is forwarded to the caller

#### Scenario: Query by jobs dispatches to list_by_jobs
- **WHEN** `query_tasks(jobs=[TaskId(1), TaskId(2), TaskId(3)], statuses=None, uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_jobs([TaskId(1), TaskId(2), TaskId(3)])` is awaited, the UoW closes without `commit`, and the returned `list[Task]` is forwarded to the caller

#### Scenario: Both jobs and statuses supplied raises ValueError
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** `ValueError` is raised and no UoW is opened

#### Scenario: Neither jobs nor statuses returns empty list
- **WHEN** `query_tasks(jobs=None, statuses=None, uow_factory=f)` is called
- **THEN** `[]` is returned without dispatching to either repository method and without opening a UoW

#### Scenario: Use case is read-only
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` runs to completion successfully
- **THEN** `uow.commit()` is never called on the opened UoW

### Requirement: AllocationTracker tracks in-flight cloud allocations

The system SHALL provide an `AllocationTracker` class in
`yascheduler.application.allocation_tracker` that maintains an in-memory
`set[TaskId]` of task_ids with in-flight cloud allocations (was `set[int]`).
The class SHALL expose `add(task_id: TaskId) -> bool` (returns True if newly
added, False if already tracked), `discard(task_id: TaskId) -> None`, and
`__contains__(task_id: TaskId) -> bool`.

The tracker SHALL be constructed once by the orchestrator and injected into
the `allocate_task`, `consume_task`, and `abandon_node` use cases. It is
internal to the orchestrator and never crosses the public `Yascheduler`
facade boundary.

#### Scenario: Add new task to tracker
- **WHEN** `tracker.add(TaskId(42))` is called for an untracked task_id
- **THEN** returns True and `TaskId(42)` is in `tracker`

#### Scenario: Add duplicate task to tracker
- **WHEN** `tracker.add(TaskId(42))` is called while `TaskId(42)` is already tracked
- **THEN** returns False and the set is unchanged

#### Scenario: Discard tracked task
- **WHEN** `tracker.discard(TaskId(42))` is called after a successful allocation or completion
- **THEN** `TaskId(42)` is no longer in `tracker`

#### Scenario: Discard untracked task is a no-op
- **WHEN** `tracker.discard(TaskId(99))` is called for a task not in the tracker
- **THEN** no error is raised and the set is unchanged

#### Scenario: Containment check
- **WHEN** `TaskId(42) in tracker` is evaluated
- **THEN** returns True if `TaskId(42)` is tracked, False otherwise
