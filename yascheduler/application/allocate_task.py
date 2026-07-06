# FILE: yascheduler/application/allocate_task.py
# VERSION: 5.19.0
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
#   _allocate_free_machine - Find free machine and start task on it; iterates (session, node) pairs
#   _find_free_machines - Find free compatible machines for task allocation; returns list[tuple[MachineSession, Node]] paired by s.machine.node_id (dup-IP disambiguated — distinct node_id keys)
#   _try_start_on_machine - Attempt to start a task on a specific (session, node) pair; calls allocate_to(node) binding both allocated_ip and allocated_node_id; emits TaskAllocated with node_id=node.node_id
#   _count_nodes_by_cloud - Pure helper: count nodes by cloud prefix (shared with orchestrator)
#   _TmpSelection - NamedTuple(name: str, node: Node) — tmp-node handle is the Node from insert, reused as the real node identity by clouds.allocate
#   _select_and_insert_tmp - Under allocation_lock, compute capacity, select provider, insert tmp-node via insert(NewNode(cloud=..., enabled=False)); returns _TmpSelection(name, node)
#   _cleanup_tmp_node_best_effort - Best-effort tmp-node removal by NodeId (remove(tmp_node_id) directly — no get lookup); logs failures, never raises
#   _allocate_cloud_node - Call clouds.allocate(provider, tmp_node: Node) (returns Node reusing tmp_node.node_id); cleanup tmp-node by NodeId on failure then re-raise (takes tmp_node: Node)
#   _persist_node_with_cleanup - Persist final node via single uow.nodes.update(node) (flips enabled=TRUE, sets ip/ncpus — V1 single-row lifecycle); on failure best-effort deallocate VM via clouds.deallocate(node) + tmp cleanup then re-raise (takes tmp_node_id: NodeId)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v5.19.0 - drop-task-context-entity: _validate_engine and _try_start_on_machine read task.engine; with_event(TaskAllocated, ..., engine_name=task.engine).
#   PREVIOUS_CHANGE: v5.18.0 - cloud-port-node-arg: _TmpSelection carries the tmp Node (was node_id); _allocate_cloud_node takes tmp_node: Node; _persist_node_with_cleanup calls clouds.deallocate(node) (dropped selected_name param + cloud_name fallback).
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple

from yascheduler.domain import (
    MachineSession,
    NewNode,
    Node,
    NodeId,
    Task,
    TaskAllocated,
    TaskFailed,
    TaskId,
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
    node: Node


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
    engine_name: str | None = task.engine
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
#   PURPOSE: Attempt to start a task on a specific (session, node) pair.
#   INPUTS: {
#     session: MachineSession - The machine session to try,
#     node: Node - The Node paired with the session (carries node_id for allocate_to),
#     engine: Engine - The resolved engine config,
#     task: Task - The task to allocate,
#     operations: MachineOperations - SSH operations for occupancy checks,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]] - Upload+spawn callback,
#     tracker: AllocationTracker - In-flight cloud allocation tracker
#   }
#   OUTPUTS: { bool - True if task started successfully on this machine }
#   SIDE_EFFECTS: Sets task running via allocate_to(node) (binding both allocated_ip and allocated_node_id), starts occupancy check, records TaskAllocated event, discards tracker slot. Log lines include node_id=%s alongside ip=%s.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-OPERATIONS, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: _try_start_on_machine
async def _try_start_on_machine(
    session: MachineSession,
    node: Node,
    engine: Engine,
    task: Task,
    operations: MachineOperations,
    uow_factory: Callable[[], AbstractUnitOfWork],
    start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]],
    tracker: AllocationTracker,
) -> bool:
    task = task.allocate_to(node).mark_running()
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine] task_id=%s ip=%s node_id=%s",
        task.task_id,
        session.ip,
        node.node_id,
    )
    if not await start_task_on_machine(session, engine, task):
        return False
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine][ALLOCATED] "
        "task_id=%s ip=%s node_id=%s",
        task.task_id,
        session.ip,
        node.node_id,
    )
    operations.start_occupancy_check(session, engine)
    task = task.with_event(TaskAllocated, node_id=node.node_id, engine_name=task.engine)
    async with uow_factory() as uow:
        await uow.tasks.save(task)
        await uow.commit()
    tracker.discard(task.task_id)
    return True


