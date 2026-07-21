"""Consume task use case — download outputs from a remote machine and finalise or defer the task."""
# region MODULE_CONTRACT
# PURPOSE: Reliably retrieve remote computation results and classify errors to either close the task lifecycle or retry, so transient infra failures do not prematurely terminate valid work.
# SCOPE: Task consumption lifecycle — output download via SFTP, transient/permanent error classification, finalise with domain transitions (complete/fail), persistence, tracker slot discard.
# KEYWORDS: consume, finalise, download, defer, retry, output, sftp
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from functools import partial
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

__all__ = ["consume_task"]


# region FUNC__prepare_store_folder
# PURPOSE: Ensure the local filesystem is ready to receive remote outputs and resolve what to fetch, so the download step has a target directory and file list.
# REQUIRES: task.remote_folder is not None (task is RUNNING).
async def _prepare_store_folder(
    task: Task,
    local_tasks_dir: Path,
    engines: EngineRepository,
) -> tuple[Path, list[str], str]:
    # region BLOCK_create_dir
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
        None,
        partial(store_folder.mkdir, 0o777, parents=True, exist_ok=True),
    )
    # endregion BLOCK_create_dir
    return store_folder, output_files, remote_folder


# endregion FUNC__prepare_store_folder


# region FUNC__format_download_error
# PURPOSE: Produce a single actionable error message from multiple per-file download failures so operators or clients can diagnose what went wrong.
def _format_download_error(
    combined_errors: list[tuple[str | None, Exception]],
) -> str:
    parts: list[str] = []
    for path, err in combined_errors:
        msg = str(err)
        parts.append(f"{path}: {msg}" if path is not None else msg)
    return "Download error: " + ", ".join(parts)


# endregion FUNC__format_download_error


# region FUNC__decide_finalisation
# PURPOSE: Decide whether to finalise (DONE) or defer (stay RUNNING) based on error types. Finalise when permanent errors exist or all succeeded; defer on transient-only.
# ENSURES: Returns None (defer) when transient-only; Task with complete/fail applied when finalising.
def _decide_finalisation(
    task: Task,
    local_folder: str,
    remote_folder: str,
    transient_errors: list[tuple[str | None, Exception]],
    permanent_errors: list[tuple[str | None, Exception]],
    store_folder: Path,
) -> Task | None:
    # region BLOCK_decide
    # Defer when transient-only: leave RUNNING, no status change, no event.
    if transient_errors and not permanent_errors:
        return None
    # endregion BLOCK_decide

    # region BLOCK_finalise
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
    # endregion BLOCK_finalise
    return task


# endregion FUNC__decide_finalisation


# region FUNC__finalize_task
# PURPOSE: On finalise: apply domain lifecycle (complete/fail), save via UoW, discard in-flight allocation slot. On defer: no side effects.
# ENSURES: Returns True when finalised (DONE, tracker slot discarded); False when deferred (no side effects).
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
    # region BLOCK_decide_or_defer
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
    # endregion BLOCK_decide_or_defer

    # region BLOCK_set_status
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
    # endregion BLOCK_set_status
    return True


# endregion FUNC__finalize_task


# region FUNC_consume_task
# PURPOSE: Load a RUNNING task, download its outputs from the remote machine, and finalise (DONE) or defer (stay RUNNING).
# ENSURES: Returns True when finalised (or task gone — vacuously finalised); False when deferred.
async def consume_task(
    task_id: TaskId,
    session: MachineSession,
    output_downloader: OutputDownloader,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    local_tasks_dir: Path,
    tracker: AllocationTracker,
) -> bool:
    """Load task by id via UoW, download outputs from remote machine, finalise or defer."""
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
    if task is None:
        logger.warning("task_id=%s not found, skipping consume", task_id)
        # Discard the tracker slot so a missing task row can't leak an
        # in-flight allocation slot forever (treat as vacuously finalised).
        tracker.discard(task_id)
        return True

    store_folder, output_files, task_remote_folder = await _prepare_store_folder(
        task,
        local_tasks_dir,
        engines,
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


# endregion FUNC_consume_task
