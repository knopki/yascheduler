# FILE: yascheduler/application/allocate_task.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Allocate task use case — match a TO_DO task to a free machine or request cloud provisioning.
#   SCOPE: allocate_task async function.
#   DEPENDS: M-DB, M-REMOTE-REPO, M-CLOUD-MANAGER, M-CONFIG
#   LINKS: M-DB, M-SCHEDULER, M-CLOUD-MANAGER, M-REMOTE-REPO
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   allocate_task - Assign a TO_DO task to a free machine or request cloud node
#   _validate_engine - Validate task engine is configured and supported
#   _allocate_free_machine - Find free machine and start task on it
#   _find_free_machines - Find free compatible machines for task allocation
#   _try_start_on_machine - Attempt to start a task on a specific machine
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Extract _find_free_machines from _allocate_free_machine to comply with 60-line function limit.
#   PREVIOUS_CHANGE: v1.2.0 - Extract _try_start_on_machine from _allocate_free_machine to reduce func size.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from attrs import evolve

from yascheduler.db import DB, TaskModel, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from yascheduler.adapters.cloud.manager import CloudProvisionerImpl
    from yascheduler.config import Engine, EngineRepository
    from yascheduler.remote_machine import RemoteMachine, RemoteMachineRepository

logger = logging.getLogger(__name__)


# START_CONTRACT: _validate_engine
#   PURPOSE: Validate that the task's engine is configured and supported.
#   INPUTS: {
#     task: TaskModel - The task to validate,
#     engines: EngineRepository - Config engine repository,
#     db: DB - Legacy database facade,
#     do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]] - Webhook callback
#   }
#   OUTPUTS: { Engine | None - The resolved engine, or None if invalid }
#   SIDE_EFFECTS: Sets task error and sends webhook if engine is unsupported.
#   LINKS: M-DB, M-CONFIG
# END_CONTRACT: _validate_engine
async def _validate_engine(
    task: TaskModel,
    engines: EngineRepository,
    db: DB,
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
) -> Engine | None:
    # START_BLOCK_VALIDATE_ENGINE
    engine_name: str | None = task.metadata.get("engine", None)
    engine = engines.get(engine_name) if engine_name else None
    if engine is None:
        logger.warning(
            "Unsupported engine '%s' for task_id=%s", engine_name, task.task_id
        )
        await db.set_task_error(
            task.task_id, metadata=task.metadata, error="unsupported engine"
        )
        await do_task_webhook(task.task_id, task.metadata, TaskStatus.DONE)
        return None
    # END_BLOCK_VALIDATE_ENGINE
    return engine


# START_CONTRACT: _try_start_on_machine
#   PURPOSE: Attempt to start a task on a specific free machine.
#   INPUTS: {
#     machine: RemoteMachine - The machine to try,
#     engine: Engine - The resolved engine config,
#     task: TaskModel - The task to allocate,
#     ip: str - The machine IP,
#     db: DB - Legacy database facade,
#     start_task_on_machine: Callable[[RemoteMachine, Engine, TaskModel], Awaitable[bool]] - Upload+spawn callback,
#     do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]] - Webhook callback,
#     clouds: CloudProvisionerImpl - Cloud provider manager
#   }
#   OUTPUTS: { bool - True if task started successfully on this machine }
#   SIDE_EFFECTS: Sets task running, starts occupancy check, sends webhook, marks cloud task done.
#   LINKS: M-DB, M-REMOTE-REPO, M-CLOUD-MANAGER
# END_CONTRACT: _try_start_on_machine
async def _try_start_on_machine(
    machine: RemoteMachine,
    engine: Engine,
    task: TaskModel,
    ip: str,
    db: DB,
    start_task_on_machine: Callable[
        [RemoteMachine, Engine, TaskModel], Awaitable[bool]
    ],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
    clouds: CloudProvisionerImpl,
) -> bool:
    task_m = evolve(task, ip=ip)
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine] task_id=%s ip=%s", task.task_id, ip
    )
    if not await start_task_on_machine(machine, engine, task_m):
        return False
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine][ALLOCATED] task_id=%s ip=%s",
        task.task_id,
        ip,
    )
    await machine.start_occupancy_check(engine)
    await db.set_task_running(task.task_id, task_m.ip)
    await db.commit()
    await do_task_webhook(task.task_id, task_m.metadata, TaskStatus.RUNNING)
    clouds.mark_task_done(task.task_id)
    return True


