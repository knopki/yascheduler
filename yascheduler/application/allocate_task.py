# FILE: yascheduler/application/allocate_task.py
# VERSION: 3.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Allocate task use case — match a TO_DO task to a free machine or request cloud provisioning.
#   SCOPE: allocate_task async function.
#   DEPENDS: M-APPLICATION-UOW, M-SSH-GATEWAY, M-CLOUD-PROVISIONER, M-CONFIG
#   LINKS: M-DOMAIN-MODEL, M-APPLICATION-UOW, M-SCHEDULER, M-CLOUD-PROVISIONER, M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   allocate_task - Assign a TO_DO task to a free machine or request cloud node (UoW-based)
#   _validate_engine - Validate task engine is configured and supported
#   _allocate_free_machine - Find free machine and start task on it
#   _find_free_machines - Find free compatible machines for task allocation
#   _try_start_on_machine - Attempt to start a task on a specific machine
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v3.0.0 - Replace RemoteMachineRepository/RemoteMachine with SSHMachineGateway/ConnectedMachine.
#   PREVIOUS_CHANGE: v2.0.0 - Rewrite to use UoW + domain Task instead of DB + TaskModel.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from yascheduler.domain.model import ConnectedMachine, Task, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from yascheduler.adapters.cloud.manager import CloudProvisionerImpl
    from yascheduler.adapters.ssh.gateway import SSHMachineGateway
    from yascheduler.application.uow import AbstractUnitOfWork
    from yascheduler.config import Engine, EngineRepository

logger = logging.getLogger(__name__)


# START_CONTRACT: _validate_engine
#   PURPOSE: Validate that the task's engine is configured and supported.
#   INPUTS: {
#     task: Task - The task to validate,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]] - Webhook callback
#   }
#   OUTPUTS: { Engine | None - The resolved engine, or None if invalid }
#   SIDE_EFFECTS: Sets task error and sends webhook if engine is unsupported.
#   LINKS: M-DOMAIN-MODEL, M-CONFIG
# END_CONTRACT: _validate_engine
async def _validate_engine(
    task: Task,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
) -> Engine | None:
    # START_BLOCK_VALIDATE_ENGINE
    engine_name: str | None = task.context.engine
    engine = engines.get(engine_name) if engine_name else None
    if engine is None:
        logger.warning(
            "Unsupported engine '%s' for task_id=%s", engine_name, task.task_id
        )
        task = task.reject("unsupported engine")
        async with uow_factory() as uow:
            await uow.tasks.save(task)
            await uow.commit()
        await do_task_webhook(task.task_id, task.context.to_metadata(), TaskStatus.DONE)
        return None
    # END_BLOCK_VALIDATE_ENGINE
    return engine


# START_CONTRACT: _try_start_on_machine
#   PURPOSE: Attempt to start a task on a specific free machine.
#   INPUTS: {
#     machine: ConnectedMachine - The machine to try,
#     engine: Engine - The resolved engine config,
#     task: Task - The task to allocate,
#     gateway: SSHMachineGateway - SSH gateway for occupancy checks,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     start_task_on_machine: Callable[[ConnectedMachine, Engine, Task], Awaitable[bool]] - Upload+spawn callback,
#     do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]] - Webhook callback,
#     clouds: CloudProvisionerImpl - Cloud provider manager
#   }
#   OUTPUTS: { bool - True if task started successfully on this machine }
#   SIDE_EFFECTS: Sets task running, starts occupancy check, sends webhook, marks cloud task done.
#   LINKS: M-DOMAIN-MODEL, M-SSH-GATEWAY, M-CLOUD-PROVISIONER
# END_CONTRACT: _try_start_on_machine
async def _try_start_on_machine(
    machine: ConnectedMachine,
    engine: Engine,
    task: Task,
    gateway: SSHMachineGateway,
    uow_factory: Callable[[], AbstractUnitOfWork],
    start_task_on_machine: Callable[[ConnectedMachine, Engine, Task], Awaitable[bool]],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
    clouds: CloudProvisionerImpl,
) -> bool:
    task = task.allocate_to(machine.ip).mark_running()
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine] task_id=%s ip=%s",
        task.task_id,
        machine.ip,
    )
    if not await start_task_on_machine(machine, engine, task):
        return False
    logger.debug(
        "[AllocateTask][_try_allocate_to_machine][ALLOCATED] task_id=%s ip=%s",
        task.task_id,
        machine.ip,
    )
    gateway.start_occupancy_check(machine.ip, engine)
    async with uow_factory() as uow:
        await uow.tasks.save(task)
        await uow.commit()
    await do_task_webhook(task.task_id, task.context.to_metadata(), TaskStatus.RUNNING)
    clouds.mark_task_done(task.task_id)
    return True


