# FILE: yascheduler/application/consume_task.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Consume task use case — download outputs from a remote machine and mark task DONE.
#   SCOPE: consume_task async function.
#   DEPENDS: M-APPLICATION-UOW, M-REMOTE-REPO, M-CLOUD-MANAGER, M-CONFIG
#   LINKS: M-APPLICATION-UOW, M-SCHEDULER, M-CLOUD-MANAGER, M-REMOTE-REPO
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   consume_task - Load task via UoW, download outputs, mark DONE or ERROR
#   _prepare_store_folder - Create local output directory from domain Task context
#   _sftp_download_job - Open SFTP session, download files, clean remote dir
#   _download_task_outputs - Download output files via SFTP with retry
#   _finalize_task - Apply domain lifecycle, save via UoW, send webhook, notify cloud manager
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Rewrite to use UoW + domain Task instead of DB + TaskModel
#   PREVIOUS_CHANGE: v1.2.0 - Extract _sftp_download_job from _download_task_outputs for func-size compliance.
#   PREVIOUS_CHANGE: v1.1.0 - Extract three private helpers from consume_task for size compliance.
#   PREVIOUS_CHANGE: v1.0.0 - Extract consume_task use case from scheduler.consume_task.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import backoff
from asyncssh.sftp import SFTPError

from yascheduler.domain.model import Task, TaskStatus
from yascheduler.remote_machine import RemoteMachine, SFTPRetryExc

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from yascheduler.adapters.cloud.manager import CloudProvisionerImpl
    from yascheduler.application.uow import AbstractUnitOfWork
    from yascheduler.config import EngineRepository

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


# START_CONTRACT: _sftp_download_job
#   PURPOSE: Open SFTP session, download all output files, clean remote directory.
#   INPUTS: {
#     machine: RemoteMachine - Target machine,
#     output_files: list[str] - Remote file paths to download,
#     store_folder: Path - Local download destination,
#     remote_folder: str - Remote directory to clean,
#     task: Task - Completed task (for logging)
#   }
#   OUTPUTS: { list[tuple[str | None, Exception]] - Download errors }
#   SIDE_EFFECTS: Downloads files via SFTP, removes remote directory tree.
#   LINKS: M-REMOTE-REPO
# END_CONTRACT: _sftp_download_job
async def _sftp_download_job(
    machine: RemoteMachine,
    output_files: list[str],
    store_folder: Path,
    remote_folder: str,
    task: Task,
) -> list[tuple[str | None, Exception]]:
    errors: list[tuple[str | None, Exception]] = []
    file_get_retry = backoff.on_exception(backoff.fibo, SFTPRetryExc, max_time=60)
    async with machine.sftp() as sftp:
        for out_file in output_files:
            try:
                await file_get_retry(sftp.get)(out_file, store_folder, preserve=True)
            except (OSError, SFTPError) as err:
                errors.append((out_file, err))
                logger.warning(
                    "Cannot download file for task_id=%s from %s: %s",
                    task.task_id,
                    out_file,
                    err,
                )
        await sftp.rmtree(machine.path(remote_folder))
    return errors


# START_CONTRACT: _download_task_outputs
#   PURPOSE: Download output files from remote machine via SFTP with retry, then clean remote dir.
#   INPUTS: {
#     machine: RemoteMachine - The machine where the task ran,
#     output_files: list[str] - Remote file paths to download,
#     store_folder: Path - Local directory for downloaded files,
#     remote_folder: str - Remote directory to clean after download,
#     task: Task - The completed task (for logging)
#   }
#   OUTPUTS: { tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]] - (meta_add, sftp_errors) }
#   SIDE_EFFECTS: Downloads files via SFTP, removes remote directory tree.
#   LINKS: M-REMOTE-REPO
# END_CONTRACT: _download_task_outputs
async def _download_task_outputs(
    machine: RemoteMachine,
    output_files: list[str],
    store_folder: Path,
    remote_folder: str,
    task: Task,
) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]:
    # START_BLOCK_DOWNLOAD
    meta_add: list[tuple[str, Any]] = [
        ("remote_folder", remote_folder),
        ("local_folder", str(store_folder)),
    ]

    job_retry = backoff.on_exception(backoff.fibo, SFTPRetryExc, max_time=60)
    try:
        sftp_errors = await job_retry(_sftp_download_job)(
            machine, output_files, store_folder, remote_folder, task
        )
    except Exception as err:
        logger.warning("Cannot scp from %s: %s", remote_folder, err)
        sftp_errors = [(remote_folder, err)]
    # END_BLOCK_DOWNLOAD

    return meta_add, sftp_errors


