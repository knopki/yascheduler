# FILE: yascheduler/application/allocate_task.py
# VERSION: 5.12.0
# START_MODULE_CONTRACT
#   PURPOSE: Allocate task use case — match a TO_DO task to a free machine or request cloud provisioning.
#   SCOPE: allocate_task async function and cloud-fallback helpers.
#   DEPENDS: M-APPLICATION-UOW, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-CLOUD-PROVISIONER, M-DOMAIN-ENGINE, M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-UOW, M-CLOUD-PROVISIONER, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-APPLICATION-ALLOCATION-TRACKER, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   allocate_task - Assign a TO_DO task to a free machine or request cloud node (UoW-based)
#   _validate_engine - Validate task engine is configured and supported
#   _allocate_free_machine - Find free machine and start task on it
#   _find_free_machines - Find free compatible machines for task allocation
#   _try_start_on_machine - Attempt to start a task on a specific machine
#   _count_nodes_by_cloud - Pure helper: count nodes by cloud prefix (shared with orchestrator)
#   _select_and_insert_tmp - Under allocation_lock, compute capacity and insert tmp-node committed before lock release
#   _cleanup_tmp_node_best_effort - Best-effort tmp-node removal; logs failures, never raises
#   _allocate_cloud_node - Call clouds.allocate (returns NewNode); cleanup tmp-node on failure then re-raise
#   _persist_node_with_cleanup - Persist final node (insert NewNode→Node + remove tmp + commit); on failure best-effort deallocate VM + tmp cleanup then re-raise
#   _provision_and_persist - Orchestrate _allocate_cloud_node then _persist_node_with_cleanup
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v5.12.0 - Cloud-fallback now persists via uow.nodes.insert(NewNode) (renamed from add); _allocate_cloud_node/_provision_and_persist return NewNode (pre-persistence; node_id is DB-generated and lives on the persisted row, not on the local object). The insert call site captures the persisted Node internally; the caller discards the NewNode (add-node-id-identity).
#   PREVIOUS_CHANGE: v5.11.0 - fix-cloud-alloc-session-lifecycle: Fix A in _find_free_machines intersects list_free with DB-enabled IPs (uow.nodes.list_enabled) so setup-in-flight tmp-nodes (enabled=FALSE) and disabled-but-not-disconnected nodes are invisible to the allocator; Fix C in _allocate_free_machine wraps each _try_start_on_machine in try/except (log + continue) so a single stale/unreachable session cannot abort the free-machine loop and starve the cloud branch.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple

from yascheduler.domain import (
    MachineSession,
    NewNode,
    Node,
    Task,
    TaskAllocated,
    TaskFailed,
    TaskStatus,
)

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable, Sequence

    from yascheduler.domain import (
        CloudProvisioner,
        Engine,
        EngineRepository,
        MachineOperations,
        MachineRepository,
    )

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


class _TmpSelection(NamedTuple):
    name: str
    ip: str


# START_CONTRACT: _validate_engine
#   PURPOSE: Validate that the task's engine is configured and supported.
#   INPUTS: {
#     task: Task - The task to validate,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory
#   }
#   OUTPUTS: { Engine | None - The resolved engine, or None if invalid }
#   SIDE_EFFECTS: Sets task error and records TaskFailed event if engine is unsupported.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS
# END_CONTRACT: _validate_engine
async def _validate_engine(
    task: Task,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> Engine | None:
    # START_BLOCK_VALIDATE_ENGINE
    engine_name: str | None = task.context.engine
    engine = engines.get(engine_name) if engine_name else None
    if engine is None:
        logger.warning(
            "Unsupported engine '%s' for task_id=%s", engine_name, task.task_id
        )
        task = task.reject("unsupported engine").with_event(
            TaskFailed, reason="unsupported engine"
        )
        async with uow_factory() as uow:
            await uow.tasks.save(task)
            await uow.commit()
        return None
    # END_BLOCK_VALIDATE_ENGINE
    return engine


# START_CONTRACT: _try_start_on_machine
#   PURPOSE: Attempt to start a task on a specific free machine.
#   INPUTS: {
#     session: MachineSession - The machine session to try,
#     engine: Engine - The resolved engine config,
#     task: Task - The task to allocate,
#     operations: MachineOperations - SSH operations for occupancy checks,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]] - Upload+spawn callback,
#     tracker: AllocationTracker - In-flight cloud allocation tracker
#   }
#   OUTPUTS: { bool - True if task started successfully on this machine }
#   SIDE_EFFECTS: Sets task running, starts occupancy check, records TaskAllocated event, discards tracker slot.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-OPERATIONS, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: _try_start_on_machine
async def _try_start_on_machine(
    session: MachineSession,
    engine: Engine,
    task: Task,
    operations: MachineOperations,
    uow_factory: Callable[[], AbstractUnitOfWork],
    start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]],
    tracker: AllocationTracker,
) -> bool:
    task = task.allocate_to(session.ip).mark_running()
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine] task_id=%s ip=%s",
        task.task_id,
        session.ip,
    )
    if not await start_task_on_machine(session, engine, task):
        return False
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine][ALLOCATED] task_id=%s ip=%s",
        task.task_id,
        session.ip,
    )
    operations.start_occupancy_check(session, engine)
    task = task.with_event(
        TaskAllocated, node_ip=session.ip, engine_name=task.context.engine
    )
    async with uow_factory() as uow:
        await uow.tasks.save(task)
        await uow.commit()
    tracker.discard(task.task_id)
    return True