# START_CONTRACT: _find_free_machines
#   PURPOSE: Find free compatible machines eligible for task allocation.
#   INPUTS: {
#     engine: Engine - The resolved engine config,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     gateway: SSHMachineGateway - SSH gateway with connected machines
#   }
#   OUTPUTS: { list[ConnectedMachine] - Free machines matching platforms }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-SSH-GATEWAY
# END_CONTRACT: _find_free_machines
async def _find_free_machines(
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    gateway: SSHMachineGateway,
) -> list[ConnectedMachine]:
    # START_BLOCK_FIND_FREE_MACHINES
    async with uow_factory() as uow:
        running_tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
    busy_node_ips = {t.allocated_ip for t in running_tasks if t.allocated_ip}
    free_machines = [
        m
        for m in gateway.list_free(platforms=list(engine.platforms))
        if m.ip not in busy_node_ips
    ]
    return free_machines
    # END_BLOCK_FIND_FREE_MACHINES


# START_CONTRACT: _allocate_free_machine
#   PURPOSE: Find a free compatible machine and start the task on it.
#   INPUTS: { task: Task, engine: Engine, uow_factory: Callable, gateway: SSHMachineGateway,
#     start_task_on_machine: Callable, do_task_webhook: Callable, clouds: CloudProvisionerImpl }
#   OUTPUTS: { bool - True if allocated to a machine, False if not }
#   SIDE_EFFECTS: Updates task status, starts occupancy check, sends webhook, marks cloud task done.
#   LINKS: M-DOMAIN-MODEL, M-SSH-GATEWAY, M-CLOUD-PROVISIONER
# END_CONTRACT: _allocate_free_machine
async def _allocate_free_machine(
    task: Task,
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    gateway: SSHMachineGateway,
    start_task_on_machine: Callable[[ConnectedMachine, Engine, Task], Awaitable[bool]],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
    clouds: CloudProvisionerImpl,
) -> bool:
    free_machines = await _find_free_machines(engine, uow_factory, gateway)

    # START_BLOCK_ALLOCATE_MACHINE
    for machine in free_machines:
        if await _try_start_on_machine(
            machine,
            engine,
            task,
            gateway,
            uow_factory,
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
#     task_id: int - The task id to allocate,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     gateway: SSHMachineGateway - SSH gateway with connected machines,
#     clouds: CloudProvisionerImpl - Cloud provider manager,
#     start_task_on_machine: Callable - Callback to upload+spawn on remote machine,
#     do_task_webhook: Callable - Callback to send webhook notification
#   }
#   OUTPUTS: { bool - True if allocated to a machine, False if cloud requested or error }
#   SIDE_EFFECTS: May update task status in DB, start occupancy check, send webhook, request cloud node.
#   LINKS: M-DOMAIN-MODEL, M-SSH-GATEWAY, M-CLOUD-PROVISIONER
# END_CONTRACT: allocate_task
async def allocate_task(
    task_id: int,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    gateway: SSHMachineGateway,
    clouds: CloudProvisionerImpl,
    start_task_on_machine: Callable[[ConnectedMachine, Engine, Task], Awaitable[bool]],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
) -> bool:
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
    if task is None:
        return False

    logger.debug("[AllocateTask][allocate_task] task_id=%s", task.task_id)

    engine = await _validate_engine(task, engines, uow_factory, do_task_webhook)
    if engine is None:
        return False

    if await _allocate_free_machine(
        task,
        engine,
        uow_factory,
        gateway,
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
