"""TaskDeployer — upload task inputs and spawn the calculation process on a remote machine via MachineSession. Stateless: takes (log) at construction, (session, ...) per call."""
# region MODULE_CONTRACT
# PURPOSE: Upload task inputs and spawn calculation process on a remote machine via MachineSession; rolls back BUSY on failure.
# SCOPE: TaskDeployer class, _safe_b64decode and _write_remote_file module-private helpers.
# DEPENDENCIES: USES API: asyncssh (SFTPClient, SFTP errors)
# KEYWORDS: deploy, task, upload, spawn, TaskDeployer, sftp
# endregion MODULE_CONTRACT

from __future__ import annotations

import base64
import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import asyncssh

from yascheduler.domain import MachineState

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.sftp import SFTPClient

    from yascheduler.domain import Engine, MachineSession, Task

__all__ = ["TaskDeployer"]

logger = logging.getLogger(__name__)


# region FUNC__safe_b64decode
# PURPOSE: Decode base64 string with lenient padding handling.
# INVARIANTS: Lenient on padding — auto-appends = to satisfy len % 4 == 0; normalizes whitespace and newlines before decoding; accepts str or bytes input — bytes is decoded first.
def _safe_b64decode(b64_data: str | bytes) -> bytes:
    if isinstance(b64_data, bytes):
        b64_data = b64_data.decode()
    b64_data = b64_data.strip().replace("\n", "").replace(" ", "")
    missing_padding = len(b64_data) % 4
    if missing_padding:
        b64_data += "=" * (4 - missing_padding)
    return base64.b64decode(b64_data)


# endregion FUNC__safe_b64decode


# region FUNC__write_remote_file
# PURPOSE: Write data to a remote file via SFTP with error handling.
async def _write_remote_file(
    sftp: SFTPClient,
    path: str,
    data: bytes | str,
    mode: str = "wb",
) -> None:
    # region BLOCK_write_file
    try:
        async with sftp.open(path, mode) as f:
            await f.write(data)  # type: ignore[type-var]
    except asyncssh.misc.Error as err:
        logger.exception(
            "Write %s - SFTPError: %s (%s)",
            path,
            err.reason,
            err.code,
        )
        raise
    # endregion BLOCK_write_file


# endregion FUNC__write_remote_file


# region CLASS_TaskDeployer
# PURPOSE: Upload task inputs and spawn calculation process on a remote machine via MachineSession; rolls back BUSY on failure.
class TaskDeployer:
    """Upload task inputs and spawn the calculation process on a remote machine.

    Stateless: takes (log) at construction, (session, ...) per call. Rolls back
    the session BUSY marking under `except BaseException` on any deploy/spawn
    failure.
    """

    def __init__(self) -> None:
        """Stateless deployer — no initialisation needed."""

    # region METHOD__upload_task_data
    # PURPOSE: Upload task input files to remote machine via SFTP.
    async def _upload_task_data(
        self,
        session: MachineSession,
        task: Task,
        remote_dir: PurePath,
        input_files: Sequence[str],
    ) -> bool:

        # region BLOCK_upload
        async with session.open_sftp() as sftp:
            try:
                await sftp.makedirs(PurePosixPath(remote_dir), exist_ok=True)
            except asyncssh.misc.Error as err:
                logger.exception(
                    "Create %s - SFTPError: %s (%s) (task_id=%s)",
                    remote_dir,
                    err.reason,
                    err.code,
                    task.task_id,
                )
                raise

            for input_file in input_files:
                r_input_file = remote_dir / input_file
                file_data = task.extra[input_file]
                if input_file == "fort.9":
                    await _write_remote_file(
                        sftp,
                        r_input_file.as_posix(),
                        _safe_b64decode(str(file_data)),
                    )
                else:
                    await _write_remote_file(
                        sftp,
                        r_input_file.as_posix(),
                        str(file_data),
                        mode="w",
                    )
        return True
        # endregion BLOCK_upload

    # endregion METHOD__upload_task_data

    # region METHOD__exec_spawn_command
    # PURPOSE: Execute spawn command on remote machine via SSH.
    async def _exec_spawn_command(
        self,
        session: MachineSession,
        engine: Engine,
        task: Task,
        task_dir: PurePath,
        eng_path: PurePath,
        ncpus: int,
    ) -> None:
        # region BLOCK_spawn
        try:
            run_cmd = engine.spawn.format(
                engine_path=session.quote(str(eng_path)),
                task_path=session.quote(str(task_dir)),
                ncpus=ncpus,
            )
            logger.debug(
                "SPAWN",
                extra={
                    "hostname": session.hostname,
                    "task_id": task.task_id,
                    "cmd": run_cmd,
                    "cwd": str(task_dir),
                },
            )
            await session.run_bg(run_cmd, cwd=str(task_dir))
        except Exception:
            logger.exception("SSH spawn cmd error")
            raise
        # endregion BLOCK_spawn

    # endregion METHOD__exec_spawn_command

    # region METHOD_start_task_on_machine
    # PURPOSE: Upload task inputs and spawn calculation process on remote machine.
    # REQUIRES: task.remote_folder is not None (asserted before session.occupy).
    async def start_task_on_machine(
        self,
        session: MachineSession,
        engine: Engine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        """Upload task inputs and spawn calculation process on remote machine."""
        # region BLOCK_start_task
        if task.remote_folder is None:
            msg = "task.remote_folder must not be None"
            raise AssertionError(msg)
        session.occupy()

        logger.info(
            "Submitting task_id=%s %s with %s to %s",
            task.task_id,
            task.label,
            engine.name,
            session.hostname,
        )

        # region BLOCK_deploy_spawn
        try:
            path_type = session.path
            remote_folder = path_type(task.remote_folder)
            # region BLOCK_deploy
            async with session.open_sftp() as sftp:
                try:
                    root_dir = path_type(await sftp.realpath("."))
                    task_dir = (
                        remote_folder
                        if remote_folder.is_absolute()
                        else root_dir / remote_folder
                    )
                    if engines_dir.is_absolute():
                        engine_path = engines_dir / engine.name
                    else:
                        engine_path = root_dir / engines_dir / engine.name
                    await self._upload_task_data(
                        session,
                        task,
                        task_dir,
                        engine.input_files,
                    )
                except Exception:
                    logger.exception(
                        "Can't upload task_id=%s files",
                        task.task_id,
                    )
                    raise
            # endregion BLOCK_deploy

            await self._exec_spawn_command(
                session,
                engine,
                task,
                task_dir,
                engine_path,
                ncpus,
            )
        except BaseException as err:
            # region BLOCK_rollback_busy
            # Roll back the session BUSY marking on any deploy/spawn failure (incl.
            # CancelledError during daemon shutdown) so the machine is not left stuck.
            if session.is_closed:
                logger.warning(
                    "task_id=%s on %s: already disconnected, skipping rollback (%s)",
                    task.task_id,
                    session.hostname,
                    err,
                )
                raise
            if session.machine.state != MachineState.BUSY:
                logger.warning(
                    "unexpected state %s, expected BUSY (task_id=%s on %s)",
                    session.machine.state,
                    task.task_id,
                    session.hostname,
                )
            else:
                logger.info(
                    "task_id=%s on %s (%s); rolling back BUSY",
                    task.task_id,
                    session.hostname,
                    err,
                )
            session.update(session.machine.release())
            raise
            # endregion BLOCK_rollback_busy
        # endregion BLOCK_deploy_spawn

        return True
        # endregion BLOCK_start_task

    # endregion METHOD_start_task_on_machine


# endregion CLASS_TaskDeployer
