# FILE: yascheduler/application/allocate_task.py
# VERSION: 5.23.0
# START_MODULE_CONTRACT
#   PURPOSE: Allocate task use case — match a TO_DO task to a free machine or request cloud provisioning.
#   SCOPE: Task-to-machine allocation with cloud fallback — free machine search, cloud provisioning, tmp-node lifecycle, and persistence.
#   DEPENDS: M-APPLICATION-UOW, M-SSH-REPOSITORY, M-SSH-OPS-OCCUPANCY, M-CLOUD-PROVISIONER, M-DOMAIN-ENGINE, M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-UOW, M-CLOUD-PROVISIONER, M-SSH-REPOSITORY, M-SSH-OPS-OCCUPANCY, M-APPLICATION-ALLOCATION-TRACKER, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   allocate_task - Assign a TO_DO task to a free machine or request cloud node
#   _validate_engine - Validate task engine is configured and supported
#   _allocate_free_machine - Find free machine and start task on it
#   _find_free_machines - Find free compatible machines for task allocation
#   _try_start_on_machine - Attempt to start a task on a specific (session, node) pair
#   _count_nodes_by_cloud - Count nodes by cloud prefix (shared with orchestrator)
#   _TmpSelection - NamedTuple(name: str, node: Node) for tmp-node handle
#   _select_and_insert_tmp - Under lock, select provider and insert tmp-node
#   _cleanup_tmp_node_best_effort - Best-effort tmp-node removal by NodeId
#   _allocate_cloud_node - Call clouds.allocate; cleanup tmp-node on failure
#   _persist_node_with_cleanup - Persist final node; cleanup VM on failure
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v5.24.0 - Rewrite TMP_CLEANUP_FAILED/CLOUD_FAILED/PERSIST_FAILED/DEALLOC_FAILED/NO_PLATFORM to pure narrative (no grace markers) per reform-grace-logging slice 7.
#   PREVIOUS_CHANGE: v5.23.0 - session.ip→session.hostname; node.ip→node.hostname in log lines (Wave 2 — domain rename consumed).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from yascheduler.domain import (
    MachineSession,
    NewNode,
    Node,
    NodeId,
    Task,
    TaskId,
    TaskStatus,
)
from yascheduler.shared import get_logger

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import PurePath

    from yascheduler.domain import (
        CloudProvisioner,
        Engine,
        EngineRepository,
        MachineRepository,
    )
    from yascheduler.infra import OccupancyChecker

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = get_logger("M-APPLICATION-ALLOCATE")


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
#   SIDE_EFFECTS: On unsupported engine, transitions task via reject() , saves, and commits.
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
        task = task.reject("unsupported engine")
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
#     node: Node - The Node paired with the session,
#     engine: Engine - The resolved engine config,
#     task: Task - The task to allocate,
#     occupancy_checker: OccupancyChecker - SSH operations for occupancy checks,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]] - Upload+spawn callback,
#     tracker: AllocationTracker - In-flight cloud allocation tracker,
#     remote_tasks_dir - Remote base directory for task folders
#   }
#   OUTPUTS: { bool }
#   SIDE_EFFECTS: starts occupancy check, saves, commits
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-OPS-OCCUPANCY, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: _try_start_on_machine
async def _try_start_on_machine(
    session: MachineSession,
    node: Node,
    engine: Engine,
    task: Task,
    occupancy_checker: OccupancyChecker,
    uow_factory: Callable[[], AbstractUnitOfWork],
    start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]],
    tracker: AllocationTracker,
    remote_tasks_dir: PurePath,
) -> bool:
    dt_str = task.created_at.strftime("%Y%m%d_%H%M%S")
    remote_folder = str(remote_tasks_dir / f"{dt_str}_{task.task_id}")
    task = task.run(node.node_id, remote_folder)
    logger.trace(
        "TRY_ALLOCATE",
        task_id=task.task_id,
        hostname=session.hostname,
        node_id=node.node_id,
    )
    if not await start_task_on_machine(session, engine, task):
        return False
    logger.trace(
        "ALLOCATED",
        task_id=task.task_id,
        hostname=session.hostname,
        node_id=node.node_id,
    )
    occupancy_checker.start_occupancy_check(session, engine)
    async with uow_factory() as uow:
        await uow.tasks.save(task)
        await uow.commit()
    tracker.discard(task.task_id)
    return True


