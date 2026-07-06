# FILE: yascheduler/application/query_tasks.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Query tasks use case — read-only task queries by status or job IDs via UoW, returning tasks alongside their allocated nodes.
#   SCOPE: query_tasks async function.
#   DEPENDS: M-DOMAIN-MODEL, M-APPLICATION-UOW
#   LINKS: M-DOMAIN-MODEL, M-APPLICATION-UOW, M-ENTRYPOINTS-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   query_tasks - Read-only task query by statuses XOR job IDs within a single UoW; returns (tasks, nodes_by_id)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - task-schema-and-entity-cleanup: query_tasks return type widens from list[Task] to tuple[list[Task], dict[NodeId, Node]]; after fetching tasks, batch-loads nodes via uow.nodes.get_by_ids when any task has an allocated_node_id (else returns (tasks, {})). The facade unpacks the tuple and passes nodes_by_id to _task_to_dict, which projects the nested node object.
#   PREVIOUS_CHANGE: v1.1.0 - query_tasks jobs param narrows Sequence[int] | None -> Sequence[TaskId] | None; forwards list(jobs) to list_by_jobs(list[TaskId]) (add-task-id-identity). The public Yascheduler.queue_get_tasks_async(jobs: list[int]) facade is the sole int/TaskId boundary on this path (wraps [TaskId(i) for i in jobs]).
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import Node, NodeId, Task, TaskId, TaskStatus

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: query_tasks
#   PURPOSE: Read-only task query by statuses XOR job IDs within a single UoW; returns tasks alongside their allocated nodes.
#   INPUTS: {
#     jobs: Sequence[TaskId] | None - Job IDs to query (mutually exclusive with statuses),
#     statuses: Sequence[TaskStatus] | None - Statuses to query (mutually exclusive with jobs),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory for DB access
#   }
#   OUTPUTS: { tuple[list[Task], dict[NodeId, Node]] - Matching tasks and their allocated nodes keyed by node_id; ([], {}) if neither filter is non-empty }
#   SIDE_EFFECTS: Opens a single UoW for reading (no commit).
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
        logger.debug("[QueryTasks][query_tasks][EMPTY_DISPATCH] no filters supplied")
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
