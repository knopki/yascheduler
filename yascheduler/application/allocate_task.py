# FILE: yascheduler/application/allocate_task.py
# VERSION: 4.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Allocate task use case — match a TO_DO task to a free machine or request cloud provisioning.
#   SCOPE: allocate_task async function.
#   DEPENDS: M-APPLICATION-UOW, M-SSH-GATEWAY, M-CLOUD-PROVISIONER, M-CONFIG, M-DOMAIN-EVENTS
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-UOW, M-CLOUD-PROVISIONER, M-SSH-GATEWAY
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
#   LAST_CHANGE: v4.2.0 - Update callback type from Engine to TaskExecutionEngine (gateway-port-cleanup scope expansion).
#   PREVIOUS_CHANGE: v4.1.0 - Use MachineGateway Protocol instead of concrete SSHMachineGateway (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from yascheduler.domain import (
    ConnectedMachine,
    Task,
    TaskAllocated,
    TaskExecutionEngine,
    TaskFailed,
    TaskStatus,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from yascheduler.adapters import CloudProvisionerImpl
    from yascheduler.config import Engine, EngineRepository
    from yascheduler.domain import MachineGateway

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: _validate_engine
#   PURPOSE: Validate that the task's engine is configured and supported.
#   INPUTS: {
#     task: Task - The task to validate,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory
#   }
#   OUTPUTS: { Engine | None - The resolved engine, or None if invalid }
#   SIDE_EFFECTS: Sets task error and records TaskFailed event if engine is unsupported.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-CONFIG
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
        task = task.reject("unsupported engine")
        task = task.record_event(
            TaskFailed(
                task_id=task.task_id,
                webhook_url=task.context.webhook_url,
                webhook_custom_params=task.context.webhook_custom_params,
                reason="unsupported engine",
            )
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
#     machine: ConnectedMachine - The machine to try,
#     engine: Engine - The resolved engine config,
#     task: Task - The task to allocate,
#     gateway: MachineGateway - SSH gateway for occupancy checks,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     start_task_on_machine: Callable[[ConnectedMachine, TaskExecutionEngine, Task], Awaitable[bool]] - Upload+spawn callback,
#     clouds: CloudProvisionerImpl - Cloud provider manager
#   }
#   OUTPUTS: { bool - True if task started successfully on this machine }
#   SIDE_EFFECTS: Sets task running, starts occupancy check, records TaskAllocated event, marks cloud task done.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-GATEWAY, M-CLOUD-PROVISIONER
# END_CONTRACT: _try_start_on_machine
async def _try_start_on_machine(
    machine: ConnectedMachine,
    engine: Engine,
    task: Task,
    gateway: MachineGateway,
    uow_factory: Callable[[], AbstractUnitOfWork],
    start_task_on_machine: Callable[
        [ConnectedMachine, TaskExecutionEngine, Task], Awaitable[bool]
    ],
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
    task = task.record_event(
        TaskAllocated(
            task_id=task.task_id,
            webhook_url=task.context.webhook_url,
            webhook_custom_params=task.context.webhook_custom_params,
            node_ip=machine.ip,
            engine_name=task.context.engine,
        )
    )
    async with uow_factory() as uow:
        await uow.tasks.save(task)
        await uow.commit()
    clouds.mark_task_done(task.task_id)
    return True


# START_CONTRACT: _find_free_machines
#   PURPOSE: Find free compatible machines eligible for task allocation.
#   INPUTS: {
#     engine: Engine - The resolved engine config,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     gateway: MachineGateway - SSH gateway with connected machines
#   }
#   OUTPUTS: { list[ConnectedMachine] - Free machines matching platforms }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-SSH-GATEWAY
# END_CONTRACT: _find_free_machines
async def _find_free_machines(
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    gateway: MachineGateway,
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
#   INPUTS: { task: Task, engine: Engine, uow_factory: Callable, gateway: MachineGateway,
#     start_task_on_machine: Callable, clouds: CloudProvisionerImpl }
#   OUTPUTS: { bool - True if allocated to a machine, False if not }
#   SIDE_EFFECTS: Updates task status, starts occupancy check, records TaskAllocated event, marks cloud task done.
#   LINKS: M-DOMAIN-MODEL, M-SSH-GATEWAY, M-CLOUD-PROVISIONER
# END_CONTRACT: _allocate_free_machine
async def _allocate_free_machine(
    task: Task,
    engine: Engine,
    uow_factory: Callable[[], AbstractUnitOfWork],
    gateway: MachineGateway,
    start_task_on_machine: Callable[
        [ConnectedMachine, TaskExecutionEngine, Task], Awaitable[bool]
    ],
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
#     gateway: MachineGateway - SSH gateway with connected machines,
#     clouds: CloudProvisionerImpl - Cloud provider manager,
#     start_task_on_machine: Callable - Callback to upload+spawn on remote machine
#   }
#   OUTPUTS: { bool - True if allocated to a machine, False if cloud requested or error }
#   SIDE_EFFECTS: May update task status in DB, start occupancy check, record events (TaskAllocated/TaskFailed), request cloud node.
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-SSH-GATEWAY, M-CLOUD-PROVISIONER
# END_CONTRACT: allocate_task
async def allocate_task(
    task_id: int,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    gateway: MachineGateway,
    clouds: CloudProvisionerImpl,
    start_task_on_machine: Callable[
        [ConnectedMachine, TaskExecutionEngine, Task], Awaitable[bool]
    ],
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
        gateway,
        start_task_on_machine,
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
