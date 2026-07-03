# FILE: yascheduler/application/deallocate_nodes.py
# VERSION: 4.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Deallocate idle nodes use case — disable idle cloud nodes and return Node objects for VM deletion.
#   SCOPE: deallocate_node, deallocate_nodes async functions.
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-SSH-REPOSITORY, M-CLOUD-PROVISIONER
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   deallocate_node - Disconnect and cloud-deallocate a single node; logs+flags stale row if DB remove fails after successful cloud delete
#   deallocate_nodes - Disable idle cloud nodes and return Node objects for VM deletion
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v4.6.0 - deallocate-node-id-identity: deallocate_nodes returns list[Node] (was list[str] of IPs) — phase 2 returns the Node objects it reads from list_disabled() directly, eliminating the orchestrator consumer's uow.nodes.get(ip) round-trip. Removed the dead "." in node.ip post-filter (tmp-node rows now carry ip="" and are excluded at SQL level by list_disabled.sql WHERE ip <> ''). The orchestrator's _deallocate_q is rekeyed to UniqueQueue[NodeId, Node] in the same change.
#   PREVIOUS_CHANGE: v4.5.0 - Mutators rekeyed from ip to node_id (node-id-keyed-mutators): deallocate_node calls uow.nodes.disable(node.node_id) and uow.nodes.remove(node.node_id); deallocate_nodes disable loop iterates all_enabled_nodes.values() and calls uow.nodes.disable(node.node_id) (was ip-keyed). Internal log lines add node_id=%s alongside ip=%s. clouds.deallocate(node.cloud, node.ip) stays ip-keyed (ip = cloud host, out of scope).
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from yascheduler.domain import Node, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import CloudConfig, CloudProvisioner, MachineRepository

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: deallocate_node
#   PURPOSE: Disconnect and cloud-deallocate a single node.
#   INPUTS: {
#     node: Node - The node to deallocate,
#     repository: MachineRepository, operations: MachineOperations - SSH gateway,
#     clouds: CloudProvisioner - Cloud provider manager,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Disconnects remote machine, disables node (by node_id) via UoW, deletes cloud VM via port, removes node (by node_id) via second UoW. If the second UoW fails after cloud delete succeeded, logs loudly for manual reconciliation (row stays disabled) and does not re-raise — the cloud VM is already gone.
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-CLOUD-PROVISIONER, M-APPLICATION-UOW
# END_CONTRACT: deallocate_node
async def deallocate_node(
    node: Node,
    repository: MachineRepository,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> None:
    if repository.contains(node.ip):
        await repository.disconnect(node.ip)
        logger.debug(
            "[deallocate_node][DISCONNECT] node_id=%s ip=%s gateway disconnected",
            node.node_id,
            node.ip,
        )
    if node.cloud:
        # START_BLOCK_DISABLE
        logger.debug(
            "[deallocate_node][DISABLE] node_id=%s ip=%s cloud=%s",
            node.node_id,
            node.ip,
            node.cloud,
        )
        async with uow_factory() as uow:
            await uow.nodes.disable(node.node_id)
            await uow.commit()
        # END_BLOCK_DISABLE

        # START_BLOCK_CLOUD_DELETE
        logger.debug(
            "[deallocate_node][CLOUD_DELETE] node_id=%s ip=%s cloud=%s",
            node.node_id,
            node.ip,
            node.cloud,
        )
        await clouds.deallocate(node.cloud, node.ip)
        # END_BLOCK_CLOUD_DELETE

        # START_BLOCK_REMOVE
        logger.debug(
            "[deallocate_node][REMOVE] node_id=%s ip=%s cloud=%s",
            node.node_id,
            node.ip,
            node.cloud,
        )
        try:
            async with uow_factory() as uow:
                await uow.nodes.remove(node.node_id)
                await uow.commit()
        except Exception as remove_err:
            # Cloud VM is already gone; the disabled DB row is stale. Log
            # loudly so operators can reconcile manually. Not re-raised: the
            # cloud delete succeeded, and the next cycle's deallocate_node
            # will re-attempt (cloud-SDK delete-idempotency dependent) plus
            # this remove.
            logger.error(
                "[deallocate_node][REMOVE_FAILED] node_id=%s ip=%s cloud=%s err=%s "
                "— VM is deleted but DB row left disabled; "
                "manual reconciliation needed",
                node.node_id,
                node.ip,
                node.cloud,
                remove_err,
            )
        # END_BLOCK_REMOVE


# START_CONTRACT: deallocate_nodes
#   PURPOSE: Disable idle cloud nodes exceeding tolerance and return their Node objects for VM deletion.
#   INPUTS: {
#     uow_factory: Callable[[], AbstractUnitOfWork] - Unit of Work factory,
#     config_clouds: Sequence[CloudConfig] - Cloud configuration with idle_tolerance,
#     idle_machines: dict[str, float] - IP -> free_since monotonic timestamp (seconds since arbitrary epoch)
#   }
#   OUTPUTS: { list[Node] - Disabled node objects (each carrying node_id) for orchestrator to deallocate }
#   SIDE_EFFECTS: Disables nodes in DB.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS
# END_CONTRACT: deallocate_nodes
async def deallocate_nodes(
    uow_factory: Callable[[], AbstractUnitOfWork],
    config_clouds: Sequence[CloudConfig],
    idle_machines: dict[str, float],
) -> list[Node]:
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
            node
            for node in all_enabled_nodes.values()
            if node.cloud == ccfg.prefix
            and node.ip in idle_machines
            and (now - idle_machines[node.ip]) >= ccfg.idle_tolerance
        ]
        for node in nodes_to_disable:
            async with uow_factory() as uow:
                await uow.nodes.disable(node.node_id)
                await uow.commit()
                logger.debug(
                    "[deallocate_nodes][DISABLE] node_id=%s ip=%s cloud=%s",
                    node.node_id,
                    node.ip,
                    node.cloud,
                )
    # END_BLOCK_DISABLE_IDLE

    # START_BLOCK_COLLECT_DISABLED
    async with uow_factory() as uow:
        free_disabled_nodes = [
            node
            for node in await uow.nodes.list_disabled()
            if node.ip not in busy_ips and node.cloud
        ]
    return free_disabled_nodes
    # END_BLOCK_COLLECT_DISABLED