# START_CONTRACT: _find_free_machines
#   PURPOSE: Find free compatible machines eligible for task allocation, paired with their Node (matched by node_id).
#   INPUTS: {
#     engine: Engine - The resolved engine config,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     repository: MachineRepository - SSH repository with connected machines
#   }
#   OUTPUTS: { list[tuple[MachineSession, Node]] - Free sessions paired with their matching Node }
#   SIDE_EFFECTS: Reads running tasks and enabled nodes from DB.
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
#   INPUTS: { task: Task, engine: Engine, uow_factory: Callable, repository: MachineRepository, occupancy_checker: OccupancyChecker,
#     start_task_on_machine: Callable, tracker: AllocationTracker, remote_tasks_dir: PurePath }
#   OUTPUTS: { bool - True if allocated to a machine, False if not }
#   SIDE_EFFECTS: Transitions task via run(node.node_id, remote_folder) on the first successful pair, starts occupancy check, saves, commits, discards tracker slot. Iterates (session, node) pairs from _find_free_machines; per-pair failures isolated and logged.
#   LINKS: M-DOMAIN-MODEL, M-SSH-REPOSITORY, M-SSH-OPS-OCCUPANCY, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: _allocate_free_machine
async def _allocate_free_machine(
    task: Task,
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    repository: MachineRepository,
    occupancy_checker: OccupancyChecker,
    start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]],
    tracker: AllocationTracker,
    remote_tasks_dir: PurePath,
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
                occupancy_checker,
                uow_factory,
                start_task_on_machine,
                tracker,
                remote_tasks_dir,
            ):
                return True
        except Exception as err:
            logger.trace(
                "SESSION_FAILED",
                task_id=task.task_id,
                hostname=session.hostname,
                err=err,
            )
            continue
        # END_BLOCK_TRY_START_ISOLATED
    # END_BLOCK_ALLOCATE_MACHINE

    return False


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
#   SIDE_EFFECTS: Opens UoW, removes tmp-node by node_id, commits. Failures logged only — never re-raised.
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
            "tmp-node cleanup failed: task_id=%s ctx=%s tmp_node_id=%s err=%s",
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
#   SIDE_EFFECTS: Calls clouds.allocate(provider, tmp_node). On failure removes tmp-node by node_id (best-effort, logged not raised).
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
        logger.error("cloud allocation failed: task_id=%s err=%s", task_id, err)
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
#   SIDE_EFFECTS: Opens UoW, calls uow.nodes.update(node), commits. On failure: best-effort clouds.deallocate(node) + tmp-node cleanup, then re-raises.
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
            "persist node failed: task_id=%s hostname=%s err=%s",
            task_id,
            node.hostname,
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
                "deallocate node failed: task_id=%s hostname=%s err=%s",
                task_id,
                node.hostname,
                dealloc_err,
            )
        await _cleanup_tmp_node_best_effort(
            uow_factory, tmp_node_id, task_id, "persist-failed"
        )
        raise
    # END_BLOCK_FINAL_PERSIST

    logger.trace(
        "CLOUD_DONE", task_id=task_id, hostname=node.hostname, cloud=node.cloud
    )


# START_CONTRACT: allocate_task
#   PURPOSE: Match a TO_DO task to a free compatible machine or request cloud allocation.
#   INPUTS: {
#     task_id: TaskId - The task id to allocate,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     repository: MachineRepository, occupancy_checker: OccupancyChecker - SSH gateway with connected machines,
#     clouds: CloudProvisioner - Cloud provider port,
#     start_task_on_machine: Callable - Callback to upload+spawn on remote machine,
#     tracker: AllocationTracker - In-flight cloud allocation tracker,
#     allocation_lock: asyncio.Lock - Lock for critical section coordination,
#     remote_tasks_dir: PurePath - Remote base directory for task folders
#   }
#   OUTPUTS: { bool - True if allocated to a machine, False if cloud requested or error }
#   SIDE_EFFECTS: May update task status in DB, start occupancy check, record events (TaskAllocated/TaskFailed), tracker.add/set_node/discard, tmp-node insertion, cloud allocation. On failure best-effort cleanup of VM and tmp-node.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-REPOSITORY, M-SSH-OPS-OCCUPANCY, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: allocate_task
async def allocate_task(
    task_id: TaskId,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    repository: MachineRepository,
    occupancy_checker: OccupancyChecker,
    clouds: CloudProvisioner,
    start_task_on_machine: Callable[[MachineSession, Engine, Task], Awaitable[bool]],
    tracker: AllocationTracker,
    allocation_lock: asyncio.Lock,
    remote_tasks_dir: PurePath,
) -> bool:
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
    if task is None:
        return False

    logger.trace("ALLOCATE_TASK", task_id=task.task_id)

    engine = await _validate_engine(task, engines, uow_factory)
    if engine is None:
        return False

    if await _allocate_free_machine(
        task,
        engine,
        uow_factory,
        repository,
        occupancy_checker,
        start_task_on_machine,
        tracker,
        remote_tasks_dir,
    ):
        return True

    # Empty-platform engines are eligible for free machines (matched above) but
    # never for cloud provisioning — select_provider would silently return None
    # and the task would spin in TO_DO forever. Short-circuit with a warning
    # before entering the cloud critical section.
    if not engine.platforms:
        logger.warning(
            "engine %s has no platforms; cannot cloud-provision: task_id=%s",
            engine.name,
            task.task_id,
        )
        return False

    # START_BLOCK_ALLOCATE_CLOUD_CRITICAL_SECTION
    logger.trace("CLOUD", task_id=task.task_id)

    # Step 0: tracker dedup
    if not tracker.add(task.task_id):
        logger.trace("DEDUP", task_id=task.task_id)
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
            logger.trace("NO_PROVIDER", task_id=task.task_id)
            return False
        selected_name = selected.name
        tmp_node_id = selected.node.node_id
        tmp_owned_by_provisioner = True
        tracker.set_node(task.task_id, tmp_node_id)
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