# START_CONTRACT: _find_free_machines
#   PURPOSE: Find free compatible machines eligible for task allocation.
#   INPUTS: {
#     engine: Engine - The resolved engine config,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     repository: MachineRepository - SSH repository with connected machines
#   }
#   OUTPUTS: { list[MachineSession] - Free sessions matching platforms whose IP is DB-enabled and not busy }
#   SIDE_EFFECTS: Reads uow.tasks.list_by_status({RUNNING}) and uow.nodes.list_enabled() in the same UoW. Enabled-gate invariant: a session is returned ONLY if its machine.ip is in the set of DB-enabled node IPs, so setup-in-flight tmp-nodes (enabled=FALSE) and disabled-but-not-disconnected nodes are excluded.
#   LINKS: M-DOMAIN-MODEL, M-SSH-REPOSITORY, M-PERSISTENCE-UOW
# END_CONTRACT: _find_free_machines
async def _find_free_machines(
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    repository: MachineRepository,
) -> list[MachineSession]:
    # START_BLOCK_FIND_FREE_MACHINES
    async with uow_factory() as uow:
        running_tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
        enabled_nodes = await uow.nodes.list_enabled()
    busy_node_ips = {t.allocated_ip for t in running_tasks if t.allocated_ip}
    enabled_ips = {n.ip for n in enabled_nodes}
    free_sessions = [
        s
        for s in repository.list_free(platforms=list(engine.platforms))
        if s.machine.ip in enabled_ips and s.machine.ip not in busy_node_ips
    ]
    return free_sessions
    # END_BLOCK_FIND_FREE_MACHINES


# START_CONTRACT: _allocate_free_machine
#   PURPOSE: Find a free compatible machine and start the task on it.
#   INPUTS: { task: Task, engine: Engine, uow_factory: Callable, repository: MachineRepository, operations: MachineOperations,
#     start_task_on_machine: Callable, tracker: AllocationTracker }
#   OUTPUTS: { bool - True if allocated to a machine, False if not }
#   SIDE_EFFECTS: Updates task status, starts occupancy check, records TaskAllocated event, discards tracker slot. Per-session failures are isolated: each _try_start_on_machine call is wrapped in try/except Exception, logged at error with task_id and ip, and the loop continues to the next session. A transient SSH failure does NOT call repository.disconnect — the monitor task owns session lifecycle. No exception propagates out of the loop.
#   LINKS: M-DOMAIN-MODEL, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: _allocate_free_machine
async def _allocate_free_machine(
    task: Task,
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    repository: MachineRepository,
    operations: MachineOperations,
    start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]],
    tracker: AllocationTracker,
) -> bool:
    free_sessions = await _find_free_machines(engine, uow_factory, repository)

    # START_BLOCK_ALLOCATE_MACHINE
    for session in free_sessions:
        # START_BLOCK_TRY_START_ISOLATED
        # Defense-in-depth: a single stale or transiently-unreachable session
        # must not abort the loop and starve the cloud-provisioning branch.
        # No repository.disconnect here — a transient SSH failure does not
        # imply a dead session; the monitor task manages its lifecycle.
        # Stale sessions left by failed setup are prevented at the source by
        # the setup-failure disconnect in CloudProvisionerImpl.allocate.
        try:
            if await _try_start_on_machine(
                session,
                engine,
                task,
                operations,
                uow_factory,
                start_task_on_machine,
                tracker,
            ):
                return True
        except Exception as err:
            logger.debug(
                "[AllocateTask][_allocate_free_machine][SESSION_FAILED] "
                "task_id=%s ip=%s err=%s",
                task.task_id,
                session.ip,
                err,
            )
            continue
        # END_BLOCK_TRY_START_ISOLATED
    # END_BLOCK_ALLOCATE_MACHINE

    return False


