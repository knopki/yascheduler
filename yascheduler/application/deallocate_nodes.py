"""Deallocate idle nodes use case — disable idle cloud nodes and reap every free disabled node."""
# region MODULE_CONTRACT
# PURPOSE: Stop paying for idle cloud capacity by disabling nodes that have been free past their configured tolerance, and reap any free disabled node so draining nodes are torn down once their task finishes.
# SCOPE: Idle cloud node deallocation + collect every free disabled node for teardown.
# KEYWORDS: deallocate, idle, node, cloud, disable, tolerance
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from yascheduler.domain import MachineState, Node, NodeId
from yascheduler.domain.exceptions import NodeRowNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import CloudConfig, CloudProvisioner, MachineRepository

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)

__all__ = ["deallocate_node", "deallocate_nodes"]


# region FUNC_deallocate_node
# PURPOSE: Tear down a node completely — disconnect SSH, disable in DB (cloud only), delete cloud VM (cloud only), remove row — so billing stops and the scheduler no longer tracks it.
# REQUIRES: The caller SHALL wrap deallocate_node in try/except Exception that logs node_id, hostname, and the error and continues; the caller SHALL NOT call repository.contains(...)/repository.disconnect(...) directly — SSH teardown is owned by deallocate_node.
# ENSURES: Cloud VM deletion happens before row removal; row removal itself runs for both cloud and static nodes (a static node disabled by --remove-soft is reaped here once its task finishes). If row removal fails, the error is logged but not re-raised (stale disabled row left for manual reconciliation). If the node's machine slot is BUSY at entry, teardown is skipped entirely, so the live task is not lost; a later cycle reaps the node once free.
# RATIONALE:
# - Q: Why re-check machine.state == BUSY at entry when deallocate_nodes already filters by busy_node_ids?
#   A: busy_node_ids is a single snapshot read before the disables; an allocator that read the enabled set before the disable holds (session, node) and occupies the slot afterward (occupy() runs before the SSH upload, before the RUNNING save). The stale snapshot would route that node here for VM deletion under a live task. The teardown-time re-check closes that window; BUSY is airtight because no event-loop yield separates the allocator's free-machine pick from occupy().
# - Q: Why do SSH disconnect and row removal run for both cloud and static nodes, while cloud VM deletion is conditional?
#   A: SSH disconnect and row removal are node-teardown steps, not cloud-specific. Cloud VM deletion (and its protective pre-disable bracket) is conditional on node.cloud because static nodes have no VM to delete; their row removal has no cloud-delete-failure risk to guard against. Static nodes reach this path via the orchestrator's drain flow: --remove-soft disables a busy node, the connect loop keeps it connected to finish the task, and once free the deallocate loop reaps the row.
async def deallocate_node(
    node: Node,
    repository: MachineRepository,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> None:
    """Disconnect and cloud-deallocate a single node."""
    # region BLOCK_recheck_busy
    # deallocate_nodes() snapshots busy_node_ids once, then disables nodes
    # across separate transactions. An in-flight allocator that read the
    # enabled set before the disable can still occupy this node and flip a
    # task to RUNNING: MachineSession.occupy() runs before the
    # SSH upload, with no event-loop yield between the allocator's
    # free-machine pick and occupy, so a BUSY machine here means a task is
    # live on the node. Tearing it down would lose the task silently (the
    # consumer's machine-gone path abandons it). Skip teardown; the node
    # stays disabled + connected so the consume loop finishes the task, and a
    # later deallocate cycle reaps it once the slot is FREE again.
    session = repository.get_session(node.node_id)
    if session is not None and session.machine.state == MachineState.BUSY:
        logger.debug(
            "SKIP_BUSY",
            extra={"node_id": node.node_id, "hostname": node.hostname},
        )
        return
    # endregion BLOCK_recheck_busy
    if repository.contains(node.node_id):
        await repository.disconnect(node.node_id)
        logger.debug(
            "DISCONNECT",
            extra={"node_id": node.node_id, "hostname": node.hostname},
        )
    if node.cloud:
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

    # region BLOCK_remove
    # Runs for both cloud and static nodes: SSH teardown and row removal are
    # not cloud-specific. The cloud VM deletion above is guarded; a static
    # node disabled by --remove-soft is reaped here once its task finishes.
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
    except NodeRowNotFoundError:
        # Row already gone. For cloud nodes the VM is already deleted; for
        # static nodes the row was removed concurrently. Nothing to reconcile.
        logger.debug(
            "node already removed: node_id=%s hostname=%s cloud=%s",
            node.node_id,
            node.hostname,
            node.cloud,
        )
    except Exception:
        # Row removal failed; the disabled DB row is stale. For cloud nodes
        # the VM is already gone. Log loudly so operators can reconcile
        # manually. Not re-raised: the next cycle's deallocate_node retries.
        logger.exception(
            "node remove failed: node_id=%s hostname=%s cloud=%s "
            "— DB row left disabled; manual reconciliation needed",
            node.node_id,
            node.hostname,
            node.cloud,
        )
    # endregion BLOCK_remove


# endregion FUNC_deallocate_node


# region FUNC_deallocate_nodes
# PURPOSE: Disable idle cloud nodes exceeding their configured idle tolerance and return the disabled Node objects for teardown (cloud VM deletion + static row removal).
# ENSURES: Returns disabled nodes (cloud and static) whose node_id is not in busy_node_ids; the disable phase is cloud-only (idle tolerance), but the collect phase returns every free disabled node so static drain nodes are reaped too. Intermediate list is non-empty for pyright/mypy inference.
async def deallocate_nodes(
    uow_factory: Callable[[], AbstractUnitOfWork],
    config_clouds: Sequence[CloudConfig],
    idle_machines: dict[NodeId, float],
) -> list[Node]:
    """Disable idle cloud nodes exceeding tolerance and return disabled Node objects for teardown."""
    # region BLOCK_disable_idle
    async with uow_factory() as uow:
        running_tasks = await uow.tasks.list_running()
        busy_node_ids = {t.state.allocated_node_id for t in running_tasks}
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
    # endregion BLOCK_disable_idle

    # region BLOCK_collect_disabled
    # Note: intermediate var is required — inlining the return inside the
    # async-with makes pyright/mypy infer an implicit None fall-through.
    async with uow_factory() as uow:
        # Collect every free disabled node — cloud (idle-tolerance) and
        # static (--remove-soft drain) alike. The disable phase above is
        # cloud-only; the reap phase is not: a draining static node must be
        # returned so its row is removed once its task finishes.
        free_disabled_nodes = [
            node
            for node in await uow.nodes.list_disabled()
            if node.node_id not in busy_node_ids
        ]
    return free_disabled_nodes  # noqa: RET504
    # endregion BLOCK_collect_disabled


# endregion FUNC_deallocate_nodes
