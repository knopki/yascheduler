## MODIFIED Requirements

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function
SHALL accept `task_id: TaskId` (was `int`), `uow_factory`, `repository:
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
insertion, cloud allocation (via `clouds.allocate(selection)`), final
node persistence, and tmp-node cleanup on failure. The
`allocation_lock` SHALL serialize the capacity-read + select + add_tmp
critical section as a single UoW with commit before lock release.

The tmp-node cleanup paths (`_cleanup_tmp_node_best_effort` and the
`_persist_node_with_cleanup` failure/success paths) SHALL resolve the
`NodeId` by calling `uow.nodes.get(tmp_ip)` before `uow.nodes.remove(node.node_id)`.
If `get` returns `None` (row already removed), the `remove` call SHALL be
skipped (no rowcount check — matches prior no-op-on-0-rows behavior). The
`get` lookup is best-effort inside the existing `try/except` wrapper;
failures are logged, not raised.

#### Scenario: Allocate to free machine
- **WHEN** `allocate_task(task_id, engines, uow_factory, repository, operations, clouds, start_task_on_machine, tracker, allocation_lock)` is called (with `task_id: TaskId`) and a free compatible machine exists
- **THEN** the task is loaded via UoW (`uow.tasks.get(task_id)`), allocated via `task.allocate_to(ip)`, transitioned to RUNNING via `task.mark_running()`, saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called

#### Scenario: No free machine — cloud fallback with full ownership
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the use case calls `tracker.add(task_id)` (returns False → return immediately if already in-flight). Then opens a UoW under `allocation_lock`, reads `uow.nodes.list_all()`, calls `clouds.select_provider(platforms, counts)` (port method). If `selection is None`, calls `tracker.discard(task_id)` and returns False. Otherwise inserts a tmp-node via `uow.nodes.add_tmp(selection)`, commits, calls `clouds.allocate(selection)` outside the lock, then opens a second UoW to persist the final Node and remove the tmp-node. Returns False.

#### Scenario: Cloud allocation failure cleans up tmp-node
- **WHEN** `clouds.allocate(selection)` raises `CloudAllocateError` or `CloudSetupError` after tmp-node insertion
- **THEN** the use case opens a UoW, resolves the tmp-node via `uow.nodes.get(tmp_ip)`, and if found removes it via `uow.nodes.remove(node.node_id)`, commits, calls `tracker.discard(task_id)`, and re-raises

#### Scenario: Tmp-node cleanup looks up NodeId before remove
- **WHEN** any tmp-node cleanup path (`_cleanup_tmp_node_best_effort` or `_persist_node_with_cleanup`) runs
- **THEN** it calls `uow.nodes.get(tmp_ip)` to obtain the `Node`, and if the node exists calls `uow.nodes.remove(node.node_id)`; if `get` returns `None`, `remove` is skipped

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a `task_id: TaskId` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without creating a second VM

#### Scenario: Throttle returns None — no tmp-node inserted
- **WHEN** `clouds.select_provider(platforms, counts)` returns `None` because the selected provider's op semaphore is locked
- **THEN** the use case calls `tracker.discard(task_id)` and returns False (no tmp-node inserted, no exception raised)

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.reject("unsupported engine")`, saved, committed, and `TaskFailed` event is recorded (carrying `task_id: TaskId`)

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
(ip is the cloud host address, not node identity — out of scope to change).

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

#### Scenario: No matching TO_DO task
- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_ip == node.ip`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran

#### Scenario: Multiple matching TO_DO tasks is logged not fatal
- **WHEN** the stuck-task lookup finds more than one TO_DO task with `allocated_ip == node.ip`
- **THEN** a warning is logged, `tracker.discard` is NOT called (ambiguous which task to release), the VM deletion + DB removal still ran, and the function returns without raising

#### Scenario: No adapter imports at runtime
- **WHEN** `abandon_node.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

#### Scenario: Internal logs include node_id and ip
- **WHEN** `abandon_node` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields