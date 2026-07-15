# FILE: yascheduler/application/abandon_node.py
# VERSION: 2.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Abandon never-connected cloud node use case — VM delete + DB-row remove + discard tracker entry linked to the node.
#   SCOPE: Never-connected cloud node cleanup — VM delete, DB row remove, discard tracker entry by node via discard_by_node.
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ABANDON-NODE, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   abandon_node - Best-effort cloud VM delete (clouds.deallocate(node)), remove yascheduler_nodes row, discard tracker entry by node via discard_by_node
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.3.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...).
#   PREVIOUS_CHANGE: v2.2.0 - Split test-targeted CLOUD_DELETE_FAILED and AMBIGUOUS_TRACKER emits into log.trace + log.error/log.warning per reform-grace-logging slices 6.2-6.3.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.domain import CloudProvisioner, Node

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: abandon_node
#   PURPOSE: Clean up a cloud node that never established its SSH connection and discard the tracker entry linked to the node.
#   INPUTS: {
#     node: Node - The never-connected node to abandon,
#     clouds: CloudProvisioner - Cloud provider manager for VM deletion,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     tracker: AllocationTracker - In-flight allocation tracker holding the task-to-node link
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Best-effort cloud VM delete; removes node row from DB; discards tracker entries linked to the node via discard_by_node.
#   RAISES: Re-raises any exception from uow.nodes.remove / uow.commit (caller catches to keep the worker alive). Cloud-delete failures are swallowed (logged at error) so DB cleanup still runs.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: abandon_node
async def abandon_node(
    node: Node,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    tracker: AllocationTracker,
) -> None:
    # START_BLOCK_CLOUD_DELETE
    if node.cloud is not None:
        try:
            await clouds.deallocate(node)
        except Exception as err:
            logger.debug(
                "CLOUD_DELETE_FAILED",
                extra={
                    "node_id": node.node_id,
                    "hostname": node.hostname,
                    "cloud": node.cloud,
                    "err": err,
                },
            )
            logger.error("cloud delete failed for node %s: %s", node.hostname, err)
    # END_BLOCK_CLOUD_DELETE

    # START_BLOCK_REMOVE_ROW
    try:
        async with uow_factory() as uow:
            await uow.nodes.remove(node.node_id)
            await uow.commit()
    except Exception as err:
        logger.debug(
            "REMOVE_FAILED",
            extra={"node_id": node.node_id, "hostname": node.hostname, "err": err},
        )
        logger.error(
            "abandon_node remove failed: node_id=%s hostname=%s err=%s",
            node.node_id,
            node.hostname,
            err,
        )
        raise
    # END_BLOCK_REMOVE_ROW

    # START_BLOCK_DISCARD_BY_NODE
    removed = tracker.discard_by_node(node.node_id)
    if removed > 1:
        logger.debug(
            "AMBIGUOUS_TRACKER",
            extra={
                "node_id": node.node_id,
                "hostname": node.hostname,
                "count": removed,
            },
        )
        logger.warning(
            "ambiguous tracker: node %s has %d entries", node.hostname, removed
        )
    # END_BLOCK_DISCARD_BY_NODE
