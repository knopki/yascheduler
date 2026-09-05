"""Abandon never-connected cloud node use case — disable row, VM delete, DB-row remove, discard tracker entry linked to the node."""
# region MODULE_CONTRACT
# PURPOSE: Prevent resource leaks — orphan cloud VMs, stale DB rows, dangling tracker entries — when a provisioned node never connects, so billing stops and the scheduler does not track phantom resources.
# SCOPE: Never-connected cloud node cleanup — DB row disable, cloud VM delete, node row removal, tracker discard-by-node.
# KEYWORDS: abandon, never-connected, cloud, cleanup, vm delete, tracker, external_id
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from yascheduler.domain.exceptions import NodeRowNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.domain import CloudProvisioner, Node, NodeId

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)

__all__ = ["abandon_node"]


async def _remove_row(
    uow_factory: Callable[[], AbstractUnitOfWork],
    node_id: NodeId,
    hostname: str,
) -> None:
    """Remove the node's DB row; swallow the not-found case, report and re-raise other failures."""
    try:
        async with uow_factory() as uow:
            await uow.nodes.remove(node_id)
            await uow.commit()
    except NodeRowNotFoundError:
        logger.debug(
            "abandon_node row already removed: node_id=%s hostname=%s",
            node_id,
            hostname,
        )
    except Exception as err:
        logger.debug(
            "REMOVE_FAILED",
            extra={"node_id": node_id, "hostname": hostname, "err": err},
        )
        logger.exception(
            "abandon_node remove failed: node_id=%s hostname=%s",
            node_id,
            hostname,
        )
        raise


# region FUNC_abandon_node
# PURPOSE: Clean up all traces of a never-connected node — DB row disable, cloud VM delete, DB row removal, tracker discard — so cloud billing stops and future tasks are not falsely deduped.
# REQUIRES: node is a cloud node (cloud is not None) for the VM-delete path.
# ENSURES: The DB row is disabled before the cloud VM deletion is attempted. A cloud VM deletion failure propagates and leaves the DB row disabled (with external_id preserved) so a later deallocate cycle can retry; the DB row is removed only after a successful VM deletion. The tracker entry for the node is discarded in all cases (success, VM-deletion failure, no-cloud branch). A DB-row removal failure after a successful VM deletion re-raises.
async def abandon_node(
    node: Node,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
    tracker: AllocationTracker,
) -> None:
    """Clean up a cloud node that never established its SSH connection and discard the tracker entry linked to the node."""
    try:
        if node.cloud is not None:
            # region BLOCK_disable
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
            # endregion BLOCK_disable

            # region BLOCK_cloud_delete
            logger.debug(
                "CLOUD_DELETE",
                extra={
                    "node_id": node.node_id,
                    "hostname": node.hostname,
                    "cloud": node.cloud,
                },
            )
            await clouds.deallocate(node)
            # endregion BLOCK_cloud_delete

            # region BLOCK_remove_row
            logger.debug(
                "REMOVE",
                extra={
                    "node_id": node.node_id,
                    "hostname": node.hostname,
                    "cloud": node.cloud,
                },
            )
            await _remove_row(uow_factory, node.node_id, node.hostname)
            # endregion BLOCK_remove_row
        else:
            # region BLOCK_remove_row_no_cloud
            # No cloud VM to delete; remove the DB row directly.
            logger.debug(
                "REMOVE_NO_CLOUD",
                extra={
                    "node_id": node.node_id,
                    "hostname": node.hostname,
                },
            )
            await _remove_row(uow_factory, node.node_id, node.hostname)
            # endregion BLOCK_remove_row_no_cloud
    finally:
        # region BLOCK_discard_by_node
        # Discarded in `finally` so the entry is released whether or not
        # the cloud VM deletion (or the DB-row removal) raised. The
        # abandoned node is never allocated again, so its in-flight
        # allocation entry is dead weight in all outcomes.
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
