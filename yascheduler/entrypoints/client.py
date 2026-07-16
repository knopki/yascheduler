"""Yascheduler client."""
# region MODULE_CONTRACT
# PURPOSE: Provide the public Python/CLI client (Yascheduler) for submitting and querying tasks, bridging sync callers to the async use-case layer via to_sync adapter.
# SCOPE: Yascheduler sync/async client class, to_sync adapter, _task_to_dict projection.
# KEYWORDS: client, facade, task, submit, query, sync, async
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from yascheduler.application import query_tasks
from yascheduler.domain import Node, NodeId, Task, TaskId, TaskStatus
from yascheduler.entrypoints.config_parser import parse_config

from .di import CLIDeps, make_cli_deps
from .paths import CONFIG_FILE

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping, Sequence
    from pathlib import PurePath

    from yascheduler.entrypoints.config import Config

if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec
else:
    from typing import ParamSpec

ReturnT_co = TypeVar("ReturnT_co", covariant=True)
ParamT = ParamSpec("ParamT")

__all__ = [
    "Yascheduler",
]


# region FUNC_to_sync
# PURPOSE: Wrap an async function so it can be called synchronously, detecting a running event loop and offloading to a worker thread when necessary.
def to_sync(
    func: Callable[ParamT, Coroutine[Any, Any, ReturnT_co]],
) -> Callable[ParamT, ReturnT_co]:
    """Wrap async function and run it sync in thread."""

    @wraps(func)
    def outer(*args: ParamT.args, **kwargs: ParamT.kwargs) -> ReturnT_co:
        """Execute the async method synchronously in sync and async runtime."""
        coro = func(*args, **kwargs)
        try:
            asyncio.get_running_loop()  # Triggers RuntimeError if no running event loop

            # Create a separate thread so we can block before returning
            with ThreadPoolExecutor(1) as pool:
                return pool.submit(lambda: asyncio.run(coro)).result()
        except RuntimeError:
            return asyncio.run(coro)

    return outer


# endregion FUNC_to_sync


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
                "hostname": node.hostname,
                "port": node.port,
                "username": node.username,
                "cloud": node.cloud,
                "jump_host": node.jump_host,
                "jump_port": node.jump_port,
                "jump_username": node.jump_username,
                "external_id": node.external_id,
                "status": node.status.name,
                "created_at": node.created_at.isoformat(),
                "updated_at": node.updated_at.isoformat(),
            }
            if node is not None
            else None
        ),
    }


class Yascheduler:
    """Yascheduler client."""

    STATUS_TO_DO = TaskStatus.TO_DO.value
    STATUS_RUNNING = TaskStatus.RUNNING.value
    STATUS_DONE = TaskStatus.DONE.value

    config: Config

    # region METHOD___init__
    # PURPOSE: Initialize the Yascheduler client with config path and optional DI factory.
    def __init__(
        self,
        config_path: PurePath | str = CONFIG_FILE,
        *,
        deps_factory: Callable[[Config], CLIDeps] | None = None,
        **_: dict[str, Any],
    ) -> None:
        """Initialize the Yascheduler client with config path and optional DI factory."""
        self.config = parse_config(config_path)
        self._deps_factory = deps_factory or make_cli_deps

    # endregion METHOD___init__

    # region METHOD_queue_submit_task_async
    # PURPOSE: Submit a new task asynchronously via CLIDeps.submit, returning the task_id as an int.
    async def queue_submit_task_async(
        self,
        label: str,
        metadata: Mapping[str, Any],
        engine_name: str,
        *,
        _webhook_onsubmit: bool = False,
    ) -> int:
        """Submit new task."""
        deps = self._deps_factory(self.config)
        # deps.submit (-> TaskId) → extract .value so the public contract stays int.
        return (await deps.submit(label, dict(metadata), engine_name)).value

    # endregion METHOD_queue_submit_task_async

    # region METHOD_queue_submit_task
    # PURPOSE: Submit a new task synchronously via the async delegate wrapped with to_sync.
    def queue_submit_task(
        self,
        label: str,
        metadata: Mapping[str, Any],
        engine_name: str,
        *,
        webhook_onsubmit: bool = False,
    ) -> int:
        """Submit new task."""
        fn = to_sync(self.queue_submit_task_async)
        return fn(label, metadata, engine_name, _webhook_onsubmit=webhook_onsubmit)

    # endregion METHOD_queue_submit_task

    # region METHOD_queue_get_tasks_async
    # PURPOSE: Query tasks asynchronously by job IDs or statuses via the query_tasks use case.
    async def queue_get_tasks_async(
        self,
        jobs: Sequence[int] | None = None,
        status: Sequence[int] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Get tasks by ids or statuses."""
        # raise ValueError if unknown task status
        statuses: list[TaskStatus] | None = (
            [TaskStatus(x) for x in status] if status else None
        )
        # The facade is the sole int/TaskId boundary: wrap job ints → TaskId
        # before crossing into the use case (public jobs: list[int] preserved).
        job_ids: list[TaskId] | None = [TaskId(i) for i in jobs] if jobs else None
        deps = self._deps_factory(self.config)
        tasks, nodes_by_id = await query_tasks(job_ids, statuses, deps.uow_factory)
        return [_task_to_dict(t, nodes_by_id) for t in tasks]

    # endregion METHOD_queue_get_tasks_async

    # region METHOD_queue_get_tasks
    # PURPOSE: Query tasks synchronously by job IDs or statuses.
    def queue_get_tasks(
        self,
        jobs: Sequence[int] | None = None,
        status: Sequence[int] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Get tasks by ids or statuses."""
        return to_sync(self.queue_get_tasks_async)(jobs, status)

    # endregion METHOD_queue_get_tasks

    # region METHOD_queue_get_task_async
    # PURPOSE: Get a single task by ID asynchronously.
    async def queue_get_task_async(self, task_id: int) -> Mapping[str, Any] | None:
        """Get task by id."""
        for task_dict in await self.queue_get_tasks_async(jobs=[task_id]):
            return task_dict
        return None

    # endregion METHOD_queue_get_task_async

    # region METHOD_queue_get_task
    # PURPOSE: Get a single task by ID synchronously.
    def queue_get_task(self, task_id: int) -> Mapping[str, Any] | None:
        """Get task by id."""
        for task_dict in self.queue_get_tasks(jobs=[task_id]):
            return task_dict
        return None

    # endregion METHOD_queue_get_task
