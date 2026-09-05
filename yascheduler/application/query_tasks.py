"""Read-only task query by statuses or job IDs."""
# region MODULE_CONTRACT
# PURPOSE: Provide a read-only snapshot of tasks and their allocated nodes so CLI and API consumers can display scheduler state without side effects.
# SCOPE: query_tasks use case — status-based or job-ID-based lookup with batch node loading.
# KEYWORDS: query, tasks, status, jobs, read-only, list
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

from yascheduler.domain import allocated_node_id_of

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import AnyTask, Node, NodeId, TaskId, TaskStatus

    from .uow import AbstractUnitOfWork

__all__ = ["query_tasks"]


# region FUNC_query_tasks
# PURPOSE: Let CLI/API consumers filter tasks by status or job ID in a single DB round trip, so they can build dashboards or check completion without unnecessary queries.
# REQUIRES: jobs and statuses are mutually exclusive (ValueError raised if both non-empty).
# ENSURES: Returns ([], {}) when neither filter is provided; tasks are read-only, no side effects.
async def query_tasks(
    jobs: Sequence[TaskId] | None,
    statuses: Sequence[TaskStatus] | None,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> tuple[list[AnyTask], dict[NodeId, Node]]:
    """Read-only task query by statuses XOR job IDs within a single UoW; returns tasks alongside their allocated nodes."""
    # region BLOCK_validate_input
    if jobs and statuses:
        msg = "jobs and statuses are mutually exclusive"
        raise ValueError(msg)
    # endregion BLOCK_validate_input

    # region BLOCK_empty_dispatch
    if not statuses and not jobs:
        return [], {}
    # endregion BLOCK_empty_dispatch

    # region BLOCK_query
    async with uow_factory() as uow:
        if statuses:
            tasks = await uow.tasks.list_by_status(set(statuses))
        else:
            tasks = await uow.tasks.list_by_jobs(list(jobs or []))
        # region BLOCK_batch_load_nodes
        node_ids = [
            nid for nid in (allocated_node_id_of(t) for t in tasks) if nid is not None
        ]
        # Deduplicate while preserving a stable order for deterministic tests.
        seen: set[NodeId] = set()
        distinct_node_ids: list[NodeId] = []
        for nid in node_ids:
            if nid not in seen:
                seen.add(nid)
                distinct_node_ids.append(nid)
        if distinct_node_ids:
            nodes_by_id = await uow.nodes.get_by_ids(distinct_node_ids)
        else:
            nodes_by_id = {}
        # endregion BLOCK_batch_load_nodes
    return tasks, nodes_by_id
    # endregion BLOCK_query


# endregion FUNC_query_tasks