# START_CONTRACT: _count_nodes_by_cloud
#   PURPOSE: Build a {cloud_prefix: count} map from a node list, skipping nodes with cloud=None.
#   INPUTS: { nodes: Sequence[Node] - nodes to count }
#   OUTPUTS: { dict[str, int] - cloud prefix -> node count }
#   SIDE_EFFECTS: None — pure transform.
#   LINKS: M-DOMAIN-MODEL
# END_CONTRACT: _count_nodes_by_cloud
def _count_nodes_by_cloud(nodes: Sequence[Node]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in nodes:
        if n.cloud:
            counts[n.cloud] = counts.get(n.cloud, 0) + 1
    return counts


# START_CONTRACT: _select_and_insert_tmp
#   PURPOSE: Under allocation_lock, compute provider capacity, call select_provider port, and insert tmp-node in a single UoW committed before lock release.
#   INPUTS: {
#     clouds: CloudProvisioner - Cloud port (select_provider called sync),
#     engine: Engine - Resolved engine config (source of platforms),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     allocation_lock: asyncio.Lock - Critical-section lock
#   }
#   OUTPUTS: { _TmpSelection | None - selected provider name + tmp-node ip, or None if no provider available }
#   SIDE_EFFECTS: Reads uow.nodes.list_all, inserts tmp-node, commits under lock. Concurrent selectors observe the tmp-node after lock release.
#   LINKS: M-CLOUD-PROVISIONER, M-APPLICATION-UOW
# END_CONTRACT: _select_and_insert_tmp
async def _select_and_insert_tmp(
    clouds: CloudProvisioner,
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    allocation_lock: asyncio.Lock,
) -> _TmpSelection | None:
    # START_BLOCK_CAPACITY_AND_SELECT
    async with allocation_lock:
        async with uow_factory() as uow:
            nodes = await uow.nodes.list_all()
            counts = _count_nodes_by_cloud(nodes)
            selected_name = clouds.select_provider(list(engine.platforms), counts)
            if selected_name is None:
                return None
            tmp_ip = await uow.nodes.add_tmp(selected_name)
            await uow.commit()
            return _TmpSelection(name=selected_name, ip=tmp_ip)
    # END_BLOCK_CAPACITY_AND_SELECT


# START_CONTRACT: _cleanup_tmp_node_best_effort
#   PURPOSE: Best-effort tmp-node removal; logs failures, never raises.
#   INPUTS: {
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     tmp_ip: str - The tmp-node IP to remove,
#     task_id: int - For log correlation,
#     context: str - Why cleanup is running (e.g. "cloud-alloc-failed")
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens UoW, removes tmp-node, commits. Failures logged only — never re-raised.
#   LINKS: M-APPLICATION-UOW
# END_CONTRACT: _cleanup_tmp_node_best_effort
async def _cleanup_tmp_node_best_effort(
    uow_factory: Callable[[], AbstractUnitOfWork],
    tmp_ip: str,
    task_id: int,
    context: str,
) -> None:
    # START_BLOCK_BEST_EFFORT_TMP_CLEANUP
    try:
        async with uow_factory() as uow:
            await uow.nodes.remove(tmp_ip)
            await uow.commit()
    except Exception as cleanup_err:
        logger.error(
            "[AllocateTask][allocate_task][TMP_CLEANUP_FAILED] "
            "task_id=%s ctx=%s tmp_ip=%s err=%s",
            task_id,
            context,
            tmp_ip,
            cleanup_err,
        )
    # END_BLOCK_BEST_EFFORT_TMP_CLEANUP


# START_CONTRACT: _allocate_cloud_node
#   PURPOSE: Call clouds.allocate; on failure run best-effort tmp-node cleanup then re-raise so the caller sees the original cloud-allocation error.
#   INPUTS: {
#     clouds: CloudProvisioner - Cloud port (allocate),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory (for cleanup),
#     selected_name: str - Provider name to allocate,
#     tmp_ip: str - tmp-node IP committed by _select_and_insert_tmp,
#     task_id: int - For log correlation
#   }
#   OUTPUTS: { NewNode - The provisioned cloud node (not yet persisted; no node_id) }
#   SIDE_EFFECTS: Calls clouds.allocate. On failure opens a UoW to remove+commit the tmp-node (best-effort, logged not raised).
#   RAISES: { Exception - Original cloud-allocation exception, never a cleanup exception }
#   LINKS: M-CLOUD-PROVISIONER, M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: _allocate_cloud_node
async def _allocate_cloud_node(
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    selected_name: str,
    tmp_ip: str,
    task_id: int,
) -> NewNode:
    # START_BLOCK_CLOUD_ALLOCATE
    try:
        node = await clouds.allocate(selected_name)
    except Exception as err:
        logger.error(
            "[AllocateTask][allocate_task][CLOUD_FAILED] task_id=%s err=%s",
            task_id,
            err,
        )
        # Best-effort tmp-node cleanup; failure here is logged but does
        # not mask the original cloud-allocation exception.
        await _cleanup_tmp_node_best_effort(
            uow_factory, tmp_ip, task_id, "cloud-alloc-failed"
        )
        raise
    # END_BLOCK_CLOUD_ALLOCATE
    return node


# START_CONTRACT: _persist_node_with_cleanup
#   PURPOSE: Persist the final node (insert NewNode→Node + remove tmp + commit); on failure best-effort delete the billable orphan VM and remove the tmp-node, then re-raise the original persist error.
#   INPUTS: {
#     node: NewNode - Provisioned (but not yet persisted) cloud node (no node_id),
#     clouds: CloudProvisioner - Cloud port (deallocate on persist failure),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     selected_name: str - Provider name (fallback if node.cloud is None),
#     tmp_ip: str - tmp-node IP to remove,
#     task_id: int - For log correlation
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens UoW, inserts the NewNode (receiving the persisted Node), removes tmp, commits. On failure: best-effort clouds.deallocate + tmp-node cleanup (logged not raised), then re-raises.
#   RAISES: { Exception - Original persist exception, never a cleanup exception }
#   LINKS: M-CLOUD-PROVISIONER, M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: _persist_node_with_cleanup
async def _persist_node_with_cleanup(
    node: NewNode,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    selected_name: str,
    tmp_ip: str,
    task_id: int,
) -> None:
    # START_BLOCK_FINAL_PERSIST
    try:
        async with uow_factory() as uow:
            await uow.nodes.insert(node)
            await uow.nodes.remove(tmp_ip)
            await uow.commit()
    except Exception as persist_err:
        logger.error(
            "[AllocateTask][allocate_task][PERSIST_FAILED] task_id=%s ip=%s err=%s",
            task_id,
            node.ip,
            persist_err,
        )
        # VM is up and billing but has no DB row; best-effort delete so we
        # don't leak a billable orphan. Failure here is logged not raised.
        # node.cloud is str|None on the model, but the node just came back
        # from clouds.allocate(selected_name) — fall back to selected_name
        # to satisfy the port's str contract.
        cloud_name = node.cloud or selected_name
        try:
            await clouds.deallocate(cloud_name, node.ip)
        except Exception as dealloc_err:
            logger.error(
                "[AllocateTask][allocate_task][DEALLOC_FAILED] task_id=%s ip=%s err=%s",
                task_id,
                node.ip,
                dealloc_err,
            )
        await _cleanup_tmp_node_best_effort(
            uow_factory, tmp_ip, task_id, "persist-failed"
        )
        raise
    # END_BLOCK_FINAL_PERSIST

    logger.debug(
        "[AllocateTask][allocate_task][CLOUD_DONE] task_id=%s ip=%s provider=%s",
        task_id,
        node.ip,
        selected_name,
    )


# START_CONTRACT: _provision_and_persist
#   PURPOSE: Provision cloud VM via _allocate_cloud_node then persist via _persist_node_with_cleanup; on any post-allocate failure, best-effort cleanup (deallocate VM + remove tmp-node) preserves the original exception so the caller sees the real cause.
#   INPUTS: {
#     clouds: CloudProvisioner - Cloud port (allocate/deallocate),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     selected_name: str - Provider name to allocate,
#     tmp_ip: str - tmp-node IP committed by _select_and_insert_tmp,
#     task_id: int - For log correlation
#   }
#   OUTPUTS: { NewNode - The provisioned cloud node (now persisted; the DB-generated node_id lives in the committed row, not on this object) }
#   SIDE_EFFECTS: Calls clouds.allocate; opens UoW to insert+remove+commit. On persist failure calls clouds.deallocate (best-effort) + tmp-node cleanup (best-effort), then re-raises original.
#   RAISES: { Exception - Original cloud-allocate or persist exception, never a cleanup exception }
#   LINKS: M-CLOUD-PROVISIONER, M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: _provision_and_persist
async def _provision_and_persist(
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    selected_name: str,
    tmp_ip: str,
    task_id: int,
) -> NewNode:
    node = await _allocate_cloud_node(
        clouds, uow_factory, selected_name, tmp_ip, task_id
    )
    await _persist_node_with_cleanup(
        node, clouds, uow_factory, selected_name, tmp_ip, task_id
    )
    return node


# START_CONTRACT: allocate_task
#   PURPOSE: Match a TO_DO task to a free compatible machine or request cloud allocation.
#   INPUTS: {
#     task_id: int - The task id to allocate,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     repository: MachineRepository, operations: MachineOperations - SSH gateway with connected machines,
#     clouds: CloudProvisioner - Cloud provider port,
#     start_task_on_machine: Callable - Callback to upload+spawn on remote machine,
#     tracker: AllocationTracker - In-flight cloud allocation tracker,
#     allocation_lock: asyncio.Lock - Lock for critical section coordination
#   }
#   OUTPUTS: { bool - True if allocated to a machine, False if cloud requested or error }
#   SIDE_EFFECTS: May update task status in DB, start occupancy check, record events (TaskAllocated/TaskFailed), tracker.add/discard lifecycle, tmp-node insertion, cloud allocation via port. On cloud-fallback failure the VM and tmp-node are best-effort cleaned up by _provision_and_persist.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: allocate_task
async def allocate_task(
    task_id: int,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    repository: MachineRepository,
    operations: MachineOperations,
    clouds: CloudProvisioner,
    start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]],
    tracker: AllocationTracker,
    allocation_lock: asyncio.Lock,
) -> bool:
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
    if task is None:
        return False

    logger.debug("[AllocateTask][allocate_task] task_id=%s", task.task_id)

    engine = await _validate_engine(task, engines, uow_factory)
    if engine is None:
        return False

    if await _allocate_free_machine(
        task,
        engine,
        uow_factory,
        repository,
        operations,
        start_task_on_machine,
        tracker,
    ):
        return True

    # Empty-platform engines are eligible for free machines (matched above) but
    # never for cloud provisioning — select_provider would silently return None
    # and the task would spin in TO_DO forever. Short-circuit with a warning
    # before entering the cloud critical section.
    if not engine.platforms:
        logger.warning(
            "[AllocateTask][allocate_task][NO_PLATFORM] task_id=%s engine=%s "
            "has no platforms; cannot cloud-provision",
            task.task_id,
            engine.name,
        )
        return False

    # START_BLOCK_ALLOCATE_CLOUD_CRITICAL_SECTION
    logger.debug("[AllocateTask][allocate_task][CLOUD] task_id=%s", task.task_id)

    # Step 0: tracker dedup
    if not tracker.add(task.task_id):
        logger.debug(
            "[AllocateTask][allocate_task][DEDUP] task_id=%s already in-flight",
            task.task_id,
        )
        return False

    # success-flag guarantees tracker.discard on any exception escaping the
    # cloud-fallback (step1 commit/add_tmp fail, step2 cloud-alloc fail, step3
    # final persist fail) while preserving the entry on the success path
    # (VM provisioned, awaiting consume_task / next-cycle free-machine start).
    cloud_allocated = False
    tmp_ip: str | None = None
    tmp_owned_by_provisioner = False
    try:
        selected = await _select_and_insert_tmp(
            clouds, engine, uow_factory, allocation_lock
        )
        if selected is None:
            logger.debug(
                "[AllocateTask][allocate_task][NO_PROVIDER] task_id=%s",
                task.task_id,
            )
            return False
        selected_name = selected.name
        tmp_ip = selected.ip
        # _provision_and_persist and its internals own tmp-node cleanup on
        # any exception they raise. The outer finally only cleans up when
        # the hand-off never happened (defensive against an unexpected raise
        # between tmp commit and provisioner entry).
        tmp_owned_by_provisioner = True
        await _provision_and_persist(
            clouds, uow_factory, selected_name, tmp_ip, task.task_id
        )
        cloud_allocated = True
        return False
    finally:
        if not cloud_allocated:
            tracker.discard(task.task_id)
            if tmp_ip is not None and not tmp_owned_by_provisioner:
                await _cleanup_tmp_node_best_effort(
                    uow_factory, tmp_ip, task.task_id, "allocator-unexpected"
                )
    # END_BLOCK_ALLOCATE_CLOUD_CRITICAL_SECTION
