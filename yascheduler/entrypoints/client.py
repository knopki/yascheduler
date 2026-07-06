# FILE: yascheduler/entrypoints/client.py
# VERSION: 2.10.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public Python/CLI client for submitting and querying tasks.
#   SCOPE: Task submission (via DI/CLIDeps) and status query (via query_tasks use case + UoW); private to_sync async-to-sync bridge helper.
#   DEPENDS: M-ENTRYPOINTS-CONFIG, M-DI, M-APPLICATION-QUERY-TASKS, M-DOMAIN-MODEL, M-ENTRYPOINTS-PATHS
#   LINKS: M-DI, M-AIIDA, M-ENTRYPOINTS, M-ENTRYPOINTS-PATHS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Sync/async client wrapper for task operations
#   _task_to_dict - Project domain Task to the public shape
#   to_sync - Private async-to-sync decorator (inlined from former yascheduler.shared.async_utils; not re-exported)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.10.0 - drop-task-context-entity: _task_to_dict reconstructs the flat metadata dict inline from the six typed Task fields (engine, remote_folder, local_folder, webhook_url, webhook_custom_params, error — None omitted) plus **t.extra (was t.context.to_metadata()). Public dict shape {task_id, label, status, metadata, node} unchanged.
#   PREVIOUS_CHANGE: v2.9.0 - task-schema-and-entity-cleanup: queue_get_tasks_async unpacks (tasks, nodes_by_id) from query_tasks (return type widened to tuple); _task_to_dict(t, nodes_by_id) drops flat "ip"/"cloud" keys and adds a nested "node" object {ip, port, username, cloud} (or null) built from nodes_by_id.get(t.allocated_node_id). Public keys are now {task_id, label, status, metadata, node}. BREAKING facade dict shape change.
# END_CHANGE_SUMMARY

"""Yascheduler client"""

import asyncio
import logging
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from pathlib import PurePath
from typing import Any, Optional, TypeVar, Union

from yascheduler.application import query_tasks
from yascheduler.domain import Node, NodeId, Task, TaskId, TaskStatus
from yascheduler.entrypoints.config import Config
from yascheduler.entrypoints.config_parser import parse_config

from .di import CLIDeps, make_cli_deps
from .paths import CONFIG_FILE

if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec
else:
    from typing import ParamSpec

ReturnT_co = TypeVar("ReturnT_co", covariant=True)
ParamT = ParamSpec("ParamT")


