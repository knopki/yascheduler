# FILE: yascheduler/application/submit_task.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: Submit task use case — validates inputs, creates a domain NewTask, persists via UoW and returns the generated TaskId.
#   SCOPE: submit_task async function.
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-DOMAIN-EXCEPTIONS, M-DOMAIN-ENGINE, M-APPLICATION-UOW
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-UOW, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit_task - Create a new TO_DO task after validating engine and inputs; returns TaskId
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - submit_task return type int -> TaskId; constructs NewTask(label, context) (pre-persistence shape, no task_id=0 sentinel) and persists via uow.tasks.insert (sole NewTask→Task conversion). The task_id=0 fiction is gone (add-task-id-identity).
#   PREVIOUS_CHANGE: v1.4.0 - TYPE_CHECKING import EngineRepository from yascheduler.domain instead of yascheduler.config (engine-to-domain-frozen).
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from yascheduler.domain import (
    MissingInputFileError,
    NewTask,
    TaskContext,
    TaskCreated,
    TaskId,
    UnsupportedEngineError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import PurePath

    from yascheduler.domain import EngineRepository, Task

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
#   OUTPUTS: { TaskId - The generated task_id (the public Yascheduler.queue_submit_task facade extracts .value to keep the public -> int contract) }
#   SIDE_EFFECTS: Inserts a task row in the database via UoW (NewTask→Task conversion in insert). Records TaskCreated event dispatched on commit.
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
) -> TaskId:
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
    new_task = NewTask(label=label, context=context)
    # END_BLOCK_CREATE_TASK

    # START_BLOCK_PERSIST
    async with uow_factory() as uow:
        task: Task = await uow.tasks.insert(new_task)
        dt_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_folder = str(remote_tasks_dir / f"{dt_str}_{task.task_id}")
        context = task.context.replace(remote_folder=remote_folder)
        task = task.with_context(context).with_event(
            TaskCreated, engine_name=task.context.engine
        )
        await uow.tasks.save(task)
        await uow.commit()
    # END_BLOCK_PERSIST

    logger.info("submitted: %s", label)
    return task.task_id
