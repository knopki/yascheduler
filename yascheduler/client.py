# FILE: yascheduler/client.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public Python/CLI client for submitting and querying tasks.
#   SCOPE: Task submission (via DI/CLIDeps) and status query (via DB).
#   DEPENDS: M-DB, M-VARIABLES, M-COMPAT, M-CONFIG, M-DI
#   LINKS: M-DB, M-DI, M-AIIDA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Sync/async client wrapper for task operations
#   to_sync - Decorator wrapping async functions for sync execution
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Replace Scheduler import with make_cli_deps for submit; query methods unchanged.
#   PREVIOUS_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Yascheduler client"""

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from pathlib import PurePath
from typing import Any, Optional, TypeVar, Union

from attrs import asdict

from .compat import ParamSpec
from .config import Config
from .db import DB, TaskStatus
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
    def outer(*args: ParamT.args, **kwargs: ParamT.kwargs):
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


class Yascheduler:
    """Yascheduler client"""

    STATUS_TO_DO = TaskStatus.TO_DO.value
    STATUS_RUNNING = TaskStatus.RUNNING.value
    STATUS_DONE = TaskStatus.DONE.value

    config: Config
    _logger: Optional[logging.Logger] = None

    # START_CONTRACT: __init__
    #   PURPOSE: Initialize the Yascheduler client with config path
    #   INPUTS: { config_path: Union[PurePath, str], logger: Optional[logging.Logger] }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Loads configuration from disk
    #   LINKS: M-CLIENT, M-CONFIG
    # END_CONTRACT: __init__
    def __init__(
        self,
        config_path: Union[PurePath, str] = CONFIG_FILE,
        logger: Optional[logging.Logger] = None,
    ):
        self.config = Config.from_config_parser(config_path)
        self._logger = logger

    # START_CONTRACT: queue_submit_task_async
    #   PURPOSE: Submit a new task asynchronously via CLIDeps (no Scheduler import).
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
        webhook_onsubmit=False,
    ) -> int:
        """Submit new task"""
        from .di import make_cli_deps

        deps = make_cli_deps(self.config)
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
        webhook_onsubmit=False,
    ) -> int:
        """Submit new task"""
        fn = to_sync(self.queue_submit_task_async)
        return fn(label, metadata, engine_name, webhook_onsubmit)

    # START_CONTRACT: queue_get_tasks_async
    #   PURPOSE: Query tasks asynchronously by job IDs or statuses
    #   INPUTS: { jobs: Optional[Sequence[int]], status: Optional[Sequence[int]] }
    #   OUTPUTS: { Sequence[Mapping[str, Any]] - list of task dicts }
    #   SIDE_EFFECTS: Creates a DB connection; reads task records
    #   LINKS: M-CLIENT, M-DB
    # END_CONTRACT: queue_get_tasks_async
    async def queue_get_tasks_async(
        self,
        jobs: Optional[Sequence[int]] = None,
        status: Optional[Sequence[int]] = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Get tasks by ids or statuses"""
        if jobs is not None and status is not None:
            raise ValueError("jobs can be selected only by status or by task ids")
        # raise ValueError if unknown task status
        statuses: Optional[list[TaskStatus]] = (
            [TaskStatus(x) for x in status] if status else None
        )
        db = await DB.create(self.config.db)
        if statuses:
            tasks = await db.get_tasks_by_status(statuses)
        elif jobs:
            tasks = await db.get_tasks_by_jobs(jobs)
        else:
            return []
        return [asdict(t) for t in tasks]  # type: ignore[arg-type]

    # START_CONTRACT: queue_get_tasks
    #   PURPOSE: Query tasks synchronously by job IDs or statuses
    #   INPUTS: { jobs: Optional[Sequence[int]], status: Optional[Sequence[int]] }
    #   OUTPUTS: { Sequence[Mapping[str, Any]] }
    #   SIDE_EFFECTS: Creates a DB connection via async delegate
    #   LINKS: M-CLIENT, M-DB
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
    #   SIDE_EFFECTS: Creates a DB connection via queue_get_tasks_async
    #   LINKS: M-CLIENT, M-DB
    # END_CONTRACT: queue_get_task_async
    async def queue_get_task_async(self, task_id: int) -> Optional[Mapping[str, Any]]:
        """Get task by id"""
        for task_dict in await self.queue_get_tasks_async(jobs=[task_id]):
            return task_dict

    # START_CONTRACT: queue_get_task
    #   PURPOSE: Get a single task by ID synchronously
    #   INPUTS: { task_id: int }
    #   OUTPUTS: { Optional[Mapping[str, Any]] }
    #   SIDE_EFFECTS: Creates a DB connection via queue_get_tasks
    #   LINKS: M-CLIENT, M-DB
    # END_CONTRACT: queue_get_task
    def queue_get_task(self, task_id: int) -> Optional[Mapping[str, Any]]:
        """Get task by id"""
        for task_dict in self.queue_get_tasks(jobs=[task_id]):
            return task_dict