# START_CONTRACT: _find_free_machines
#   PURPOSE: Find free compatible machines eligible for task allocation.
#   INPUTS: {
#     engine: Engine - The resolved engine config,
#     db: DB - Legacy database facade,
#     remote_machines: RemoteMachineRepository - Connected SSH machines
#   }
#   OUTPUTS: { dict[str, RemoteMachine] - Map of IP to free machine }
#   SIDE_EFFECTS: None
#   LINKS: M-DB, M-REMOTE-REPO
# END_CONTRACT: _find_free_machines
async def _find_free_machines(
    engine: Engine,
    db: DB,
    remote_machines: RemoteMachineRepository,
) -> dict[str, RemoteMachine]:
    # START_BLOCK_FIND_FREE_MACHINES
    busy_node_ips = [t.ip for t in await db.get_tasks_by_status((TaskStatus.RUNNING,))]
    free_machines = {
        ip: m
        for ip, m in remote_machines.filter(
            busy=False, platforms=engine.platforms, reverse_sort=True
        ).items()
        if ip not in busy_node_ips
    }
    return free_machines
    # END_BLOCK_FIND_FREE_MACHINES


# START_CONTRACT: _allocate_free_machine
#   PURPOSE: Find a free compatible machine and start the task on it.
#   INPUTS: { task: TaskModel, engine: Engine, db: DB, remote_machines: RemoteMachineRepository,
#     start_task_on_machine: Callable, do_task_webhook: Callable, clouds: CloudProvisionerImpl }
#   OUTPUTS: { bool - True if allocated to a machine, False if not }
#   SIDE_EFFECTS: Updates task status, starts occupancy check, sends webhook, marks cloud task done.
#   LINKS: M-DB, M-REMOTE-REPO, M-CLOUD-MANAGER
# END_CONTRACT: _allocate_free_machine
async def _allocate_free_machine(
    task: TaskModel,
    engine: Engine,
    db: DB,
    remote_machines: RemoteMachineRepository,
    start_task_on_machine: Callable[
        [RemoteMachine, Engine, TaskModel], Awaitable[bool]
    ],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
    clouds: CloudProvisionerImpl,
) -> bool:
    free_machines = await _find_free_machines(engine, db, remote_machines)

    # START_BLOCK_ALLOCATE_MACHINE
    for ip, machine in free_machines.items():
        if await _try_start_on_machine(
            machine,
            engine,
            task,
            ip,
            db,
            start_task_on_machine,
            do_task_webhook,
            clouds,
        ):
            return True
    # END_BLOCK_ALLOCATE_MACHINE

    return False


# START_CONTRACT: allocate_task
#   PURPOSE: Match a TO_DO task to a free compatible machine or request cloud allocation.
#   INPUTS: {
#     task: TaskModel - The task to allocate,
#     engines: EngineRepository - Config engine repository,
#     db: DB - Legacy database facade,
#     remote_machines: RemoteMachineRepository - Connected SSH machines,
#     clouds: CloudProvisionerImpl - Cloud provider manager,
#     start_task_on_machine: Callable - Callback to upload+spawn on remote machine,
#     do_task_webhook: Callable - Callback to send webhook notification
#   }
#   OUTPUTS: { bool - True if allocated to a machine, False if cloud requested or error }
#   SIDE_EFFECTS: May update task status in DB, start occupancy check, send webhook, request cloud node.
#   LINKS: M-DB, M-REMOTE-REPO, M-CLOUD-MANAGER
# END_CONTRACT: allocate_task
async def allocate_task(
    task: TaskModel,
    engines: EngineRepository,
    db: DB,
    remote_machines: RemoteMachineRepository,
    clouds: CloudProvisionerImpl,
    start_task_on_machine: Callable[
        [RemoteMachine, Engine, TaskModel], Awaitable[bool]
    ],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
) -> bool:
    logger.debug("[AllocateTask][allocate_task] task_id=%s", task.task_id)

    engine = await _validate_engine(task, engines, db, do_task_webhook)
    if engine is None:
        return False

    if await _allocate_free_machine(
        task,
        engine,
        db,
        remote_machines,
        start_task_on_machine,
        do_task_webhook,
        clouds,
    ):
        return True

    # START_BLOCK_ALLOCATE_CLOUD
    logger.debug("[AllocateTask][allocate_task][CLOUD] task_id=%s", task.task_id)
    await clouds.allocate_with_tracking(
        on_task=task.task_id, platforms=list(engine.platforms), throttle=True
    )
    return False
    # END_BLOCK_ALLOCATE_CLOUD