# START_CONTRACT: _find_free_machines
#   PURPOSE: Find free compatible machines eligible for task allocation, paired with their Node (matched by node_id — dup-IP nodes no longer collapse).
#   INPUTS: {
#     engine: Engine - The resolved engine config,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     repository: MachineRepository - SSH repository with connected machines
#   }
#   OUTPUTS: { list[tuple[MachineSession, Node]] - Free sessions paired with their matching Node (by s.machine.node_id), Node carries node_id }
#   SIDE_EFFECTS: Reads uow.tasks.list_by_status({RUNNING}) and uow.nodes.list_enabled() in the same UoW. Builds nodes_by_id = {n.node_id: n for n in enabled_nodes} and busy_node_ids = {t.allocated_node_id for t in running_tasks if t.allocated_node_id}. Session↔Node matching is by s.machine.node_id — two enabled nodes sharing an ip (different jump hosts) have distinct node_id keys, so each session matches its own Node (no collapse). Enabled-gate invariant: a session is returned ONLY if s.machine.node_id is in nodes_by_id, so setup-in-flight tmp-nodes (enabled=FALSE) and disabled-but-not-disconnected nodes are excluded.
#   LINKS: M-DOMAIN-MODEL, M-SSH-REPOSITORY, M-PERSISTENCE-UOW
# END_CONTRACT: _find_free_machines
async def _find_free_machines(
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    repository: MachineRepository,
) -> list[tuple[MachineSession, Node]]:
    # START_BLOCK_FIND_FREE_MACHINES
    async with uow_factory() as uow:
        running_tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
        enabled_nodes = await uow.nodes.list_enabled()
    busy_node_ids = {t.allocated_node_id for t in running_tasks if t.allocated_node_id}
    nodes_by_id = {n.node_id: n for n in enabled_nodes}
    free_sessions = [
        (s, nodes_by_id[s.machine.node_id])
        for s in repository.list_free(platforms=list(engine.platforms))
        if s.machine.node_id in nodes_by_id and s.machine.node_id not in busy_node_ids
    ]
    return free_sessions
    # END_BLOCK_FIND_FREE_MACHINES


# START_CONTRACT: _allocate_free_machine
#   PURPOSE: Find a free compatible machine and start the task on it.
#   INPUTS: { task: Task, engine: Engine, uow_factory: Callable, repository: MachineRepository, operations: MachineOperations,
#     start_task_on_machine: Callable, tracker: AllocationTracker }
#   OUTPUTS: { bool - True if allocated to a machine, False if not }
#   SIDE_EFFECTS: Updates task status via allocate_to(node), starts occupancy check, records TaskAllocated event, discards tracker slot. Iterates (session, node) pairs from _find_free_machines. Per-pair failures are isolated: each _try_start_on_machine call is wrapped in try/except Exception, logged at error with task_id and ip, and the loop continues to the next pair. A transient SSH failure does NOT call repository.disconnect — the monitor task owns session lifecycle. No exception propagates out of the loop.
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
    for session, node in free_sessions:
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
                node,
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
#   PURPOSE: Under allocation_lock, compute provider capacity, call select_provider port, and insert tmp-node via insert(NewNode(cloud=..., enabled=False)) in a single UoW committed before lock release.
#   INPUTS: {
#     clouds: CloudProvisioner - Cloud port (select_provider called sync),
#     engine: Engine - Resolved engine config (source of platforms),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     allocation_lock: asyncio.Lock - Critical-section lock
#   }
#   OUTPUTS: { _TmpSelection | None - selected provider name + tmp-node Node (the row committed by insert), or None if no provider available }
#   SIDE_EFFECTS: Reads uow.nodes.list_all, inserts tmp-node via uow.nodes.insert(NewNode(cloud=..., enabled=False)), commits under lock. Concurrent selectors observe the tmp-node after lock release.
#   LINKS: M-CLOUD-PROVISIONER, M-APPLICATION-UOW, M-DOMAIN-MODEL
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
            tmp_node = await uow.nodes.insert(
                NewNode(cloud=selected_name, enabled=False)
            )
            await uow.commit()
            return _TmpSelection(name=selected_name, node=tmp_node)
    # END_BLOCK_CAPACITY_AND_SELECT


