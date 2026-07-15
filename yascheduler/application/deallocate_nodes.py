"""Deallocate idle nodes use case — disable idle cloud nodes and return Node objects for VM deletion."""
# FILE: yascheduler/application/deallocate_nodes.py
# VERSION: 4.10.0
# START_MODULE_CONTRACT
#   PURPOSE: Deallocate idle nodes use case — disable idle cloud nodes and return Node objects for VM deletion.
#   SCOPE: Idle cloud node deallocation — disable idle nodes, return Node objects for VM deletion.
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-SSH-REPOSITORY, M-CLOUD-PROVISIONER
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   deallocate_node - Disconnect (by node_id) and cloud-deallocate a single node (clouds.deallocate(node) reads node.cloud/node.hostname internally); logs+flags stale row if DB remove fails after successful cloud delete
#   deallocate_nodes - Disable idle cloud nodes and return Node objects for VM deletion (idle_machines dict[NodeId, float]; busy_node_ids matching)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v4.10.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v4.10.0 - Rewrite REMOVE_FAILED error to pure narrative (no grace marker) per reform-grace-logging slice 7.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from yascheduler.domain import Node, NodeId, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import CloudConfig, CloudProvisioner, MachineRepository

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: deallocate_node
#   PURPOSE: Disconnect and cloud-deallocate a single node.
#   INPUTS: {
#     node: Node - The node to deallocate,
#     repository: MachineRepository - SSH gateway,
#     clouds: CloudProvisioner - Cloud provider manager,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Disconnects remote machine, disables node via UoW, deletes cloud VM, removes node row. If remove fails after cloud delete, logs for manual reconciliation.
#   LINKS: M-SSH-REPOSITORY, M-CLOUD-PROVISIONER, M-APPLICATION-UOW
# END_CONTRACT: deallocate_node
async def deallocate_node(
    node: Node,
    repository: MachineRepository,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> None:
    """Disconnect and cloud-deallocate a single node."""
    if repository.contains(node.node_id):
        await repository.disconnect(node.node_id)
        logger.debug(
            "DISCONNECT",
            extra={"node_id": node.node_id, "hostname": node.hostname},
        )
    if node.cloud:
        # START_BLOCK_DISABLE
        logger.debug(
            "DISABLE",
            extra={
                "node_id": node.node_id,
                "hostname": node.hostname,
                "cloud": node.cloud,
            },
        )
        async with uow_factory() as uow:
            await uow.nodes.disable(node.node_id)
            await uow.commit()
        # END_BLOCK_DISABLE

        # START_BLOCK_CLOUD_DELETE
        logger.debug(
            "CLOUD_DELETE",
            extra={
                "node_id": node.node_id,
                "hostname": node.hostname,
                "cloud": node.cloud,
            },
        )
        await clouds.deallocate(node)
        # END_BLOCK_CLOUD_DELETE

        # START_BLOCK_REMOVE
        logger.debug(
            "REMOVE",
            extra={
                "node_id": node.node_id,
                "hostname": node.hostname,
                "cloud": node.cloud,
            },
        )
        try:
            async with uow_factory() as uow:
                await uow.nodes.remove(node.node_id)
                await uow.commit()
        except Exception:
            # Cloud VM is already gone; the disabled DB row is stale. Log
            # loudly so operators can reconcile manually. Not re-raised: the
            # cloud delete succeeded, and the next cycle's deallocate_node
            # will re-attempt (cloud-SDK delete-idempotency dependent) plus
            # this remove.
            logger.exception(
                "node remove failed: node_id=%s hostname=%s cloud=%s "
                "— VM is deleted but DB row left disabled; "
                "manual reconciliation needed",
                node.node_id,
                node.hostname,
                node.cloud,
            )
        # END_BLOCK_REMOVE


# START_CONTRACT: deallocate_nodes
#   PURPOSE: Disable idle cloud nodes exceeding tolerance and return their Node objects for VM deletion.
#   INPUTS: {
#     uow_factory: Callable[[], AbstractUnitOfWork] - Unit of Work factory,
#     config_clouds: Sequence[CloudConfig] - Cloud configuration with idle_tolerance,
#     idle_machines: dict[NodeId, float] - NodeId -> free_since monotonic timestamp (seconds since arbitrary epoch)
#   }
#   OUTPUTS: { list[Node] - Disabled node objects (each carrying node_id) for orchestrator to deallocate }
#   SIDE_EFFECTS: Disables nodes in DB.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS
# END_CONTRACT: deallocate_nodes
async def deallocate_nodes(
    uow_factory: Callable[[], AbstractUnitOfWork],
    config_clouds: Sequence[CloudConfig],
    idle_machines: dict[NodeId, float],
) -> list[Node]:
    """Disable idle cloud nodes exceeding tolerance and return their Node objects for VM deletion."""
    # START_BLOCK_DISABLE_IDLE
    async with uow_factory() as uow:
        running_tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
        busy_node_ids = {
            t.allocated_node_id for t in running_tasks if t.allocated_node_id
        }
        all_enabled_nodes = {
            n.node_id: n
            for n in await uow.nodes.list_enabled()
            if n.node_id not in busy_node_ids
        }

    now = time.monotonic()
    for ccfg in config_clouds:
        nodes_to_disable = [
            node
            for node in all_enabled_nodes.values()
            if node.cloud == ccfg.prefix
            and node.node_id in idle_machines
            and (now - idle_machines[node.node_id]) >= ccfg.idle_tolerance
        ]
        for node in nodes_to_disable:
            async with uow_factory() as uow:
                await uow.nodes.disable(node.node_id)
                await uow.commit()
                logger.debug(
                    "DISABLE",
                    extra={
                        "node_id": node.node_id,
                        "hostname": node.hostname,
                        "cloud": node.cloud,
                    },
                )
    # END_BLOCK_DISABLE_IDLE

    # START_BLOCK_COLLECT_DISABLED
    # Note: intermediate var is required — inlining the return inside the
    # async-with makes pyright/mypy infer an implicit None fall-through.
    async with uow_factory() as uow:
        free_disabled_nodes = [
            node
            for node in await uow.nodes.list_disabled()
            if node.node_id not in busy_node_ids and node.cloud
        ]
    return free_disabled_nodes  # noqa: RET504
    # END_BLOCK_COLLECT_DISABLED
