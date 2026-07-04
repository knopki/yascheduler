## MODIFIED Requirements

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function SHALL
accept `task_id: TaskId`, `uow_factory`, `repository: MachineRepository`
(Protocol type), `operations: MachineOperations` (Protocol type), `clouds:
CloudProvisioner` (Protocol type), `tracker: AllocationTracker`, and
`allocation_lock: asyncio.Lock`. It SHALL NOT import from `yascheduler.infra` at
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
`clouds.allocate(selection, tmp_node_id)` returning a `Node` reusing
`tmp_node_id`), final node persistence via `uow.nodes.update(node)` (a
single UPDATE flipping `enabled=TRUE` and setting `ip`/`ncpus`), and
tmp-node cleanup on failure (`uow.nodes.remove(tmp_node_id)`). The
`allocation_lock` SHALL serialize the capacity-read + select + tmp-insert
critical section as a single UoW with commit before lock release.

The tmp-node handle is a `NodeId`, not a placeholder IP. The internal
`_TmpSelection` NamedTuple SHALL carry `name: str` and `node_id: NodeId` (NOT
`ip: str`). `_select_and_insert_tmp` SHALL call
`uow.nodes.insert(NewNode(cloud=selected_name, enabled=False)) -> Node` and
return `_TmpSelection(name=selected_name, node_id=tmp_node.node_id)`. The
`NewNode.ip=""` and `NewNode.ncpus=0` defaults supply the tmp-row's `ip` and
`ncpus` columns.

The tmp-node cleanup paths (`_cleanup_tmp_node_best_effort`,
`_allocate_cloud_node`, `_provision_and_persist`) SHALL take
`tmp_node_id: NodeId` and call `uow.nodes.remove(tmp_node_id)` directly on
failure. `remove(tmp_node_id)` is idempotent: `DELETE WHERE node_id =
:node_id` affecting 0 rows is a no-op. Failures in best-effort cleanup are
logged, not raised.

The final-persistence path (`_provision_and_persist`) SHALL call
`clouds.allocate(selection, tmp_node_id) -> Node` (the cloud adapter reuses
`tmp_node_id` as the `Node`'s `node_id`), then `uow.nodes.update(node)` (a
single UPDATE flipping `enabled=TRUE` and setting `ip`/`ncpus`), then commit,
in one UoW. The prior `insert(NewNode) + remove(tmp_node_id)` pair is
replaced by a single `update` — one row per cloud allocation lifecycle, not
two. If the persist fails, the VM is best-effort deallocated via
`clouds.deallocate(cloud_name, node.ip)` and the tmp-node is best-effort
cleaned up via `_cleanup_tmp_node_best_effort`; the original exception is
re-raised.

`_find_free_machines` SHALL return `list[tuple[MachineSession, Node]]` (NOT
`list[MachineSession]`). It SHALL build `nodes_by_id = {n.node_id: n for n
in enabled_nodes}` from `uow.nodes.list_enabled()` and pair each free
session with its matching `Node`: `[(s, nodes_by_id[s.machine.node_id]) for
s in repository.list_free(platforms=...) if s.machine.node_id in
nodes_by_id and s.machine.node_id not in busy_node_ids]` where
`busy_node_ids = {t.allocated_node_id for t in running_tasks if
t.allocated_node_id}`. Session↔Node matching is by `node_id` — dup-IP nodes
no longer collapse (two enabled nodes sharing an `ip` have distinct
`node_id` keys in `nodes_by_id`, and each session matches its own node via
`s.machine.node_id`).

`_try_start_on_machine` SHALL take `(session: MachineSession, node: Node)` and
call `task.allocate_to(node)` (binding both `allocated_ip` and
`allocated_node_id` in the single `allocate_to` call). The
`_allocate_free_machine` loop SHALL iterate `(session, node)` pairs from
`_find_free_machines` and pass both to `_try_start_on_machine`. Internal log
lines in `_try_start_on_machine` SHALL include `node_id=%s` alongside
`ip=%s`.

#### Scenario: Allocate to free machine

