# FILE: yascheduler/client.py
# VERSION: 2.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public Python/CLI client for submitting and querying tasks.
#   SCOPE: Task submission (via DI/CLIDeps) and status query (via query_tasks use case + UoW).
#   DEPENDS: M-VARIABLES, M-COMPAT, M-CONFIG, M-DI, M-APPLICATION-QUERY-TASKS, M-DOMAIN-MODEL
#   LINKS: M-DI, M-AIIDA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Sync/async client wrapper for task operations
#   to_sync - Decorator wrapping async functions for sync execution
#   _task_to_dict - Project domain Task to the public 6-key Mapping shape
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.3.0 - Route queue_submit_task_async through self._deps_factory; drop local make_cli_deps import (submit/query symmetry).
#   PREVIOUS_CHANGE: v2.2.1 - FIXME on queue_submit_task_async asymmetry (bypasses deps_factory seam; follow-up proposal).
# END_CHANGE_SUMMARY

"""Yascheduler client"""

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from pathlib import PurePath
from typing import Any, Optional, TypeVar, Union

from .application import query_tasks
from .compat import ParamSpec
from .config import Config
from .di import CLIDeps, make_cli_deps
from .domain import Task, TaskStatus
from .variables import CONFIG_FILE

ReturnT_co = TypeVar("ReturnT_co", covariant=True)
ParamT = ParamSpec("ParamT")


def to_sync(
    func: Callable[ParamT, Coroutine[Any, Any, ReturnT_co]],
) -> Callable[ParamT, ReturnT_co]:
    """
    Wraps async function and run it sync in thread.
    """

    @wraps(func)
    def outer(*args: ParamT.args, **kwargs: ParamT.kwargs):  # noqa: ANN202
        """
        Execute the async method synchronously in sync and async runtime.
        """
        coro = func(*args, **kwargs)
        try:
            asyncio.get_running_loop()  # Triggers RuntimeError if no running event loop

            # Create a separate thread so we can block before returning
            with ThreadPoolExecutor(1) as pool:
                return pool.submit(lambda: asyncio.run(coro)).result()
        except RuntimeError:
            return asyncio.run(coro)

    return outer


# START_CONTRACT: _task_to_dict
#   PURPOSE: Project a domain Task to the public 6-key Mapping shape returned by query methods.
#   INPUTS: { t: Task - domain Task aggregate }
#   OUTPUTS: { Mapping[str, Any] - {task_id, label, ip, status, metadata, cloud} }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL
# END_CONTRACT: _task_to_dict
def _task_to_dict(t: Task) -> Mapping[str, Any]:
    return {
        "task_id": t.task_id,
        "label": t.label,
        "ip": t.allocated_ip or "",
        "status": t.status,
        "metadata": t.context.to_metadata(),
        "cloud": None,
    }


