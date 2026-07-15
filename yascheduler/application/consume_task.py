# FILE: yascheduler/application/consume_task.py
# VERSION: 6.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Consume task use case — download outputs from a remote machine and finalise or defer the task.
#   SCOPE: Task consumption / finalisation lifecycle — download outputs, finalise (DONE) or defer (retry).
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-ENGINE, M-DOMAIN-MODEL, M-SSH-OPS-DOWNLOAD, M-APPLICATION-ALLOCATION-TRACKER, M-DOMAIN-EVENTS
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER, M-SSH-OPS-DOWNLOAD, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   consume_task - Load task, download outputs, finalise (DONE) or defer (stay RUNNING)
#   _prepare_store_folder - Create local output directory from typed Task fields
#   _format_download_error - Format combined download errors into error string
#   _finalize_task - Apply domain lifecycle, save via UoW, discard tracker slot; returns True
#   _decide_finalisation - Decide finalise vs defer from (transient_errors, permanent_errors)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v6.3.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v6.2.0 - _decide_finalisation uses atomic Task transitions: task.fail(reason, local_folder=, remote_folder=) and task.complete(local_folder=, remote_folder=) set folders and emit TaskFailed/TaskCompleted inline. Removed with_download_results + with_event chain and the has_errors=False argument. Removed TaskCompleted/TaskFailed imports (no longer constructed here).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.domain import (
        EngineRepository,
        MachineSession,
        Task,
        TaskId,
    )
    from yascheduler.infra import OutputDownloader

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: _prepare_store_folder
#   PURPOSE: Create local output directory for task file downloads.
#   INPUTS: {
#     task: Task - Domain task with typed fields (remote_folder, engine, local_folder),
#     local_tasks_dir: Path - Local base directory for output storage,
#     engines: EngineRepository - Config engine repository
#   }
#   OUTPUTS: { tuple[Path, list[str], str] - (store_folder, output_files, remote_folder) }
#   SIDE_EFFECTS: Creates directory on local filesystem. Raises AssertionError when task.remote_folder is None (RUNNING-task precondition); uncaught locally, propagates to the orchestrator consumer worker's `except Exception`.
#   LINKS: none
# END_CONTRACT: _prepare_store_folder
async def _prepare_store_folder(
    task: Task,
    local_tasks_dir: Path,
    engines: EngineRepository,
) -> tuple[Path, list[str], str]:
    # START_BLOCK_CREATE_DIR
    assert task.remote_folder is not None  # task is RUNNING here
    remote_folder: str = task.remote_folder
    engine = engines[task.engine]
    output_files = [str(PurePosixPath(remote_folder) / x) for x in engine.output_files]
    local_folder = task.local_folder
    if local_folder:
        store_folder = Path(local_folder)
    else:
        store_folder = local_tasks_dir / Path(remote_folder).name
    await asyncio.get_running_loop().run_in_executor(
        None, store_folder.mkdir, 0o777, True, True
    )
    # END_BLOCK_CREATE_DIR
    return store_folder, output_files, remote_folder


def _format_download_error(
    combined_errors: list[tuple[str | None, Exception]],
) -> str:
    parts: list[str] = []
    for path, err in combined_errors:
        msg = str(err)
        parts.append(f"{path}: {msg}" if path is not None else msg)
    return "Download error: " + ", ".join(parts)


# START_CONTRACT: _decide_finalisation
#   PURPOSE: Decide finalise vs defer from and apply the terminal transition. Finalise when permanent_errors non-empty OR transient_errors
#     empty (full success, permanent-only, or mixed). Defer (return None) when transient-only.
#   INPUTS: {
#     task: Task - Domain task to finalise or defer,
#     local_folder: str - Downloaded local folder (download_outputs return),
#     remote_folder: str - Remote folder downloaded from (download_outputs return),
#     transient_errors: list[tuple[str | None, Exception]] - Retryable download errors,
#     permanent_errors: list[tuple[str | None, Exception]] - Non-retryable download errors,
#     store_folder: Path - Local directory where outputs were saved
#   }
#   OUTPUTS: { Task | None - task with status applied and event recorded when finalising; None when deferring }
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
# END_CONTRACT: _decide_finalisation
def _decide_finalisation(
    task: Task,
    local_folder: str,
    remote_folder: str,
    transient_errors: list[tuple[str | None, Exception]],
    permanent_errors: list[tuple[str | None, Exception]],
    store_folder: Path,
) -> Task | None:
    # START_BLOCK_DECIDE
    # Defer when transient-only: leave RUNNING, no status change, no event.
    if transient_errors and not permanent_errors:
        return None
    # END_BLOCK_DECIDE

    # START_BLOCK_FINALISE
    # Finalise on success or any permanent error. When both lists are
    # non-empty, permanent takes priority and the task fails with a combined
    # message including both. The terminal transitions set the folders AND
    # emit the matching event inline.
    combined_errors = permanent_errors + transient_errors
    final_local_folder = local_folder or task.local_folder or ""
    final_remote_folder = remote_folder or task.remote_folder or ""

    if combined_errors:
        error_msg = _format_download_error(combined_errors)
        task = task.fail(
            error_msg,
            local_folder=final_local_folder,
            remote_folder=final_remote_folder,
        )
    else:
        task = task.complete(
            local_folder=str(store_folder),
            remote_folder=final_remote_folder,
        )
    # END_BLOCK_FINALISE
    return task