- **WHEN** `allocate_task(task_id, engines, uow_factory, repository, operations, clouds, start_task_on_machine, tracker, allocation_lock)` is called (with `task_id: TaskId`) and a free compatible machine exists
- **THEN** the task is loaded via UoW (`uow.tasks.get(task_id)`), `_find_free_machines` returns `list[(MachineSession, Node)]`, `_try_start_on_machine(session, node)` is called, the task is allocated via `task.allocate_to(node)` (binding both `allocated_ip` and `allocated_node_id`), transitioned to RUNNING via `task.mark_running()`, saved via `uow.tasks.save()` (which writes both `allocated_ip` and `allocated_node_id`), committed, and `tracker.discard(task_id)` is called

#### Scenario: No free machine — cloud fallback with full ownership and single-row UPDATE

- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the use case calls `tracker.add(task_id)` (returns False → return immediately if already in-flight). Then opens a UoW under `allocation_lock`, reads `uow.nodes.list_all()`, calls `clouds.select_provider(platforms, counts)`. If `selection is None`, calls `tracker.discard(task_id)` and returns False. Otherwise inserts a tmp-node via `uow.nodes.insert(NewNode(cloud=selection, enabled=False)) -> Node` (node_id=T), commits (lock released), calls `clouds.allocate(selection, tmp_node_id=T) -> Node` (node_id=T, enabled=True, ip, ncpus) outside the lock, then opens a second UoW to `uow.nodes.update(node)` (UPDATE row T: enabled=TRUE, ip, ncpus) and commits. Returns False.

#### Scenario: Tmp-node insertion uses insert not add_tmp

- **WHEN** the cloud-fallback critical section inserts a tmp-node
- **THEN** it calls `uow.nodes.insert(NewNode(cloud=selected_name, enabled=False))` (NOT `uow.nodes.add_tmp(...)`); the returned `Node.node_id` becomes the `_TmpSelection.node_id` cleanup handle AND the real-node identity reused by `clouds.allocate`

#### Scenario: Cloud allocation failure cleans up tmp-node by node_id

- **WHEN** `clouds.allocate(selection, tmp_node_id)` raises `CloudAllocateError` or `CloudSetupError` after tmp-node insertion
- **THEN** the use case calls `_cleanup_tmp_node_best_effort(uow_factory, tmp_node_id, ...)` which calls `uow.nodes.remove(tmp_node_id)` and commits, calls `tracker.discard(task_id)`, and re-raises

#### Scenario: Final persistence is a single UPDATE, not insert+remove

- **WHEN** `_provision_and_persist` runs after `clouds.allocate` succeeded
- **THEN** it opens a UoW, calls `uow.nodes.update(node)` (the `Node` returned by `clouds.allocate`, carrying `node_id == tmp_node_id`, `enabled=True`, real `ip`, `ncpus`), and commits; it does NOT call `uow.nodes.insert` or `uow.nodes.remove` (the row already exists from `_select_and_insert_tmp`)

#### Scenario: Final persistence failure best-effort deallocates VM and cleans tmp-node

- **WHEN** `uow.nodes.update(node)` or its commit raises after `clouds.allocate` succeeded
- **THEN** the use case best-effort calls `clouds.deallocate(cloud_name, node.ip)` (logged not raised), best-effort calls `_cleanup_tmp_node_best_effort(uow_factory, tmp_node_id, ...)` (logged not raised), and re-raises the original persist exception

#### Scenario: Duplicate allocation rejected by tracker

- **WHEN** `allocate_task` is called for a `task_id: TaskId` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without creating a second VM

#### Scenario: Throttle returns None — no tmp-node inserted

- **WHEN** `clouds.select_provider(platforms, counts)` returns `None` because the selected provider's op semaphore is locked
- **THEN** the use case calls `tracker.discard(task_id)` and returns False (no tmp-node inserted, no exception raised)

#### Scenario: Unsupported engine

- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.reject("unsupported engine")`, saved, committed, and `TaskFailed` event is recorded (carrying `task_id: TaskId`)

#### Scenario: _find_free_machines returns session-node pairs matched by node_id

- **WHEN** `_find_free_machines(engine, uow_factory, repository)` is called and free compatible machines exist
- **THEN** it returns `list[tuple[MachineSession, Node]]` where each `Node` carries `node_id`, paired by `s.machine.node_id == node.node_id`; the `Node` is sourced from `uow.nodes.list_enabled()` and carried forward so the bind site has `node.node_id`

#### Scenario: _find_free_machines disambiguates dup-IP nodes by node_id

- **WHEN** two enabled nodes share the same `ip` (dup-IP configuration) with distinct `node_id`s, and a free session exists for each (each session's `machine.node_id` matches its respective node)
- **THEN** `nodes_by_id = {n.node_id: n}` keeps both nodes (no collapse); each session is paired with its own `Node` via `s.machine.node_id`; both pairs are returned (the prior `nodes_by_ip` collapse that dropped one duplicate is resolved)

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and finalises or defers the task. The function
SHALL accept `task_id: TaskId`, `session: MachineSession` (resolved by the
orchestrator via `repository.get_session(task.allocated_node_id)`),
`operations: MachineOperations` (Protocol type, for `download_outputs`),
`engines: EngineRepository`, `uow_factory: Callable[[], AbstractUnitOfWork]`,
`local_tasks_dir: Path`, and `tracker: AllocationTracker`. It SHALL NOT import
`SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime.

The function SHALL return `bool`: `True` when the task is finalised (DONE
status applied, remote directory cleaned by the operations, in-flight
allocation slot released via `tracker.discard(task_id)`); `False` when the
task is deferred for retry (status unchanged, remote directory preserved by
the operations, in-flight allocation slot NOT released).

The function SHALL receive the `session` directly (resolved by the
orchestrator from `task.allocated_node_id` via
`repository.get_session(node_id)`) and delegate SFTP download with retry and
error classification to `operations.download_outputs(session, ...)`.
`download_outputs` receives `task_id=task.task_id` (a `TaskId`); it uses the
value for logging and remote folder naming, where `TaskId.__str__` renders
the bare integer. The function SHALL receive `(meta_add, transient_errors,
permanent_errors)` from `download_outputs` and branch on them:

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

- **WHEN** `consume_task(task_id, session, operations, engines, uow_factory, local_tasks_dir, tracker)` is called (with `task_id: TaskId`) on a completed task and `download_outputs` returns empty `transient_errors` and empty `permanent_errors`
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

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept `uow_factory`,
`config_clouds: Sequence[CloudConfig]`, and `idle_machines: dict[NodeId, float]`
(`NodeId` -> free_since monotonic timestamp). It SHALL NOT accept `repository`
or `operations` (the per-node SSH/cloud teardown lives in `deallocate_node`).

The per-node wrapper `deallocate_node(node, repository, clouds, uow_factory)`
SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(cloud, ip)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

`deallocate_node` SHALL call `uow.nodes.disable(node.node_id)` and
`uow.nodes.remove(node.node_id)` (keying on `node_id`, not `ip`).
`clouds.deallocate(node.cloud, node.ip)` SHALL continue to take `ip`
(ip is the cloud host address, not node identity). `deallocate_node` SHALL
call `repository.contains(node.node_id)` and `repository.disconnect(node.node_id)`
BEFORE the `if node.cloud:` guard, so SSH teardown is owned by
`deallocate_node` and runs regardless of whether the node is a cloud node.

