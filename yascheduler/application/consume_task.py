# FILE: yascheduler/application/consume_task.py
# VERSION: 5.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Consume task use case — download outputs from a remote machine and finalise or defer the task.
#   SCOPE: consume_task async function returning bool (True=finalised, False=deferred for retry).
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-ENGINE, M-DOMAIN-MODEL, M-SSH-OPERATIONS, M-APPLICATION-ALLOCATION-TRACKER, M-DOMAIN-EVENTS
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER, M-SSH-OPERATIONS, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   consume_task - Load task via UoW, download outputs, finalise (DONE/DONE+error) or defer (stay RUNNING); returns bool
#   _prepare_store_folder - Create local output directory from domain Task context
#   _finalize_task - On finalise: apply domain lifecycle, save via UoW, record events, discard tracker slot; returns True. On defer: no side effects, returns False
#   _decide_finalisation - Decide finalise vs defer from (transient_errors, permanent_errors) and apply domain status + event when finalising
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v5.7.0 - session-based-machine-handle: consume_task takes session: MachineSession instead of ip: str; delegates session to operations.download_outputs(session=session).
#   PREVIOUS_CHANGE: v5.5.0 - consume_task returns bool (True=finalised, False=deferred for retry); unpacks 3-tuple (meta_add, transient_errors, permanent_errors) from gateway.download_outputs; transient-only errors defer (no status change, no save, no event, no tracker.discard) so the orchestrator re-consumes the RUNNING task; permanent errors or full success finalise (task.fail with combined msg when both lists present, or task.complete); tracker.discard moved into finalise branch only (fix-download-rmtree-data-loss). Renamed _record_finalization_event -> _decide_finalisation.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from yascheduler.domain import TaskCompleted, TaskFailed

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.domain import (
        EngineRepository,
        MachineOperations,
        MachineSession,
        Task,
    )

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork

logger = logging.getLogger(__name__)


# START_CONTRACT: _prepare_store_folder
#   PURPOSE: Create local output directory for task file downloads.
#   INPUTS: {
#     task: Task - Domain task with context containing paths and engine name,
#     local_tasks_dir: Path - Local base directory for output storage,
#     engines: EngineRepository - Config engine repository
#   }
#   OUTPUTS: { tuple[Path, list[str], str] - (store_folder, output_files, remote_folder) }
#   SIDE_EFFECTS: Creates directory on local filesystem.
#   LINKS: none
# END_CONTRACT: _prepare_store_folder
async def _prepare_store_folder(
    task: Task,
    local_tasks_dir: Path,
    engines: EngineRepository,
) -> tuple[Path, list[str], str]:
    # START_BLOCK_CREATE_DIR
    remote_folder: str = task.context.remote_folder  # type: ignore[assignment]
    engine = engines[task.context.engine]
    output_files = [str(PurePosixPath(remote_folder) / x) for x in engine.output_files]
    local_folder: str | None = task.context.local_folder
    if local_folder:
        store_folder = Path(local_folder)
    else:
        store_folder = local_tasks_dir / Path(remote_folder).name
    await asyncio.get_running_loop().run_in_executor(
        None, store_folder.mkdir, 0o777, True, True
    )
    # END_BLOCK_CREATE_DIR
    return store_folder, output_files, remote_folder


# START_CONTRACT: _decide_finalisation
#   PURPOSE: Decide finalise vs defer from (transient_errors, permanent_errors) and apply domain
#     status + event when finalising. Finalise when permanent_errors non-empty OR transient_errors
#     empty (full success, permanent-only, or mixed). Defer (return None) when transient-only.
#   INPUTS: {
#     task: Task - Domain task to finalise or defer,
#     meta_add: list[tuple[str, Any]] - Additional metadata to merge,
#     transient_errors: list[tuple[str | None, Exception]] - Retryable download errors,
#     permanent_errors: list[tuple[str | None, Exception]] - Non-retryable download errors,
#     store_folder: Path - Local directory where outputs were saved
#   }
#   OUTPUTS: { Task | None - task with status applied and event recorded when finalising; None when deferring }
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
# END_CONTRACT: _decide_finalisation
def _decide_finalisation(
    task: Task,
    meta_add: list[tuple[str, Any]],
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
    # message including both.
    combined_errors = permanent_errors + transient_errors
    if combined_errors:
        error_map = {p: str(e) for p, e in combined_errors}
        meta_add.append(("error", error_map))

    meta_dict = dict(meta_add)
    extra_updates = {
        k: v
        for k, v in meta_dict.items()
        if k not in ("remote_folder", "local_folder", "error")
    }
    updated_context = task.context.replace(
        local_folder=meta_dict.get("local_folder") or task.context.local_folder,
        remote_folder=meta_dict.get("remote_folder") or task.context.remote_folder,
        extra={**task.context.extra, **extra_updates},
    )

    if combined_errors:
        error_msg = str(error_map)
        task = (
            task.with_context(updated_context)
            .fail(error_msg)
            .with_event(TaskFailed, reason=error_msg)
        )
    else:
        task = (
            task.with_context(updated_context)
            .complete()
            .with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)
        )
    # END_BLOCK_FINALISE
    return task


# START_CONTRACT: _finalize_task
#   PURPOSE: On finalise: apply domain lifecycle (complete/fail), save via UoW, record events,
#     discard in-flight allocation slot. On defer: no side effects.
#   INPUTS: {
#     task: Task - Domain task to finalise,
#     meta_add: list[tuple[str, Any]] - Additional metadata to merge,
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
    meta_add: list[tuple[str, Any]],
    transient_errors: list[tuple[str | None, Exception]],
    permanent_errors: list[tuple[str | None, Exception]],
    store_folder: Path,
    uow_factory: Callable[[], AbstractUnitOfWork],
    tracker: AllocationTracker,
) -> bool:
    # START_BLOCK_DECIDE_OR_DEFER
    finalised_task = _decide_finalisation(
        task, meta_add, transient_errors, permanent_errors, store_folder
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
#     task_id: int - ID of the task to consume,
#     session: MachineSession - Session of the machine where the task ran,
#     operations: MachineOperations - SSH operations for output download,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable - Factory providing AbstractUnitOfWork,
#     local_tasks_dir: Path - Local base directory for output storage,
#     tracker: AllocationTracker - In-flight allocation tracker
#   }
#   OUTPUTS: { bool - True when finalised (DONE applied, remote dir cleaned by gateway, tracker slot discarded) or task not found in DB (vacuously finalised, tracker slot discarded); False when deferred (stay RUNNING, remote dir preserved, tracker slot retained) }
#   SIDE_EFFECTS: Downloads files via SFTP; on finalise applies domain lifecycle, saves via UoW, records events, discards tracker slot; on task-not-found discards tracker slot; on defer none.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-EVENTS, M-SSH-OPERATIONS, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: consume_task
async def consume_task(
    task_id: int,
    session: MachineSession,
    operations: MachineOperations,
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

    store_folder, output_files, remote_folder = await _prepare_store_folder(
        task, local_tasks_dir, engines
    )
    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
        session=session,
        remote_dir=remote_folder,
        local_dir=store_folder,
        files=output_files,
        task_id=task.task_id,
    )
    return await _finalize_task(
        task,
        meta_add,
        transient_errors,
        permanent_errors,
        store_folder,
        uow_factory,
        tracker,
    )
