## MODIFIED Requirements

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