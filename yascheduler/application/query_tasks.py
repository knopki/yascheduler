# FILE: yascheduler/application/query_tasks.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Read-only task query by statuses or job IDs.
#   SCOPE: Read-only task query by statuses XOR job IDs within a single UoW; returns tasks alongside their allocated nodes.
#   DEPENDS: M-DOMAIN-MODEL, M-APPLICATION-UOW
#   LINKS: M-DOMAIN-MODEL, M-APPLICATION-UOW, M-ENTRYPOINTS-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   query_tasks - Read-only task query by statuses XOR job IDs within a single UoW; returns (tasks, nodes_by_id)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Return type widens to tuple[list[Task], dict[NodeId, Node]]; batch-load nodes via uow.nodes.get_by_ids.
#   PREVIOUS_CHANGE: v1.1.0 - jobs param narrows to Sequence[TaskId]; forwards list(jobs) to list_by_jobs(list[TaskId]).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

from yascheduler.shared import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import Node, NodeId, Task, TaskId, TaskStatus

    from .uow import AbstractUnitOfWork

logger = get_logger("M-APPLICATION-QUERY-TASKS")


# START_CONTRACT: query_tasks
#   PURPOSE: Read-only task query by statuses XOR job IDs within a single UoW; returns tasks alongside their allocated nodes.
#   INPUTS: {
#     jobs: Sequence[TaskId] | None - Job IDs to query (mutually exclusive with statuses),
#     statuses: Sequence[TaskStatus] | None - Statuses to query (mutually exclusive with jobs),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory for DB access
#   }
#   OUTPUTS: { tuple[list[Task], dict[NodeId, Node]] - Matching tasks and their allocated nodes keyed by node_id; ([], {}) if neither filter is non-empty }
#   SIDE_EFFECTS: None — read-only.
#   RAISES: ValueError - if both jobs and statuses are non-empty (mutually exclusive)
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: query_tasks
async def query_tasks(
    jobs: Sequence[TaskId] | None,
    statuses: Sequence[TaskStatus] | None,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> tuple[list[Task], dict[NodeId, Node]]:
    # START_BLOCK_VALIDATE_INPUT
    if jobs and statuses:
        raise ValueError("jobs and statuses are mutually exclusive")
    # END_BLOCK_VALIDATE_INPUT

    # START_BLOCK_EMPTY_DISPATCH
    if not statuses and not jobs:
        logger.trace("EMPTY_DISPATCH")
        return [], {}
    # END_BLOCK_EMPTY_DISPATCH

    # START_BLOCK_QUERY
    async with uow_factory() as uow:
        if statuses:
            tasks = await uow.tasks.list_by_status(set(statuses))
        else:
            tasks = await uow.tasks.list_by_jobs(list(jobs or []))
        # START_BLOCK_BATCH_LOAD_NODES
        node_ids = [
            t.allocated_node_id for t in tasks if t.allocated_node_id is not None
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
        # END_BLOCK_BATCH_LOAD_NODES
    return tasks, nodes_by_id
    # END_BLOCK_QUERY
