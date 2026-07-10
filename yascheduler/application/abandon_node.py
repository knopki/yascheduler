# FILE: yascheduler/application/abandon_node.py
# VERSION: 2.0.0
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
#   LAST_CHANGE: v2.0.0 - Replace the dead TO_DO + allocated_node_id lookup with tracker.discard_by_node(node.node_id); the task-to-node link now lives in the tracker . Multi-match warning now signals tracker corruption over tracker entries, not TO_DO tasks.
#   PREVIOUS_CHANGE: v1.4.0 - calls clouds.deallocate(node).
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
            logger.error(
                "[abandon_node][CLOUD_DELETE_FAILED] node_id=%s ip=%s cloud=%s err=%s",
                node.node_id,
                node.ip,
                node.cloud,
                err,
            )
    # END_BLOCK_CLOUD_DELETE

    # START_BLOCK_REMOVE_ROW
    try:
        async with uow_factory() as uow:
            await uow.nodes.remove(node.node_id)
            await uow.commit()
    except Exception as err:
        logger.error(
            "[abandon_node][REMOVE_FAILED] node_id=%s ip=%s err=%s",
            node.node_id,
            node.ip,
            err,
        )
        raise
    # END_BLOCK_REMOVE_ROW

    # START_BLOCK_DISCARD_BY_NODE
    removed = tracker.discard_by_node(node.node_id)
    if removed > 1:
        logger.warning(
            "[abandon_node][AMBIGUOUS_TRACKER] node_id=%s ip=%s count=%d",
            node.node_id,
            node.ip,
            removed,
        )
    # END_BLOCK_DISCARD_BY_NODE