# START_CONTRACT: _cleanup_tmp_node_best_effort
#   PURPOSE: Best-effort tmp-node removal by NodeId; logs failures, never raises.
#   INPUTS: {
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     tmp_node_id: NodeId - The tmp-node's primary key (from insert's RETURNING node_id),
#     task_id: TaskId - For log correlation,
#     context: str - Why cleanup is running (e.g. "cloud-alloc-failed")
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens UoW, removes the tmp-node by node_id directly (uow.nodes.remove(tmp_node_id) — no get(ip) lookup), then commits. remove is idempotent (a 0-row DELETE is a no-op, matching prior no-op-on-0-rows behavior). Failures logged only — never re-raised.
#   LINKS: M-APPLICATION-UOW
# END_CONTRACT: _cleanup_tmp_node_best_effort
async def _cleanup_tmp_node_best_effort(
    uow_factory: Callable[[], AbstractUnitOfWork],
    tmp_node_id: NodeId,
    task_id: TaskId,
    context: str,
) -> None:
    # START_BLOCK_BEST_EFFORT_TMP_CLEANUP
    try:
        async with uow_factory() as uow:
            await uow.nodes.remove(tmp_node_id)
            await uow.commit()
    except Exception as cleanup_err:
        logger.error(
            "[AllocateTask][allocate_task][TMP_CLEANUP_FAILED] "
            "task_id=%s ctx=%s tmp_node_id=%s err=%s",
            task_id,
            context,
            tmp_node_id,
            cleanup_err,
        )
    # END_BLOCK_BEST_EFFORT_TMP_CLEANUP


# START_CONTRACT: _allocate_cloud_node
#   PURPOSE: Call clouds.allocate(provider, node); on failure run best-effort tmp-node cleanup then re-raise so the caller sees the original cloud-allocation error.
#   INPUTS: {
#     clouds: CloudProvisioner - Cloud port (allocate),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory (for cleanup),
#     selected_name: str - Provider name to allocate,
#     tmp_node: Node - tmp-node committed by _select_and_insert_tmp (its node_id is reused as the real node identity),
#     task_id: TaskId - For log correlation
#   }
#   OUTPUTS: { Node - The provisioned cloud node (node_id == tmp_node.node_id, enabled=True, real ip, ncpus); NOT yet flipped to enabled=TRUE in DB — the caller's update step does that }
#   SIDE_EFFECTS: Calls clouds.allocate(provider, tmp_node). On failure opens a UoW to remove+commit the tmp-node by node_id (best-effort, logged not raised).
#   RAISES: { Exception - Original cloud-allocation exception, never a cleanup exception }
#   LINKS: M-CLOUD-PROVISIONER, M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: _allocate_cloud_node
async def _allocate_cloud_node(
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    selected_name: str,
    tmp_node: Node,
    task_id: TaskId,
) -> Node:
    # START_BLOCK_CLOUD_ALLOCATE
    try:
        node = await clouds.allocate(selected_name, tmp_node)
    except Exception as err:
        logger.error(
            "[AllocateTask][allocate_task][CLOUD_FAILED] task_id=%s err=%s",
            task_id,
            err,
        )
        # Best-effort tmp-node cleanup; failure here is logged but does
        # not mask the original cloud-allocation exception.
        await _cleanup_tmp_node_best_effort(
            uow_factory, tmp_node.node_id, task_id, "cloud-alloc-failed"
        )
        raise
    # END_BLOCK_CLOUD_ALLOCATE
    return node