`deallocate_nodes` SHALL iterate the enabled nodes returned by
`uow.nodes.list_enabled()` and call `uow.nodes.disable(node.node_id)` for
each node whose `node_id` is in `idle_machines` and whose `node_id` is not
in `busy_node_ids` (the node_ids of RUNNING tasks' `allocated_node_id`).

`deallocate_nodes` SHALL return `list[Node]` (was `list[str]`). Phase 2
(collect free disabled cloud nodes) SHALL return the `Node` objects it
reads from `uow.nodes.list_disabled()`, each carrying `node_id`, instead
of discarding them to bare `ip` strings. This eliminates the
`uow.nodes.get(ip)` round-trip lookup previously performed by the
orchestrator's `_deallocator_consumer` to reconstruct the `Node` from `ip`.

`deallocate_nodes` phase 2 SHALL filter disabled nodes by
`node.node_id not in busy_node_ids and node.cloud`. The prior `"." in node.ip`
post-filter SHALL NOT be present — it was dead code from the fake-ip era.

Internal log lines in both `deallocate_nodes` and `deallocate_node` SHALL
include both `node_id` and `ip` for correlation.

#### Scenario: Idle cloud node disabled

- **WHEN** `deallocate_nodes(uow_factory, config_clouds, idle_machines)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the `Node` (carrying `node_id`) is included in the returned `list[Node]` for orchestrator-level SSH disconnect and cloud deallocation

#### Scenario: Non-cloud node skipped

- **WHEN** a non-cloud node (`node.cloud is None`) is idle
- **THEN** it is not disabled in phase 1 (filtered by `node.cloud == ccfg.prefix`) and not included in the returned `list[Node]` (phase 2 filters `and node.cloud`)

#### Scenario: Returns disabled Node objects carrying node_id

- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a `list[Node]` is returned (was `list[str]` of IPs); each `Node` carries its `node_id`, `ip`, `cloud`, and other fields, so the orchestrator's `_deallocator_consumer` can call `deallocate_node(node, ...)` directly without a `uow.nodes.get(ip)` round-trip lookup

#### Scenario: Phase 2 filters by node_id not in busy_node_ids

- **WHEN** `deallocate_nodes` phase 2 filters disabled nodes
- **THEN** the filter is `node.node_id not in busy_node_ids and node.cloud` — the `"." in node.ip` guard is NOT present (dead code from the fake-ip era; `list_disabled.sql` `WHERE ip <> ''` already excludes tmp-node rows at SQL level)

#### Scenario: Deallocate node brackets cloud delete with disable+remove

- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` is called for a cloud node
- **THEN** the node's SSH session is disconnected via `repository.contains(node.node_id)` + `repository.disconnect(node.node_id)` (before the `if node.cloud:` guard), then the node is disabled via `uow.nodes.disable(node.node_id)` and committed, then `clouds.deallocate(node.cloud, node.ip)` is called, then the node is removed via `uow.nodes.remove(node.node_id)` and committed

#### Scenario: Internal logs include node_id and ip

- **WHEN** `deallocate_node` or `deallocate_nodes` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function in
`yascheduler/application/abandon_node.py` that cleans up a cloud node that
never established its SSH connection, releasing the originating task to
re-allocate on the next cycle. The function SHALL accept `node: Node`,
`clouds: CloudProvisioner` (Protocol type), `uow_factory: Callable[[],
AbstractUnitOfWork]`, and `tracker: AllocationTracker`. It SHALL NOT import
from `yascheduler.infra` at runtime (TYPE_CHECKING only).

The use case SHALL NOT call `repository.disconnect` — by construction the
node was never registered in the repository (that is why it is being
abandoned). The use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node.cloud, node.ip)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `node_id`, `ip`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal.
2. Open a UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`, and
   in-memory filter for the task whose `allocated_node_id == node.node_id`.
   This read SHALL happen BEFORE the node-row removal in step 3 — the
   `allocated_node_id` FK is `ON DELETE SET NULL`, so removing the node row
   first would null `allocated_node_id` and the in-memory filter would no
   longer match. Hold the matching task(s) in memory.
3. Open a UoW, call `uow.nodes.remove(node.node_id)`, and commit. Failure here
   SHALL be logged at `error` level with `node_id`, `ip`, and the exception and
   re-raised.
4. If exactly one matching task was found in step 2, call
   `tracker.discard(task.task_id)`. If zero or multiple matched, no `discard`
   is called.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle. The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly.

Internal log lines SHALL include both `node_id` and `ip` for correlation.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released

- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a cloud node (`node.cloud` non-None) with one TO_DO task whose `allocated_node_id == node.node_id`
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

- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_node_id == node.node_id`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran

#### Scenario: Multiple matching TO_DO tasks is logged not fatal

- **WHEN** the stuck-task lookup finds more than one TO_DO task with `allocated_node_id == node.node_id`
- **THEN** a warning is logged, `tracker.discard` is NOT called (ambiguous which task to release), the VM deletion + DB removal still ran, and the function returns without raising

#### Scenario: No adapter imports at runtime

- **WHEN** `abandon_node.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)