# START_CONTRACT: _finalize_task
#   PURPOSE: Apply domain lifecycle (complete/fail), save via UoW, send webhook, and notify cloud manager.
#   INPUTS: {
#     task: Task - Domain task to finalize,
#     meta_add: list[tuple[str, Any]] - Additional metadata to merge,
#     sftp_errors: list[tuple[str | None, Exception]] - SFTP download errors,
#     store_folder: Path - Local directory where outputs were saved,
#     uow_factory: Callable - Factory providing AbstractUnitOfWork,
#     do_task_webhook: Callable - Callback to send webhook notification,
#     clouds: CloudProvisionerImpl - Cloud provider manager
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Applies domain lifecycle, saves task via UoW, sends webhook, marks task done in cloud manager.
#   LINKS: M-APPLICATION-UOW, M-CLOUD-MANAGER
# END_CONTRACT: _finalize_task
async def _finalize_task(
    task: Task,
    meta_add: list[tuple[str, Any]],
    sftp_errors: list[tuple[str | None, Exception]],
    store_folder: Path,
    uow_factory: Callable[[], AbstractUnitOfWork],
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
    clouds: CloudProvisionerImpl,
) -> None:
    # START_BLOCK_SET_STATUS
    if sftp_errors:
        meta_add.append(("error", {p: str(e) for p, e in sftp_errors}))

    new_meta = task.context.to_metadata()
    new_meta.update(dict(meta_add))

    # Update task context so that save() persists download paths and extras
    meta_dict = dict(meta_add)
    extra_updates = {
        k: v
        for k, v in meta_dict.items()
        if k not in ("remote_folder", "local_folder", "error")
    }
    updated_context = replace(
        task.context,
        local_folder=meta_dict.get("local_folder") or task.context.local_folder,
        remote_folder=meta_dict.get("remote_folder") or task.context.remote_folder,
        extra={**task.context.extra, **extra_updates},
    )

    if sftp_errors:
        error_msg = str({p: str(e) for p, e in sftp_errors})
        updated_context = replace(updated_context, error=error_msg)
        task = replace(task, context=updated_context).fail(error_msg)
    else:
        task = replace(task, context=updated_context).complete()

    await do_task_webhook(task.task_id, new_meta, TaskStatus.DONE)

    async with uow_factory() as uow:
        await uow.tasks.save(task)
        await uow.commit()

    logger.info(
        "task_id=%s %s done and saved in %s", task.task_id, task.label, store_folder
    )

    clouds.mark_task_done(task.task_id)
    # END_BLOCK_SET_STATUS


# START_CONTRACT: consume_task
#   PURPOSE: Load task by id via UoW, download outputs from remote machine, apply domain lifecycle.
#   INPUTS: {
#     task_id: int - ID of the task to consume,
#     machine: RemoteMachine - The machine where the task ran,
#     engines: EngineRepository - Config engine repository,
#     uow_factory: Callable - Factory providing AbstractUnitOfWork,
#     local_tasks_dir: Path - Local base directory for output storage,
#     clouds: CloudProvisionerImpl - Cloud provider manager,
#     do_task_webhook: Callable - Callback to send webhook notification
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Downloads files via SFTP, applies domain lifecycle, saves via UoW, sends webhook.
#   LINKS: M-APPLICATION-UOW, M-REMOTE-REPO, M-CLOUD-MANAGER
# END_CONTRACT: consume_task
async def consume_task(
    task_id: int,
    machine: RemoteMachine,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    local_tasks_dir: Path,
    clouds: CloudProvisionerImpl,
    do_task_webhook: Callable[[int, Mapping[str, Any], TaskStatus], Awaitable[None]],
) -> None:
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
    if task is None:
        logger.warning("task_id=%s not found, skipping consume", task_id)
        return

    store_folder, output_files, remote_folder = await _prepare_store_folder(
        task, local_tasks_dir, engines
    )
    meta_add, sftp_errors = await _download_task_outputs(
        machine, output_files, store_folder, remote_folder, task
    )
    await _finalize_task(
        task, meta_add, sftp_errors, store_folder, uow_factory, do_task_webhook, clouds
    )