class Yascheduler:
    """Yascheduler client"""

    STATUS_TO_DO = TaskStatus.TO_DO.value
    STATUS_RUNNING = TaskStatus.RUNNING.value
    STATUS_DONE = TaskStatus.DONE.value

    config: Config
    _logger: Optional[logging.Logger] = None

    # START_CONTRACT: __init__
    #   PURPOSE: Initialize the Yascheduler client with config path and optional DI factory.
    #   INPUTS: {
    #     config_path: Union[PurePath, str],
    #     logger: Optional[logging.Logger],
    #     deps_factory: Optional[Callable[[Config], CLIDeps]] - keyword-only test seam
    #   }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Loads configuration from disk
    #   LINKS: M-CLIENT, M-CONFIG, M-DI
    # END_CONTRACT: __init__
    def __init__(
        self,
        config_path: Union[PurePath, str] = CONFIG_FILE,
        logger: Optional[logging.Logger] = None,
        *,
        deps_factory: Optional[Callable[[Config], CLIDeps]] = None,
    ) -> None:
        self.config = Config.from_config_parser(config_path)
        self._logger = logger
        self._deps_factory = deps_factory or make_cli_deps

    # START_CONTRACT: queue_submit_task_async
    #   PURPOSE: Submit a new task asynchronously via the deps_factory seam (CLIDeps.submit).
    #   INPUTS: { label: str, metadata: Mapping[str, Any], engine_name: str, webhook_onsubmit: bool }
    #   OUTPUTS: { int - task_id }
    #   SIDE_EFFECTS: Creates a new task in the database via submit_task use case.
    #   LINKS: M-CLIENT, M-DI
    # END_CONTRACT: queue_submit_task_async
    async def queue_submit_task_async(
        self,
        label: str,
        metadata: Mapping[str, Any],
        engine_name: str,
        webhook_onsubmit: bool = False,
    ) -> int:
        """Submit new task"""
        deps = self._deps_factory(self.config)
        return await deps.submit(label, dict(metadata), engine_name)

    # START_CONTRACT: queue_submit_task
    #   PURPOSE: Submit a new task synchronously
    #   INPUTS: { label: str, metadata: Mapping[str, Any], engine_name: str, webhook_onsubmit: bool }
    #   OUTPUTS: { int - task_id }
    #   SIDE_EFFECTS: Creates a new task in the database
    #   LINKS: M-CLIENT
    # END_CONTRACT: queue_submit_task
    def queue_submit_task(
        self,
        label: str,
        metadata: Mapping[str, Any],
        engine_name: str,
        webhook_onsubmit: bool = False,
    ) -> int:
        """Submit new task"""
        fn = to_sync(self.queue_submit_task_async)
        return fn(label, metadata, engine_name, webhook_onsubmit)

    # START_CONTRACT: queue_get_tasks_async
    #   PURPOSE: Query tasks asynchronously by job IDs or statuses via the query_tasks use case.
    #   INPUTS: { jobs: Optional[Sequence[int]], status: Optional[Sequence[int]] }
    #   OUTPUTS: { Sequence[Mapping[str, Any]] - list of task dicts with 6 keys each }
    #   SIDE_EFFECTS: Opens a UoW (DB connection) per call via deps_factory; reads task records
    #   RAISES: ValueError - if both jobs and statuses are non-empty (mutual exclusivity)
    #   LINKS: M-CLIENT, M-APPLICATION-QUERY-TASKS, M-DI
    # END_CONTRACT: queue_get_tasks_async
    async def queue_get_tasks_async(
        self,
        jobs: Optional[Sequence[int]] = None,
        status: Optional[Sequence[int]] = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Get tasks by ids or statuses"""
        # raise ValueError if unknown task status
        statuses: Optional[list[TaskStatus]] = (
            [TaskStatus(x) for x in status] if status else None
        )
        deps = self._deps_factory(self.config)
        tasks = await query_tasks(jobs, statuses, deps.uow_factory)
        return [_task_to_dict(t) for t in tasks]

    # START_CONTRACT: queue_get_tasks
    #   PURPOSE: Query tasks synchronously by job IDs or statuses
    #   INPUTS: { jobs: Optional[Sequence[int]], status: Optional[Sequence[int]] }
    #   OUTPUTS: { Sequence[Mapping[str, Any]] }
    #   SIDE_EFFECTS: Opens a UoW via async delegate
    #   LINKS: M-CLIENT, M-APPLICATION-QUERY-TASKS
    # END_CONTRACT: queue_get_tasks
    def queue_get_tasks(
        self,
        jobs: Optional[Sequence[int]] = None,
        status: Optional[Sequence[int]] = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Get tasks by ids or statuses"""
        return to_sync(self.queue_get_tasks_async)(jobs, status)

    # START_CONTRACT: queue_get_task_async
    #   PURPOSE: Get a single task by ID asynchronously
    #   INPUTS: { task_id: int }
    #   OUTPUTS: { Optional[Mapping[str, Any]] }
    #   SIDE_EFFECTS: Opens a UoW via queue_get_tasks_async
    #   LINKS: M-CLIENT, M-APPLICATION-QUERY-TASKS
    # END_CONTRACT: queue_get_task_async
    async def queue_get_task_async(self, task_id: int) -> Optional[Mapping[str, Any]]:
        """Get task by id"""
        for task_dict in await self.queue_get_tasks_async(jobs=[task_id]):
            return task_dict

    # START_CONTRACT: queue_get_task
    #   PURPOSE: Get a single task by ID synchronously
    #   INPUTS: { task_id: int }
    #   OUTPUTS: { Optional[Mapping[str, Any]] }
    #   SIDE_EFFECTS: Opens a UoW via queue_get_tasks
    #   LINKS: M-CLIENT, M-APPLICATION-QUERY-TASKS
    # END_CONTRACT: queue_get_task
    def queue_get_task(self, task_id: int) -> Optional[Mapping[str, Any]]:
        """Get task by id"""
        for task_dict in self.queue_get_tasks(jobs=[task_id]):
            return task_dict
