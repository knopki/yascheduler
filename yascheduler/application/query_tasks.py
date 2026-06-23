# FILE: yascheduler/application/query_tasks.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Query tasks use case — read-only task queries by status or job IDs via UoW.
#   SCOPE: query_tasks async function.
#   DEPENDS: M-DOMAIN-MODEL, M-APPLICATION-UOW
#   LINKS: M-DOMAIN-MODEL, M-APPLICATION-UOW, M-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   query_tasks - Read-only task query by statuses XOR job IDs within a single UoW
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extract query use case from Yascheduler.queue_get_tasks_async (client-query-uow).
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import Task, TaskStatus

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: query_tasks
#   PURPOSE: Read-only task query by statuses XOR job IDs within a single UoW.
#   INPUTS: {
#     jobs: Sequence[int] | None - Job IDs to query (mutually exclusive with statuses),
#     statuses: Sequence[TaskStatus] | None - Statuses to query (mutually exclusive with jobs),
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory for DB access
#   }
#   OUTPUTS: { list[Task] - Matching tasks; empty list if neither filter is non-empty }
#   SIDE_EFFECTS: Opens a single UoW for reading (no commit).
#   RAISES: ValueError - if both jobs and statuses are non-empty (mutually exclusive)
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: query_tasks
async def query_tasks(
    jobs: Sequence[int] | None,
    statuses: Sequence[TaskStatus] | None,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> list[Task]:
    # START_BLOCK_VALIDATE_INPUT
    if jobs and statuses:
        raise ValueError("jobs and statuses are mutually exclusive")
    # END_BLOCK_VALIDATE_INPUT

    # START_BLOCK_EMPTY_DISPATCH
    if not statuses and not jobs:
        logger.debug("[QueryTasks][query_tasks][EMPTY_DISPATCH] no filters supplied")
        return []
    # END_BLOCK_EMPTY_DISPATCH

    # START_BLOCK_QUERY
    async with uow_factory() as uow:
        if statuses:
            tasks = await uow.tasks.list_by_status(set(statuses))
        else:
            tasks = await uow.tasks.list_by_jobs(list(jobs or []))
    return tasks
    # END_BLOCK_QUERY
