"""Abandon never-connected cloud node use case — VM delete + DB-row remove + discard tracker entry linked to the node."""
# region MODULE_CONTRACT
# PURPOSE: Prevent resource leaks — orphan cloud VMs, stale DB rows, dangling tracker entries — when a provisioned node never connects, so billing stops and the scheduler does not track phantom resources.
# SCOPE: Never-connected cloud node cleanup — cloud VM delete (best-effort), node row removal, tracker discard-by-node.
# KEYWORDS: abandon, never-connected, cloud, cleanup, vm delete, tracker
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from yascheduler.domain.exceptions import NodeRowNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.domain import CloudProvisioner, Node

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)

__all__ = ["abandon_node"]


# region FUNC_abandon_node
# PURPOSE: Clean up all traces of a never-connected node — best-effort cloud VM delete, DB row removal, tracker discard — so cloud billing stops and future tasks are not falsely deduped.
# REQUIRES: node is a cloud node (cloud is not None).
# ENSURES: Cloud VM deletion is best-effort (logged on failure, never raised); DB row removal failure re-raises; tracker entries for the node are discarded.
async def abandon_node(
    node: Node,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    tracker: AllocationTracker,
) -> None:
    """Clean up a cloud node that never established its SSH connection and discard the tracker entry linked to the node."""
    # region BLOCK_cloud_delete
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
            logger.exception("cloud delete failed for node %s", node.hostname)
    # endregion BLOCK_cloud_delete

    # region BLOCK_remove_row
    try:
        async with uow_factory() as uow:
            await uow.nodes.remove(node.node_id)
            await uow.commit()
    except NodeRowNotFoundError:
        # Row already gone — the
        # desired end state; VM is already deleted above. Not an error.
        logger.debug(
            "abandon_node row already removed: node_id=%s hostname=%s",
            node.node_id,
            node.hostname,
        )
    except Exception as err:
        logger.debug(
            "REMOVE_FAILED",
            extra={"node_id": node.node_id, "hostname": node.hostname, "err": err},
        )
        logger.exception(
            "abandon_node remove failed: node_id=%s hostname=%s",
            node.node_id,
            node.hostname,
        )
        raise
    # endregion BLOCK_remove_row

    # region BLOCK_discard_by_node
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
            "ambiguous tracker: node %s has %d entries",
            node.hostname,
            removed,
        )
    # endregion BLOCK_discard_by_node


# endregion FUNC_abandon_node