# START_CONTRACT: _finalize_task
#   PURPOSE: On finalise: apply domain lifecycle (complete/fail), save via UoW, record events,
#     discard in-flight allocation slot. On defer: no side effects.
#   INPUTS: {
#     task: Task - Domain task to finalise,
#     local_folder: str - Downloaded local folder (download_outputs return),
#     remote_folder: str - Remote folder downloaded from (download_outputs return),
#     transient_errors: list[tuple[str | None, Exception]] - Retryable download errors,
#     permanent_errors: list[tuple[str | None, Exception]] - Non-retryable download errors,
#     store_folder: Path - Local directory where outputs were saved,
#     uow_factory: Callable - Factory providing AbstractUnitOfWork,
#     tracker: AllocationTracker - In-flight allocation tracker
#   }
#   OUTPUTS: { bool - True when finalised (DONE applied, tracker slot discarded); False when deferred (no side effects) }
#   SIDE_EFFECTS: On finalise: applies domain lifecycle, saves task via UoW, records TaskCompleted or
#     TaskFailed event, discards in-flight allocation slot via tracker. On defer: none.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: _finalize_task
async def _finalize_task(
    task: Task,
    local_folder: str,
    remote_folder: str,
    transient_errors: list[tuple[str | None, Exception]],
    permanent_errors: list[tuple[str | None, Exception]],
    store_folder: Path,
    uow_factory: Callable[[], AbstractUnitOfWork],
    tracker: AllocationTracker,
) -> bool:
    # START_BLOCK_DECIDE_OR_DEFER
    finalised_task = _decide_finalisation(
        task,
        local_folder,
        remote_folder,
        transient_errors,
        permanent_errors,
        store_folder,
    )
    if finalised_task is None:
        # Defer: transient-only — stay RUNNING, no save, no event, no discard.
        logger.info(
            "task_id=%s download deferred (transient errors), staying RUNNING for retry",
            task.task_id,
        )
        return False
    # END_BLOCK_DECIDE_OR_DEFER

    # START_BLOCK_SET_STATUS
    async with uow_factory() as uow:
        await uow.tasks.save(finalised_task)
        await uow.commit()

    logger.info(
        "task_id=%s %s done and saved in %s",
        finalised_task.task_id,
        finalised_task.label,
        store_folder,
    )

    tracker.discard(finalised_task.task_id)
    # END_BLOCK_SET_STATUS
    return True


# START_CONTRACT: consume_task
#   PURPOSE: Load task by id via UoW, download outputs from remote machine, finalise or defer.
#   INPUTS: {
#     task_id: TaskId - ID of the task to consume,
#     session: MachineSession - Session of the machine where the task ran,
#     output_downloader: OutputDownloader - SSH operations for output download,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable - Factory providing AbstractUnitOfWork,
#     local_tasks_dir: Path - Local base directory for output storage,
#     tracker: AllocationTracker - In-flight allocation tracker
#   }
#   OUTPUTS: { bool - True when finalised (DONE applied, remote dir cleaned by gateway, tracker slot discarded) or task not found in DB (vacuously finalised, tracker slot discarded); False when deferred (stay RUNNING, remote dir preserved, tracker slot retained) }
#   SIDE_EFFECTS: Downloads files via SFTP; on finalise applies domain lifecycle, saves via UoW, records events, discards tracker slot; on task-not-found discards tracker slot; on defer none.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-EVENTS, M-SSH-OPS-DOWNLOAD, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: consume_task
async def consume_task(
    task_id: TaskId,
    session: MachineSession,
    output_downloader: OutputDownloader,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    local_tasks_dir: Path,
    tracker: AllocationTracker,
) -> bool:
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
    if task is None:
        logger.warning("task_id=%s not found, skipping consume", task_id)
        # Discard the tracker slot so a missing task row can't leak an
        # in-flight allocation slot forever (treat as vacuously finalised).
        tracker.discard(task_id)
        return True

    store_folder, output_files, task_remote_folder = await _prepare_store_folder(
        task, local_tasks_dir, engines
    )
    (
        local_folder,
        remote_folder,
        transient_errors,
        permanent_errors,
    ) = await output_downloader.download_outputs(
        session=session,
        remote_dir=task_remote_folder,
        local_dir=store_folder,
        files=output_files,
        task_id=task.task_id,
    )
    return await _finalize_task(
        task,
        local_folder,
        remote_folder,
        transient_errors,
        permanent_errors,
        store_folder,
        uow_factory,
        tracker,
    )
