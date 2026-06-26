# FILE: yascheduler/application/deallocate_nodes.py
# VERSION: 4.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Deallocate idle nodes use case — disable idle cloud nodes and return IPs for VM deletion.
#   SCOPE: deallocate_node, deallocate_nodes async functions.
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-SSH-GATEWAY, M-CLOUD-PROVISIONER
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   deallocate_node - Disconnect and cloud-deallocate a single node; logs+flags stale row if DB remove fails after successful cloud delete
#   deallocate_nodes - Disable idle cloud nodes and return IPs for VM deletion
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v4.3.0 - TYPE_CHECKING import CloudConfig from yascheduler.domain instead of ConfigCloud from yascheduler.config (cloud-configs-to-infra-registry); config_clouds parameter typed as Sequence[CloudConfig] (domain Protocol) — application stays free of infra DTO imports via TYPE_CHECKING.
#   PREVIOUS_CHANGE: v4.2.0 - Switch idle_machines to monotonic float timestamps (matching free_since on ConnectedMachine) and compare against time.monotonic(); eliminates wall-clock/monotonic mixing that skewed idle detection under DST/NTP clock jumps.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from yascheduler.domain import Node, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import CloudConfig, CloudProvisioner, MachineGateway

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: deallocate_node
#   PURPOSE: Disconnect and cloud-deallocate a single node.
#   INPUTS: {
#     node: Node - The node to deallocate,
#     gateway: MachineGateway - SSH gateway,
#     clouds: CloudProvisioner - Cloud provider manager,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Disconnects remote machine, disables node via UoW, deletes cloud VM via port, removes node via second UoW. If the second UoW fails after cloud delete succeeded, logs loudly for manual reconciliation (row stays disabled) and does not re-raise — the cloud VM is already gone.
#   LINKS: M-SSH-GATEWAY, M-CLOUD-PROVISIONER, M-APPLICATION-UOW
# END_CONTRACT: deallocate_node
async def deallocate_node(
    node: Node,
    gateway: MachineGateway,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> None:
    if gateway.contains(node.ip):
        await gateway.disconnect(node.ip)
        logger.info(
            "[deallocate_node][DISCONNECT] ip=%s gateway disconnected",
            node.ip,
        )
    if node.cloud:
        # START_BLOCK_DISABLE
        logger.info(
            "[deallocate_node][DISABLE] ip=%s cloud=%s",
            node.ip,
            node.cloud,
        )
        async with uow_factory() as uow:
            await uow.nodes.disable(node.ip)
            await uow.commit()
        # END_BLOCK_DISABLE

        # START_BLOCK_CLOUD_DELETE
        logger.info(
            "[deallocate_node][CLOUD_DELETE] ip=%s cloud=%s",
            node.ip,
            node.cloud,
        )
        await clouds.deallocate(node.cloud, node.ip)
        # END_BLOCK_CLOUD_DELETE

        # START_BLOCK_REMOVE
        logger.info(
            "[deallocate_node][REMOVE] ip=%s cloud=%s",
            node.ip,
            node.cloud,
        )
        try:
            async with uow_factory() as uow:
                await uow.nodes.remove(node.ip)
                await uow.commit()
        except Exception as remove_err:
            # Cloud VM is already gone; the disabled DB row is stale. Log
            # loudly so operators can reconcile manually. Not re-raised: the
            # cloud delete succeeded, and the next cycle's deallocate_node
            # will re-attempt (cloud-SDK delete-idempotency dependent) plus
            # this remove.
            logger.error(
                "[deallocate_node][REMOVE_FAILED] ip=%s cloud=%s err=%s "
                "— VM is deleted but DB row left disabled; "
                "manual reconciliation needed",
                node.ip,
                node.cloud,
                remove_err,
            )
        # END_BLOCK_REMOVE


# START_CONTRACT: deallocate_nodes
#   PURPOSE: Disable idle cloud nodes exceeding tolerance and return their IPs for VM deletion.
#   INPUTS: {
#     uow_factory: Callable[[], AbstractUnitOfWork] - Unit of Work factory,
#     config_clouds: Sequence[CloudConfig] - Cloud configuration with idle_tolerance,
#     idle_machines: dict[str, float] - IP -> free_since monotonic timestamp (seconds since arbitrary epoch)
#   }
#   OUTPUTS: { list[str] - List of disabled node IPs for orchestrator to deallocate }
#   SIDE_EFFECTS: Disables nodes in DB.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS
# END_CONTRACT: deallocate_nodes
async def deallocate_nodes(
    uow_factory: Callable[[], AbstractUnitOfWork],
    config_clouds: Sequence[CloudConfig],
    idle_machines: dict[str, float],
) -> list[str]:
    # START_BLOCK_DISABLE_IDLE
    async with uow_factory() as uow:
        running_tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
        busy_ips = {t.allocated_ip for t in running_tasks if t.allocated_ip}
        all_enabled_nodes = {
            n.ip: n for n in await uow.nodes.list_enabled() if n.ip not in busy_ips
        }

    now = time.monotonic()
    for ccfg in config_clouds:
        nodes_to_disable = [
            ip
            for ip, node in all_enabled_nodes.items()
            if node.cloud == ccfg.prefix
            and ip in idle_machines
            and (now - idle_machines[ip]) >= ccfg.idle_tolerance
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
