# Use Cases

## Purpose

Application-layer use cases that orchestrate domain operations for task
submission, allocation, consumption, and node deallocation.

## Requirements

### Requirement: SubmitTask use case

The system SHALL provide a `submit_task` async function that creates a new
task in the database after validating the engine and inputs.

#### Scenario: Successful task submission
- **WHEN** `submit_task("my-job", ctx, "fleur", engines, uow_factory)` is called with valid inputs
- **THEN** a new Task is saved with status TO_DO and the task_id is returned

#### Scenario: Unsupported engine
- **WHEN** `submit_task(...)` is called with an engine_name not in the EngineRepository
- **THEN** `UnsupportedEngineError` is raised

#### Scenario: Missing input file
- **WHEN** `submit_task(...)` is called with context missing a required input file
- **THEN** `MissingInputFileError` is raised

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
`clouds.select_provider` port method returning `str | None`), tmp-node
insertion, cloud allocation (via `clouds.allocate(selection)`), final
node persistence, and tmp-node cleanup on failure. The
`allocation_lock` SHALL serialize the capacity-read + select + add_tmp
critical section as a single UoW with commit before lock release.

#### Scenario: Allocate to free machine
- **WHEN** `allocate_task(task_id, engines, uow_factory, gateway, clouds, start_task_on_machine, tracker, allocation_lock)` is called and a free compatible machine exists
- **THEN** the task is loaded via UoW, allocated via `task.allocate_to(ip)`, transitioned to RUNNING via `task.mark_running()`, saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called

#### Scenario: No free machine — cloud fallback with full ownership
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the use case calls `tracker.add(task_id)` (returns False → return immediately if already in-flight). Then opens a UoW under `allocation_lock`, reads `uow.nodes.list_all()`, calls `clouds.select_provider(platforms, counts)` (port method). If `selection is None`, calls `tracker.discard(task_id)` and returns False. Otherwise inserts a tmp-node via `uow.nodes.add_tmp(selection)`, commits, calls `clouds.allocate(selection)` outside the lock, then opens a second UoW to persist the final Node and remove the tmp-node. Returns False.

#### Scenario: Cloud allocation failure cleans up tmp-node
- **WHEN** `clouds.allocate(selection)` raises `CloudAllocateError` or `CloudSetupError` after tmp-node insertion
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

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept
`uow_factory` and `SSHMachineGateway` instead of `RemoteMachineRepository`.
It SHALL NOT import from `remote_machine/`.

The per-node wrapper `deallocate_node(node, gateway, clouds, uow_factory)`
SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(cloud, ip)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

#### Scenario: Idle cloud node disabled
- **WHEN** `deallocate_nodes(uow_factory, config_clouds, idle_machines)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(ip)` and committed; the IP is returned for orchestrator-level SSH cleanup and cloud deallocation

#### Scenario: Non-cloud node skipped
- **WHEN** a non-cloud node is idle
- **THEN** it is not disabled and not included in returned IPs

#### Scenario: Returns disabled node IPs
- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a list of disabled node IPs is returned for the orchestrator to handle SSH disconnect and cloud deallocation

#### Scenario: Deallocate node brackets cloud delete with disable+remove
- **WHEN** `deallocate_node(node, gateway, clouds, uow_factory)` is called for a cloud node
- **THEN** the node is disabled via UoW and committed, then `clouds.deallocate(node.cloud, node.ip)` is called, then the node is removed via a second UoW and committed

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function in
`yascheduler/application/abandon_node.py` that cleans up a cloud node that
never established its SSH connection, releasing the originating task to
re-allocate on the next cycle. The function SHALL accept `node: Node`,
`gateway: MachineGateway` (Protocol type), `clouds: CloudProvisioner`
(Protocol type), `uow_factory: Callable[[], AbstractUnitOfWork]`, and
`tracker: AllocationTracker`. It SHALL NOT import from `yascheduler.infra`
at runtime (TYPE_CHECKING only).

The use case SHALL NOT call `gateway.disconnect` — by construction the node
was never registered in the gateway (that is why it is being abandoned). The
use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node.cloud, node.ip)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `ip`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal (the row may already be stale, but
   removing it is idempotent and lets the orchestrator stop re-yielding the
   IP).
2. Open a UoW, call `uow.nodes.remove(node.ip)`, and commit. Failure here
   SHALL be logged at `error` level with `ip` and the exception and
   re-raised (the caller — `_connect_machine_consumer` — wraps its body in a
   try/except that keeps the worker alive, mirroring `_allocator_consumer`).
3. Open a second UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`,
   and in-memory filter for the task whose `allocated_ip == node.ip`. If
   exactly one such task exists, call `tracker.discard(task.task_id)`. If
   zero or multiple match, no `discard` is called — zero means the task has
   already advanced (e.g. operator reassignment), multiple is an
   invariant violation that SHOULD be logged at `warning` level but not
   fatal.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle with no retry counter (per
the proposal's Non-Goal on re-allocation limits). The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly, which is stronger than disabling and matches the never-connected
semantics (there is no transient-disconnect risk to protect against, since
the node was never in the gateway).

#### Scenario: Happy path — VM deleted, DB row removed, tracker released
- **WHEN** `abandon_node(node, gateway, clouds, uow_factory, tracker)` is called for a cloud node (`node.cloud` non-None) with one TO_DO task whose `allocated_ip == node.ip`
- **THEN** `clouds.deallocate(node.cloud, node.ip)` is called, `uow.nodes.remove(node.ip)` is called and committed, `tracker.discard(task.task_id)` is called for the matching task, and the function returns without raising

#### Scenario: Non-cloud node skips VM deletion
- **WHEN** `abandon_node(...)` is called with `node.cloud is None`
- **THEN** `clouds.deallocate` is NOT called, `uow.nodes.remove(node.ip)` is still called and committed, and the stuck-task lookup still runs

#### Scenario: Cloud deletion failure does not block DB cleanup
- **WHEN** `clouds.deallocate(node.cloud, node.ip)` raises an exception
- **THEN** the exception is logged at `error` level with `ip`, `cloud`, and the message, `uow.nodes.remove(node.ip)` is still called and committed, and the function continues to the stuck-task lookup

#### Scenario: DB remove failure is re-raised
- **WHEN** `uow.nodes.remove(node.ip)` or its commit raises an exception
- **THEN** the exception is logged at `error` level with `ip` and the message, and the exception is re-raised (the caller keeps the worker alive via its outer try/except)

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
