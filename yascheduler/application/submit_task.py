# FILE: yascheduler/application/submit_task.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Submit task use case — validates inputs, creates a domain Task, persists via UoW.
#   SCOPE: submit_task async function.
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-DOMAIN-EXCEPTIONS, M-CONFIG, M-APPLICATION-UOW
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit_task - Create a new TO_DO task after validating engine and inputs
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Record TaskCreated event on task submission.
#   PREVIOUS_CHANGE: v1.0.0 - Extract submit_task use case from scheduler.create_new_task.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from yascheduler.domain import (
    MissingInputFileError,
    Task,
    TaskContext,
    TaskCreated,
    TaskStatus,
    UnsupportedEngineError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import PurePath

    from yascheduler.config import EngineRepository

    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: submit_task
#   PURPOSE: Create a new TO_DO task after validating engine and inputs.
#   INPUTS: {
#     label: str - Task label,
#     metadata: Mapping[str, Any] - Raw input file data and parameters,
#     engine_name: str - Engine to use,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable[[], AbstractUnitOfWork] - UoW factory for DB access,
#     remote_tasks_dir: PurePosixPath - Remote base directory for task folders
#   }
#   OUTPUTS: { int - The generated task_id }
#   SIDE_EFFECTS: Inserts a task row in the database via UoW. Records TaskCreated event dispatched on commit.
#   RAISES: UnsupportedEngineError, MissingInputFileError
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: submit_task
async def submit_task(
    label: str,
    metadata: Mapping[str, Any],
    engine_name: str,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    remote_tasks_dir: PurePath,
) -> int:
    # START_BLOCK_VALIDATE
    if engine_name not in engines:
        raise UnsupportedEngineError(engine_name)
    engine = engines[engine_name]
    for input_file in engine.input_files:
        if input_file not in metadata:
            raise MissingInputFileError(engine_name, input_file)
    # END_BLOCK_VALIDATE

    # START_BLOCK_CREATE_TASK
    full_meta = dict(metadata)
    full_meta["engine"] = engine_name
    context = TaskContext.from_metadata(full_meta)
    task = Task(task_id=0, label=label, context=context, status=TaskStatus.TO_DO)
    # END_BLOCK_CREATE_TASK

    # START_BLOCK_PERSIST
    async with uow_factory() as uow:
        task = await uow.tasks.insert(task)
        dt_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_folder = str(remote_tasks_dir / f"{dt_str}_{task.task_id}")
        context = replace(task.context, remote_folder=remote_folder)
        task = replace(task, context=context)
        task = task.record_event(
            TaskCreated(
                task_id=task.task_id,
                webhook_url=task.context.webhook_url,
                webhook_custom_params=task.context.webhook_custom_params,
                engine_name=task.context.engine,
            )
        )
        await uow.tasks.save(task)
        await uow.commit()
    # END_BLOCK_PERSIST

    logger.info("submitted: %s", label)
    return task.task_id
