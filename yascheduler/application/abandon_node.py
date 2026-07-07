# FILE: yascheduler/application/abandon_node.py
# VERSION: 1.4.0
# START_MODULE_CONTRACT
#   PURPOSE: Abandon never-connected cloud node use case — VM delete + DB-row remove + release stuck TO_DO task.
#   SCOPE: Never-connected cloud node cleanup — VM delete, DB row remove, release stuck TO_DO task.
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ABANDON-NODE, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   abandon_node - Best-effort cloud VM delete (clouds.deallocate(node)), remove yascheduler_nodes row, discard stuck task's tracker entry
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - calls clouds.deallocate(node).
#   PREVIOUS_CHANGE: v1.3.0 - matching rekeyed from t.allocated_ip to t.allocated_node_id; read stuck TO_DO task BEFORE node row remove.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from yascheduler.domain import Node, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.domain import CloudProvisioner

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: abandon_node
#   PURPOSE: Clean up a cloud node that never established its SSH connection and release its stuck task.
#   INPUTS: {
#     node: Node - The never-connected node to abandon,
#     clouds: CloudProvisioner - Cloud provider manager for VM deletion,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory,
#     tracker: AllocationTracker - In-flight allocation dedup to release the stuck task into
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Best-effort cloud VM delete; removes node row from DB; discards stuck task from AllocationTracker.
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

    # START_BLOCK_RELEASE_TASK
    # Read the stuck TO_DO task BEFORE removing the node row: the
    # allocated_node_id FK is ON DELETE SET NULL, so removing the node row
    # first would null allocated_node_id and the in-memory filter
    # `t.allocated_node_id == node.node_id` would no longer match. Reading
    # before remove keeps the matching robust to the FK cascade.
    async with uow_factory() as uow:
        todo_tasks = await uow.tasks.list_by_status({TaskStatus.TO_DO})
    matching = [t for t in todo_tasks if t.allocated_node_id == node.node_id]
    # END_BLOCK_RELEASE_TASK

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

    # START_BLOCK_DISCARD_TRACKER
    if len(matching) == 1:
        tracker.discard(matching[0].task_id)
    elif len(matching) > 1:
        logger.warning(
            "[abandon_node][AMBIGUOUS_TASK] node_id=%s ip=%s count=%d",
            node.node_id,
            node.ip,
            len(matching),
        )
    # END_BLOCK_DISCARD_TRACKER
