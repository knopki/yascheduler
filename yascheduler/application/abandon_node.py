# FILE: yascheduler/application/abandon_node.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Abandon never-connected cloud node use case — VM delete + DB-row remove + release stuck TO_DO task.
#   SCOPE: abandon_node async function.
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ABANDON-NODE, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   abandon_node - Best-effort cloud VM delete, remove yascheduler_nodes row, discard stuck task's tracker entry
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Mutator rekeyed from ip to node_id (node-id-keyed-mutators): uow.nodes.remove(node.node_id) (was node.ip). Internal log lines add node_id=%s alongside ip=%s. clouds.deallocate(node.cloud, node.ip) stays ip-keyed (ip = cloud host, out of scope).
#   PREVIOUS_CHANGE: v1.1.0 - Drop the unused gateway parameter (decompose-ssh-gateway). The node was never registered with the repository, so no SSH-side call is needed; the previous gateway param was present only for symmetry with deallocate_node and was never used in the body.
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
#   SIDE_EFFECTS: Best-effort cloud VM delete (logged not raised); removes yascheduler_nodes row + commit (re-raised on failure so the orchestrator's outer try/except keeps the worker alive); on success, discards the stuck TO_DO task from AllocationTracker so it re-allocates on the next cycle. Does NOT call repository.disconnect (node was never in the repository). Does NOT mark the task FAILED or emit a domain event (per Non-Goal on re-allocation limits).
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
            await clouds.deallocate(node.cloud, node.ip)
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

    # START_BLOCK_RELEASE_TASK
    async with uow_factory() as uow:
        todo_tasks = await uow.tasks.list_by_status({TaskStatus.TO_DO})
    matching = [t for t in todo_tasks if t.allocated_ip == node.ip]
    if len(matching) == 1:
        tracker.discard(matching[0].task_id)
    elif len(matching) > 1:
        logger.warning(
            "[abandon_node][AMBIGUOUS_TASK] node_id=%s ip=%s count=%d",
            node.node_id,
            node.ip,
            len(matching),
        )
    # END_BLOCK_RELEASE_TASK
