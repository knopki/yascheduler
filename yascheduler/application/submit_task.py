"""Register a new task in TO_DO state after validation."""
# FILE: yascheduler/application/submit_task.py
# VERSION: 1.8.0
# START_MODULE_CONTRACT
#   PURPOSE: Register a new task in TO_DO state after validation.
#   SCOPE: Task submission use case — validation, NewTask construction, persistence via UoW.
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-DOMAIN-EXCEPTIONS, M-DOMAIN-ENGINE, M-APPLICATION-UOW
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-UOW, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit_task - Create a new TO_DO task after validating engine and inputs; returns TaskId
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.8.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v1.7.0 - Remove remote_tasks_dir param.  Remove with_remote_folder + with_event(TaskCreated) chain; insert now returns a Task with TaskCreated in events (attached by materialize_task). submit_task no longer constructs DomainEvent subclasses.
# END_CHANGE_SUMMARY

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

    from yascheduler.domain import EngineRepository, Task

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)

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


# START_CONTRACT: submit_task
#   PURPOSE: Create a new TO_DO task after validating engine and inputs.
#   INPUTS: {
#     label: str - Task label,
#     metadata: Mapping[str, Any] - Raw input file data and parameters,
#     engine_name: str - Engine to use,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory for DB access
#   }
#   OUTPUTS: { TaskId - The generated task_id (the public Yascheduler.queue_submit_task facade extracts .value to keep the public -> int contract) }
#   SIDE_EFFECTS: Inserts a task row in the database via UoW (NewTask→Task conversion in insert, which attaches TaskCreated via materialize_task). TaskCreated event dispatched on commit.
#   RAISES: UnsupportedEngineError, MissingInputFileError
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: submit_task
async def submit_task(
    label: str,
    metadata: Mapping[str, Any],
    engine_name: str,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> TaskId:
    """Create a new TO_DO task after validating engine and inputs."""
    # START_BLOCK_VALIDATE
    if engine_name not in engines:
        raise UnsupportedEngineError(engine_name)
    engine = engines[engine_name]
    for input_file in engine.input_files:
        if input_file not in metadata:
            raise MissingInputFileError(engine_name, input_file)
    # END_BLOCK_VALIDATE

    # START_BLOCK_CREATE_TASK
    extra = {k: v for k, v in metadata.items() if k not in _KNOWN_TYPED_KEYS}
    new_task = NewTask(
        label=label,
        engine=engine_name,
        local_folder=metadata.get("local_folder"),
        webhook_url=metadata.get("webhook_url"),
        webhook_custom_params=metadata.get("webhook_custom_params", {}),
        extra=extra,
    )
    # END_BLOCK_CREATE_TASK

    # START_BLOCK_PERSIST
    async with uow_factory() as uow:
        task: Task = await uow.tasks.insert(new_task)
        await uow.tasks.save(task)
        await uow.commit()
    # END_BLOCK_PERSIST

    logger.info("submitted: %s", label)
    return task.task_id
