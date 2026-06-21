# FILE: yascheduler/application/deallocate_nodes.py
# VERSION: 3.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Deallocate idle nodes use case — disable idle cloud nodes and return IPs for VM deletion.
#   SCOPE: deallocate_nodes async function.
#   DEPENDS: M-APPLICATION-UOW, M-SSH-GATEWAY, M-CLOUD-PROVISIONER, M-CONFIG-CLOUD
#   LINKS: M-APPLICATION-UOW, M-CONFIG-CLOUD
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   deallocate_node - Disconnect and cloud-deallocate a single node
#   deallocate_nodes - Disable idle cloud nodes and return IPs for VM deletion
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v3.1.0 - Use MachineGateway Protocol and gateway.contains() instead of gateway.keys() (gateway-port-cleanup).
#   PREVIOUS_CHANGE: v3.0.0 - Replace RemoteMachineRepository with SSHMachineGateway.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from yascheduler.domain import Node, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.adapters import CloudProvisionerImpl
    from yascheduler.config import ConfigCloud
    from yascheduler.domain import MachineGateway

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: deallocate_node
#   PURPOSE: Disconnect and cloud-deallocate a single node.
#   INPUTS: {
#     node: Node - The node to deallocate,
#     gateway: MachineGateway - SSH gateway,
#     clouds: CloudProvisionerImpl - Cloud provider manager
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Disconnects remote machine, deletes cloud VM.
#   LINKS: M-SSH-GATEWAY, M-CLOUD-PROVISIONER
# END_CONTRACT: deallocate_node
async def deallocate_node(
    node: Node,
    gateway: MachineGateway,
    clouds: CloudProvisionerImpl,
) -> None:
    if gateway.contains(node.ip):
        await gateway.disconnect(node.ip)
    if node.cloud:
        await clouds.deallocate(node.ip)


# START_CONTRACT: deallocate_nodes
#   PURPOSE: Disable idle cloud nodes exceeding tolerance and return their IPs for VM deletion.
#   INPUTS: {
#     uow_factory: Callable[[], AbstractUnitOfWork] - Unit of Work factory,
#     config_clouds: Sequence[ConfigCloud] - Cloud configuration with idle_tolerance,
#     idle_machines: dict[str, float] - IP -> free_since monotonic timestamp
#   }
#   OUTPUTS: { list[str] - List of disabled node IPs for orchestrator to deallocate }
#   SIDE_EFFECTS: Disables nodes in DB.
#   LINKS: M-APPLICATION-UOW, M-CONFIG-CLOUD
# END_CONTRACT: deallocate_nodes
async def deallocate_nodes(
    uow_factory: Callable[[], AbstractUnitOfWork],
    config_clouds: Sequence[ConfigCloud],
    idle_machines: dict[str, datetime],
) -> list[str]:
    # START_BLOCK_DISABLE_IDLE
    async with uow_factory() as uow:
        running_tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
        busy_ips = {t.allocated_ip for t in running_tasks if t.allocated_ip}
        all_enabled_nodes = {
            n.ip: n for n in await uow.nodes.list_enabled() if n.ip not in busy_ips
        }

    now = datetime.now()
    for ccfg in config_clouds:
        tdlim = timedelta(seconds=ccfg.idle_tolerance)
        nodes_to_disable = [
            ip
            for ip, node in all_enabled_nodes.items()
            if node.cloud == ccfg.prefix
            and ip in idle_machines
            and (now - idle_machines[ip]) >= tdlim
        ]
        for ip in nodes_to_disable:
            async with uow_factory() as uow:
                await uow.nodes.disable(ip)
                await uow.commit()
    # END_BLOCK_DISABLE_IDLE

    # START_BLOCK_COLLECT_DISABLED
    async with uow_factory() as uow:
        free_disabled_nodes = [
            node
            for node in await uow.nodes.list_disabled()
            if node.ip not in busy_ips and "." in node.ip and node.cloud
        ]
    return [node.ip for node in free_disabled_nodes]
    # END_BLOCK_COLLECT_DISABLED
