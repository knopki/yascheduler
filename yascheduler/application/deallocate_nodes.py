# FILE: yascheduler/application/deallocate_nodes.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Deallocate idle nodes use case — disable idle cloud nodes and trigger VM deletion.
#   SCOPE: deallocate_nodes async function.
#   DEPENDS: M-DB, M-REMOTE-REPO, M-CLOUD-MANAGER, M-CONFIG-CLOUD
#   LINKS: M-DB, M-SCHEDULER, M-CLOUD-MANAGER, M-REMOTE-REPO
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   deallocate_node - Disconnect and cloud-deallocate a single node
#   deallocate_nodes - Disable idle cloud nodes and delete their VMs
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Extract deallocate_node for per-node consumer; refactor deallocate_nodes to use it.
#   PREVIOUS_CHANGE: v1.0.0 - Extract deallocate_nodes use case from scheduler deallocator loops.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from yascheduler.db import DB, NodeModel, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from yascheduler.adapters.cloud.manager import CloudProvisionerImpl
    from yascheduler.config import ConfigCloud
    from yascheduler.remote_machine import RemoteMachineRepository

logger = logging.getLogger(__name__)


# START_CONTRACT: deallocate_node
#   PURPOSE: Disconnect and cloud-deallocate a single node.
#   INPUTS: {
#     node: NodeModel - The node to deallocate,
#     remote_machines: RemoteMachineRepository - Connected SSH machines,
#     clouds: CloudProvisionerImpl - Cloud provider manager
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Disconnects remote machine, deletes cloud VM.
#   LINKS: M-REMOTE-REPO, M-CLOUD-MANAGER
# END_CONTRACT: deallocate_node
async def deallocate_node(
    node: NodeModel,
    remote_machines: RemoteMachineRepository,
    clouds: CloudProvisionerImpl,
) -> None:
    if node.ip in remote_machines.keys():
        await remote_machines.disconnect_many([node.ip])
    if node.cloud:
        await clouds.deallocate(node.ip)


# START_CONTRACT: deallocate_nodes
#   PURPOSE: Disable idle cloud nodes exceeding tolerance and delete their VMs.
#   INPUTS: {
#     db: DB - Legacy database facade,
#     remote_machines: RemoteMachineRepository - Connected SSH machines,
#     clouds: CloudProvisionerImpl - Cloud provider manager,
#     config_clouds: Sequence[ConfigCloud] - Cloud configuration with idle_tolerance
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Disables nodes in DB, disconnects remote machines, deletes cloud VMs.
#   LINKS: M-DB, M-REMOTE-REPO, M-CLOUD-MANAGER
# END_CONTRACT: deallocate_nodes
async def deallocate_nodes(
    db: DB,
    remote_machines: RemoteMachineRepository,
    clouds: CloudProvisionerImpl,
    config_clouds: Sequence[ConfigCloud],
) -> None:
    # START_BLOCK_DISABLE_IDLE
    tasks = await db.get_tasks_by_status((TaskStatus.RUNNING,))
    busy_ips = [t.ip for t in tasks]
    all_enabled_nodes = {
        n.ip: n for n in await db.get_enabled_nodes() if n.ip not in busy_ips
    }
    for ccfg in config_clouds:
        tdlim = timedelta(seconds=ccfg.idle_tolerance)
        idlers = remote_machines.filter(
            busy=False, reverse_sort=False, free_since_gt=tdlim
        )
        nodes_to_disable = [
            ip
            for ip, node in all_enabled_nodes.items()
            if node.cloud == ccfg.prefix and ip in idlers.keys()
        ]
        for ip in nodes_to_disable:
            await db.disable_node(ip)
            await db.commit()
    # END_BLOCK_DISABLE_IDLE

    # START_BLOCK_DEALLOCATE_CLOUD
    free_disabled_nodes = [
        node
        for node in await db.get_disabled_nodes()
        if node.ip not in busy_ips and "." in node.ip
    ]
    for node in free_disabled_nodes:
        await deallocate_node(node, remote_machines, clouds)
    # END_BLOCK_DEALLOCATE_CLOUD
