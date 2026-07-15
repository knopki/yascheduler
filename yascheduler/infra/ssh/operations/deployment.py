# FILE: yascheduler/infra/ssh/operations/deployment.py
# VERSION: 1.7.0
# START_MODULE_CONTRACT
#   PURPOSE: TaskDeployer — upload task inputs and spawn the calculation process on a remote machine via MachineSession. Stateless: takes (log) at construction, (session, ...) per call.
#   SCOPE: TaskDeployer class + _write_remote_file + _safe_b64decode module-private helpers.
#   DEPENDS: M-DOMAIN, M-SSH-SESSION
#   LINKS: M-SSH-OPS-DEPLOY, M-SSH-SESSION
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _safe_b64decode - Decode base64 with lenient padding handling (module-private)
#   _write_remote_file - Write data to remote file via SFTP with error handling (module-private)
#   TaskDeployer - Upload task inputs and spawn calculation process; stateless (log)-only constructor; takes session per call; rolls back BUSY via session.is_closed check
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.7.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v1.6.0 - remove log parameter from __init__/signatures; bind module-local logger = get_logger("M-SSH-OPS-DEPLOY") at module top
# END_CHANGE_SUMMARY

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

import asyncssh

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.sftp import SFTPClient

    from yascheduler.domain import Engine, MachineSession, Task


# START_CONTRACT: _safe_b64decode
#   PURPOSE: Decode base64 string with lenient padding handling.
#   INPUTS: { b64_data: str | bytes - base64 encoded data }
#   OUTPUTS: { bytes - decoded binary data }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: _safe_b64decode
def _safe_b64decode(b64_data: str | bytes) -> bytes:
    if isinstance(b64_data, bytes):
        b64_data = b64_data.decode()
    b64_data = b64_data.strip().replace("\n", "").replace(" ", "")
    missing_padding = len(b64_data) % 4
    if missing_padding:
        b64_data += "=" * (4 - missing_padding)
    return base64.b64decode(b64_data)


# START_CONTRACT: _write_remote_file
#   PURPOSE: Write data to a remote file via SFTP with error handling.
#   INPUTS: { sftp: SFTPClient, path: str, data: bytes | str, mode: str }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Writes file on remote machine.
#   LINKS: M-SSH-OPS-DEPLOY
# END_CONTRACT: _write_remote_file
async def _write_remote_file(
    sftp: SFTPClient,
    path: str,
    data: bytes | str,
    mode: str = "wb",
) -> None:
    # START_BLOCK_WRITE_FILE
    try:
        async with sftp.open(path, mode) as f:
            await f.write(data)  # type: ignore[type-var]
    except asyncssh.misc.Error as err:
        logger.error(
            "Write %s - SFTPError: %s (%s)",
            path,
            err.reason,
            err.code,
        )
        raise err
    # END_BLOCK_WRITE_FILE


# START_CONTRACT: TaskDeployer
#   PURPOSE: Upload task inputs and spawn calculation process on a remote machine via MachineSession; rolls back BUSY on failure.
#   LINKS: M-SSH-OPS-DEPLOY, M-SSH-SESSION
# END_CONTRACT: TaskDeployer
class TaskDeployer:
    """Upload task inputs and spawn the calculation process on a remote machine.

    Stateless: takes (log) at construction, (session, ...) per call. Rolls back
    the session BUSY marking under `except BaseException` on any deploy/spawn
    failure.
    """

    def __init__(self) -> None:
        pass

    # START_CONTRACT: TaskDeployer._upload_task_data
    #   PURPOSE: Upload task input files to remote machine via SFTP.
    #   INPUTS: { session, task, remote_dir, input_files }
    #   OUTPUTS: { bool - True on success }
    #   SIDE_EFFECTS: Creates remote directories, writes files via SFTP.
    #   LINKS: M-SSH-OPS-DEPLOY
    # END_CONTRACT: TaskDeployer._upload_task_data
    async def _upload_task_data(
        self,
        session: MachineSession,
        task: Task,
        remote_dir: PurePath,
        input_files: Sequence[str],
    ) -> bool:
        from pathlib import PurePosixPath

        # START_BLOCK_UPLOAD
        async with session.open_sftp() as sftp:
            try:
                await sftp.makedirs(PurePosixPath(remote_dir), exist_ok=True)
            except asyncssh.misc.Error as err:
                logger.error(
                    "Create %s - SFTPError: %s (%s) (task_id=%s)",
                    remote_dir,
                    err.reason,
                    err.code,
                    task.task_id,
                )
                raise err

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
        # END_BLOCK_UPLOAD

    # START_CONTRACT: TaskDeployer._exec_spawn_command
    #   PURPOSE: Execute spawn command on remote machine via SSH.
    #   INPUTS: { session, engine, task, task_dir, eng_path, ncpus }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Runs background process on remote machine.
    #   LINKS: M-SSH-OPS-DEPLOY
    # END_CONTRACT: TaskDeployer._exec_spawn_command
    async def _exec_spawn_command(
        self,
        session: MachineSession,
        engine: Engine,
        task: Task,
        task_dir: PurePath,
        eng_path: PurePath,
        ncpus: int,
    ) -> None:
        # START_BLOCK_SPAWN
        try:
            run_cmd = engine.spawn.format(
                engine_path=str(eng_path),
                task_path=session.quote(str(task_dir)),
                ncpus=ncpus,
            )
            await session.run_bg(run_cmd, cwd=str(task_dir))
        except Exception as err:
            logger.error("SSH spawn cmd error: %s", err)
            raise err
        # END_BLOCK_SPAWN

    # START_CONTRACT: TaskDeployer.start_task_on_machine
    #   PURPOSE: Upload task inputs and spawn calculation process on remote machine.
    #   INPUTS: {
    #     session: MachineSession - Target machine session,
    #     engine: Engine - Engine metadata (spawn template, input files),
    #     task: Task - Task being deployed,
    #     ncpus: int - CPU cores for spawn command formatting,
    #     engines_dir: PurePath - Remote engines directory for engine path resolution
    #   }
    #   OUTPUTS: { bool - True on successful spawn }
    #   SIDE_EFFECTS: Uploads files via SFTP, marks machine busy, runs spawn command via run_bg. Raises AssertionError when task.remote_folder is None (precondition, checked before session.occupy() so outside the rollback path); uncaught locally, propagates to the orchestrator allocator worker's `except Exception`.
    #   LINKS: M-SSH-OPS-DEPLOY, M-SSH-SESSION
    # END_CONTRACT: TaskDeployer.start_task_on_machine
    async def start_task_on_machine(
        self,
        session: MachineSession,
        engine: Engine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        from yascheduler.domain import MachineState

        # START_BLOCK_START_TASK
        assert task.remote_folder is not None
        session.occupy()

        logger.info(
            "Submitting task_id=%s %s with %s to %s",
            task.task_id,
            task.label,
            engine.name,
            session.hostname,
        )

        # START_BLOCK_DEPLOY_SPAWN
        try:
            path_type = session.path
            remote_folder = path_type(task.remote_folder)
            # START_BLOCK_DEPLOY
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
                        session, task, task_dir, engine.input_files
                    )
                except Exception as err:
                    logger.error("Can't upload task_id=%s files: %s", task.task_id, err)
                    raise err
            # END_BLOCK_DEPLOY

            await self._exec_spawn_command(
                session, engine, task, task_dir, engine_path, ncpus
            )
        except BaseException as err:
            # START_BLOCK_ROLLBACK_BUSY
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
            # END_BLOCK_ROLLBACK_BUSY
        # END_BLOCK_DEPLOY_SPAWN

        return True
        # END_BLOCK_START_TASK