# START_CONTRACT: _persist_node_with_cleanup
#   PURPOSE: Persist the final node via a single uow.nodes.update(node) (flipping enabled=TRUE, setting ip/ncpus); on failure best-effort delete the billable orphan VM and remove the tmp-node, then re-raise the original persist error.
#   INPUTS: {
#     node: Node - Provisioned node (node_id == tmp_node.node_id, enabled=True, real ip, ncpus),
#     clouds: CloudProvisioner - Cloud port (deallocate on persist failure),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     tmp_node_id: NodeId - tmp-node primary key (== node.node_id; for cleanup),
#     task_id: TaskId - For log correlation
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens UoW, calls uow.nodes.update(node) (UPDATE the existing tmp row: enabled=TRUE, ip, ncpus), then commits. Single row per cloud allocation lifecycle (no insert+remove). On failure: best-effort clouds.deallocate(node) (the returned node carries cloud=adapter.name) + tmp-node cleanup (logged not raised), then re-raises.
#   RAISES: { Exception - Original persist exception, never a cleanup exception }
#   LINKS: M-CLOUD-PROVISIONER, M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: _persist_node_with_cleanup
async def _persist_node_with_cleanup(
    node: Node,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    tmp_node_id: NodeId,
    task_id: TaskId,
) -> None:
    # START_BLOCK_FINAL_PERSIST
    try:
        async with uow_factory() as uow:
            await uow.nodes.update(node)
            await uow.commit()
    except Exception as persist_err:
        logger.error(
            "[AllocateTask][allocate_task][PERSIST_FAILED] task_id=%s ip=%s err=%s",
            task_id,
            node.ip,
            persist_err,
        )
        # VM is up and billing but the DB row was not flipped; best-effort
        # delete so we don't leak a billable orphan. Failure here is logged
        # not raised. The returned node always carries cloud=adapter.name
        # (allocate is authoritative over the cloud field), so deallocate
        # resolves the provider from node.cloud directly.
        try:
            await clouds.deallocate(node)
        except Exception as dealloc_err:
            logger.error(
                "[AllocateTask][allocate_task][DEALLOC_FAILED] task_id=%s ip=%s err=%s",
                task_id,
                node.ip,
                dealloc_err,
            )
        await _cleanup_tmp_node_best_effort(
            uow_factory, tmp_node_id, task_id, "persist-failed"
        )
        raise
    # END_BLOCK_FINAL_PERSIST

    logger.debug(
        "[AllocateTask][allocate_task][CLOUD_DONE] task_id=%s ip=%s cloud=%s",
        task_id,
        node.ip,
        node.cloud,
    )


# START_CONTRACT: allocate_task
#   PURPOSE: Match a TO_DO task to a free compatible machine or request cloud allocation.
#   INPUTS: {
#     task_id: TaskId - The task id to allocate,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     repository: MachineRepository, operations: MachineOperations - SSH gateway with connected machines,
#     clouds: CloudProvisioner - Cloud provider port,
#     start_task_on_machine: Callable - Callback to upload+spawn on remote machine,
#     tracker: AllocationTracker - In-flight cloud allocation tracker,
#     allocation_lock: asyncio.Lock - Lock for critical section coordination
#   }
#   OUTPUTS: { bool - True if allocated to a machine, False if cloud requested or error }
#   SIDE_EFFECTS: May update task status in DB, start occupancy check, record events (TaskAllocated/TaskFailed), tracker.add/discard lifecycle, tmp-node insertion via uow.nodes.insert(NewNode(cloud=..., enabled=False)), cloud allocation via port. On cloud-fallback failure the VM and tmp-node (by node_id) are best-effort cleaned up.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: allocate_task
async def allocate_task(
    task_id: TaskId,
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
    # cloud-fallback (step1 commit/insert-tmp fail, step2 cloud-alloc fail,
    # step3 final persist fail) while preserving the entry on the success path
    # (VM provisioned, awaiting consume_task / next-cycle free-machine start).
    cloud_allocated = False
    tmp_node_id: NodeId | None = None
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
        tmp_node_id = selected.node.node_id
        tmp_owned_by_provisioner = True
        node = await _allocate_cloud_node(
            clouds, uow_factory, selected_name, selected.node, task_id
        )
        await _persist_node_with_cleanup(
            node, clouds, uow_factory, tmp_node_id, task_id
        )
        cloud_allocated = True
        return False
    finally:
        if not cloud_allocated:
            tracker.discard(task.task_id)
            if tmp_node_id is not None and not tmp_owned_by_provisioner:
                await _cleanup_tmp_node_best_effort(
                    uow_factory, tmp_node_id, task.task_id, "allocator-unexpected"
                )
    # END_BLOCK_ALLOCATE_CLOUD_CRITICAL_SECTION
