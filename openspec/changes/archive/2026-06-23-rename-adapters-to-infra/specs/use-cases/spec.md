## MODIFIED Requirements

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function
SHALL accept `task_id: int`, `uow_factory`, `gateway: MachineGateway`
(Protocol type), `clouds: CloudProvisioner` (Protocol type), `tracker:
AllocationTracker`, and `allocation_lock: asyncio.Lock`. It SHALL NOT
import from `yascheduler.infra` at runtime. It SHALL NOT accept
`adapters` or `configs` parameters — provider selection is delegated to
the `clouds.select_provider` port method.

For the cloud-fallback path, the use case SHALL own the full flow:
tracker dedup, capacity check, provider selection (via
`clouds.select_provider` port method returning `ProviderSelection`),
tmp-node insertion, cloud allocation (via `clouds.allocate(selection.name)`),
final node persistence, and tmp-node cleanup on failure. The
`allocation_lock` SHALL serialize the capacity-read + select + add_tmp
critical section as a single UoW with commit before lock release.

#### Scenario: Allocate to free machine
- **WHEN** `allocate_task(task_id, engines, uow_factory, gateway, clouds, start_task_on_machine, tracker, allocation_lock)` is called and a free compatible machine exists
- **THEN** the task is loaded via UoW, allocated via `task.allocate_to(ip)`, transitioned to RUNNING via `task.mark_running()`, saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called

#### Scenario: No free machine — cloud fallback with full ownership
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the use case calls `tracker.add(task_id)` (returns False → return immediately if already in-flight). Then opens a UoW under `allocation_lock`, reads `uow.nodes.list_all()`, calls `clouds.select_provider(platforms, counts)` (port method). If `selection is None`, calls `tracker.discard(task_id)` and returns False. Otherwise inserts a tmp-node via `uow.nodes.add_tmp(selection.name, selection.username)`, commits, calls `clouds.allocate(selection.name)` outside the lock, then opens a second UoW to persist the final Node and remove the tmp-node. Returns False.

#### Scenario: Cloud allocation failure cleans up tmp-node
- **WHEN** `clouds.allocate(selection.name)` raises `CloudAllocateError` or `CloudSetupError` after tmp-node insertion
- **THEN** the use case opens a UoW, removes the tmp-node via `uow.nodes.remove(tmp_ip)`, commits, calls `tracker.discard(task_id)`, and re-raises

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a task_id already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without creating a second VM

#### Scenario: Throttle returns None — no tmp-node inserted
- **WHEN** `clouds.select_provider(platforms, counts)` returns `None` because the selected provider's op semaphore is locked
- **THEN** the use case calls `tracker.discard(task_id)` and returns False (no tmp-node inserted, no exception raised)

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.reject("unsupported engine")`, saved, committed, and `TaskFailed` event is recorded

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and marks the task DONE. The function SHALL
accept `task_id: int`, `uow_factory`, `gateway: MachineGateway` (Protocol
type), and `tracker: AllocationTracker`. It SHALL NOT import
`SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at
runtime.

The function SHALL delegate SFTP download with retry to
`gateway.download_outputs()` instead of managing SFTP sessions and backoff
internally. The function SHALL receive `(meta_add, sftp_errors)` from
`download_outputs` and pass them to `_finalize_task`.

On successful finalization, the use case SHALL call
`tracker.discard(task_id)` to release the in-flight allocation slot.

#### Scenario: Successful consumption
- **WHEN** `consume_task(task_id, ip, gateway, engines, uow_factory, local_tasks_dir, tracker)` is called on a completed task
- **THEN** the task is loaded via UoW, output files are downloaded via `gateway.download_outputs()`, the task is transitioned via `task.complete()`, saved via `uow.tasks.save()`, committed, remote directory is cleaned, and `tracker.discard(task_id)` is called

#### Scenario: Download failure
- **WHEN** `gateway.download_outputs()` returns non-empty `sftp_errors`
- **THEN** the task is transitioned via `task.fail(error_details)`, saved, committed, and `tracker.discard(task_id)` is called

#### Scenario: No adapter imports at runtime
- **WHEN** `consume_task.py` is imported
- **THEN** it does NOT import `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

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
The function SHALL accept `jobs: Sequence[int] | None`, `statuses:
Sequence[TaskStatus] | None`, and `uow_factory: Callable[[],
AbstractUnitOfWork]`. It SHALL raise `ValueError` if both `jobs` and
`statuses` are supplied. It SHALL open a single Unit of Work, dispatch to
`uow.tasks.list_by_status(set(statuses))` when `statuses` is non-empty or
`uow.tasks.list_by_jobs(list(jobs))` when `jobs` is non-empty, and
return `[]` when neither is non-empty (truthiness semantics, matching
`yascheduler.client.queue_get_tasks_async`'s existing dispatch). It SHALL
NOT call `uow.commit` (read-only). It SHALL NOT import from
`yascheduler.infra` at runtime.

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
