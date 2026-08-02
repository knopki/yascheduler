"""Register a new task in TO_DO state after validation."""
# region MODULE_CONTRACT
# PURPOSE: Accept validated task requests from clients and persist them so the daemon's allocator can pick them up for scheduling.
# SCOPE: Task submission use case — engine validation, input file validation, NewTask construction, persistence via UoW.
# KEYWORDS: submit, create, task, validation, engine, input files
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from yascheduler.domain import (
    MissingInputFileError,
    NewTask,
    TaskId,
    UnsupportedEngineError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from yascheduler.domain import EngineRepository, TodoTask

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)

__all__ = ["submit_task"]

_KNOWN_TYPED_KEYS = frozenset(
    {
        "engine",
        "remote_folder",
        "local_folder",
        "webhook_url",
        "webhook_custom_params",
        "error",
    },
)


# region FUNC_submit_task
# PURPOSE: Validate engine and input files, construct a NewTask, persist via UoW, and return the generated TaskId.
# REQUIRES: engine_name is configured in engines; every input_file of the engine is present in metadata.
# ENSURES: Returns a valid TaskId > 0; the task row is committed with status TO_DO.
async def submit_task(
    label: str,
    metadata: Mapping[str, Any],
    engine_name: str,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> TaskId:
    """Create a new TO_DO task after validating engine and inputs."""
    # region BLOCK_validate
    if engine_name not in engines:
        raise UnsupportedEngineError(engine_name)
    engine = engines[engine_name]
    for input_file in engine.input_files:
        if input_file not in metadata:
            raise MissingInputFileError(engine_name, input_file)
    # endregion BLOCK_validate

    # region BLOCK_create_task
    extra = {k: v for k, v in metadata.items() if k not in _KNOWN_TYPED_KEYS}
    new_task = NewTask(
        label=label,
        engine=engine_name,
        local_folder=metadata.get("local_folder"),
        webhook_url=metadata.get("webhook_url"),
        webhook_custom_params=metadata.get("webhook_custom_params", {}),
        extra=extra,
    )
    # endregion BLOCK_create_task

    # region BLOCK_persist
    async with uow_factory() as uow:
        task: TodoTask = await uow.tasks.insert(new_task)
        await uow.tasks.save(task)
        await uow.commit()
    # endregion BLOCK_persist

    logger.info("submitted: %s", label)
    return task.task_id


# endregion FUNC_submit_task