# START_CONTRACT: to_sync
#   PURPOSE: Wrap an async function so it can be called synchronously, detecting a running event loop and offloading to a worker thread when necessary.
#   INPUTS: { func: Callable[ParamT, Coroutine[Any, Any, ReturnT_co]] - async function to wrap }
#   OUTPUTS: { Callable[ParamT, ReturnT_co] - sync callable preserving the wrapped signature }
#   SIDE_EFFECTS: May spawn a ThreadPoolExecutor and call asyncio.run in a worker thread when a running event loop is detected.
#   LINKS: M-ENTRYPOINTS-CLIENT
# END_CONTRACT: to_sync
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
#   PURPOSE: Project a domain Task to the public 5-key Mapping shape returned by query methods.
#   INPUTS: { t: Task - domain Task aggregate (t.task_id: TaskId), nodes_by_id: dict[NodeId, Node] - node lookup by allocated_node_id }
#   OUTPUTS: { Mapping[str, Any] - public shape }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL
# END_CONTRACT: _task_to_dict
def _task_to_dict(t: Task, nodes_by_id: dict[NodeId, Node]) -> Mapping[str, Any]:
    node = nodes_by_id.get(t.allocated_node_id) if t.allocated_node_id else None
    metadata: dict[str, Any] = {"engine": t.engine}
    if t.remote_folder is not None:
        metadata["remote_folder"] = t.remote_folder
    if t.local_folder is not None:
        metadata["local_folder"] = t.local_folder
    if t.webhook_url is not None:
        metadata["webhook_url"] = t.webhook_url
    if t.webhook_custom_params:
        metadata["webhook_custom_params"] = t.webhook_custom_params
    if t.error is not None:
        metadata["error"] = t.error
    for k, v in t.extra.items():
        if k not in metadata:
            metadata[k] = v
    return {
        "task_id": t.task_id.value,
        "label": t.label,
        "status": t.status,
        "metadata": metadata,
        "node": (
            {
                "ip": node.ip,
                "port": node.port,
                "username": node.username,
                "cloud": node.cloud,
            }
            if node is not None
            else None
        ),
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
    #   LINKS: M-ENTRYPOINTS-CLIENT, M-ENTRYPOINTS-CONFIG, M-DI
    # END_CONTRACT: __init__
    def __init__(
        self,
        config_path: Union[PurePath, str] = CONFIG_FILE,
        logger: Optional[logging.Logger] = None,
        *,
        deps_factory: Optional[Callable[[Config], CLIDeps]] = None,
    ) -> None:
        self.config = parse_config(config_path)
        self._logger = logger
        self._deps_factory = deps_factory or make_cli_deps

    # START_CONTRACT: queue_submit_task_async
    #   PURPOSE: Submit a new task asynchronously via the deps_factory seam (CLIDeps.submit).
    #   INPUTS: { label: str, metadata: Mapping[str, Any], engine_name: str, webhook_onsubmit: bool }
    #   OUTPUTS: { int - task_id }
    #   SIDE_EFFECTS: Creates a new task in the database via submit_task use case.
    #   LINKS: M-ENTRYPOINTS-CLIENT, M-DI
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
        # deps.submit (-> TaskId) → extract .value so the public contract stays int.
        return (await deps.submit(label, dict(metadata), engine_name)).value

    # START_CONTRACT: queue_submit_task
    #   PURPOSE: Submit a new task synchronously
    #   INPUTS: { label: str, metadata: Mapping[str, Any], engine_name: str, webhook_onsubmit: bool }
    #   OUTPUTS: { int - task_id }
    #   SIDE_EFFECTS: Creates a new task in the database
    #   LINKS: M-ENTRYPOINTS-CLIENT
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
    #   OUTPUTS: { Sequence[Mapping[str, Any]] - list of task dicts with 5 keys each (task_id, label, status, metadata, node) }
    #   SIDE_EFFECTS: Opens a UoW (DB connection) per call via deps_factory; reads task records and batch-loads allocated nodes
    #   RAISES: ValueError - if both jobs and statuses are non-empty (mutual exclusivity)
    #   LINKS: M-ENTRYPOINTS-CLIENT, M-APPLICATION-QUERY-TASKS, M-DI
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
        # The facade is the sole int/TaskId boundary: wrap job ints → TaskId
        # before crossing into the use case (public jobs: list[int] preserved).
        job_ids: Optional[list[TaskId]] = [TaskId(i) for i in jobs] if jobs else None
        deps = self._deps_factory(self.config)
        tasks, nodes_by_id = await query_tasks(job_ids, statuses, deps.uow_factory)
        return [_task_to_dict(t, nodes_by_id) for t in tasks]

    # START_CONTRACT: queue_get_tasks
    #   PURPOSE: Query tasks synchronously by job IDs or statuses
    #   INPUTS: { jobs: Optional[Sequence[int]], status: Optional[Sequence[int]] }
    #   OUTPUTS: { Sequence[Mapping[str, Any]] }
    #   SIDE_EFFECTS: Opens a UoW via async delegate
    #   LINKS: M-ENTRYPOINTS-CLIENT, M-APPLICATION-QUERY-TASKS
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
    #   LINKS: M-ENTRYPOINTS-CLIENT, M-APPLICATION-QUERY-TASKS
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
    #   LINKS: M-ENTRYPOINTS-CLIENT, M-APPLICATION-QUERY-TASKS
    # END_CONTRACT: queue_get_task
    def queue_get_task(self, task_id: int) -> Optional[Mapping[str, Any]]:
        """Get task by id"""
        for task_dict in self.queue_get_tasks(jobs=[task_id]):
            return task_dict
