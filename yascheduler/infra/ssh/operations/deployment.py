# FILE: yascheduler/infra/ssh/operations/deployment.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: TaskDeployer — upload task inputs and spawn the calculation process on a remote machine.
#   SCOPE: TaskDeployer class + _write_remote_file + _safe_b64decode module-private helpers.
#   DEPENDS: M-SSH-OPERATIONS-BASE, M-SSH-REPOSITORY, M-DOMAIN, M-PLATFORM
#   LINKS: M-SSH-OPS-DEPLOY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _safe_b64decode - Decode base64 with lenient padding handling (module-private)
#   _write_remote_file - Write data to remote file via SFTP with error handling (module-private)
#   TaskDeployer - Upload task inputs and spawn calculation process; rolls back BUSY on failure
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial module created (decompose-ssh-gateway). Extracted from the dissolved SSHMachineGateway god-class; start_task_on_machine + _upload_task_data + _exec_spawn_command + _write_remote_file + _safe_b64decode moved verbatim. Rollback now calls repository.occupy(ip) / repository.update_machine(state.machine.release()).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import asyncssh

if TYPE_CHECKING:
    import logging
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.sftp import SFTPClient

    from yascheduler.domain import ConnectedMachine, Engine, Task

    from ..repository import SSHMachineRepository
    from .base import SSHMachineOperations


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
#   INPUTS: { sftp: SFTPClient, path: str, data: bytes | str, log: Logger, mode: str }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Writes file on remote machine.
#   LINKS: M-SSH-OPS-DEPLOY
# END_CONTRACT: _write_remote_file
async def _write_remote_file(
    sftp: SFTPClient,
    path: str,
    data: bytes | str,
    log: logging.Logger,
    mode: str = "wb",
) -> None:
    # START_BLOCK_WRITE_FILE
    try:
        async with sftp.open(path, mode) as f:
            await f.write(data)  # type: ignore[type-var]
    except asyncssh.misc.Error as err:
        log.error(
            "Write %s - SFTPError: %s (%s)",
            path,
            err.reason,
            err.code,
        )
        raise err
    # END_BLOCK_WRITE_FILE


# START_CONTRACT: TaskDeployer
#   PURPOSE: Upload task inputs and spawn calculation process on a remote machine; rolls back BUSY on failure.
#   LINKS: M-SSH-OPS-DEPLOY, M-SSH-OPERATIONS, M-SSH-REPOSITORY
# END_CONTRACT: TaskDeployer
class TaskDeployer:
    """Upload task inputs and spawn the calculation process on a remote machine.

    Receives a primitive-provider (the operations object, typed against the
    narrow CommandExecutor + SftpProvider + StateAccessors Protocols) and the
    repository (for occupy/release/get_quote). Rolls back the repository-level
    BUSY marking under `except BaseException` on any deploy/spawn failure.
    """

    def __init__(
        self,
        operations: SSHMachineOperations,
        repository: SSHMachineRepository,
        log: logging.Logger,
    ) -> None:
        self._operations = operations
        self._repository = repository
        self._log = log

    # START_CONTRACT: TaskDeployer._upload_task_data
    #   PURPOSE: Upload task input files to remote machine via SFTP.
    #   INPUTS: { ip, task, remote_dir, input_files }
    #   OUTPUTS: { bool - True on success }
    #   SIDE_EFFECTS: Creates remote directories, writes files via SFTP.
    #   LINKS: M-SSH-OPS-DEPLOY
    # END_CONTRACT: TaskDeployer._upload_task_data
    async def _upload_task_data(
        self,
        ip: str,
        task: Task,
        remote_dir: PurePath,
        input_files: Sequence[str],
    ) -> bool:
        from pathlib import PurePosixPath

        # START_BLOCK_UPLOAD
        async with self._operations.get_sftp(ip) as sftp:
            try:
                await sftp.makedirs(PurePosixPath(remote_dir), exist_ok=True)
            except asyncssh.misc.Error as err:
                self._log.error(
                    "Create %s - SFTPError: %s (%s) (task_id=%s)",
                    remote_dir,
                    err.reason,
                    err.code,
                    task.task_id,
                )
                raise err

            for input_file in input_files:
                r_input_file = remote_dir / input_file
                file_data = task.context.extra[input_file]
                if input_file == "fort.9":
                    await _write_remote_file(
                        sftp,
                        r_input_file.as_posix(),
                        _safe_b64decode(str(file_data)),
                        self._log,
                    )
                else:
                    await _write_remote_file(
                        sftp,
                        r_input_file.as_posix(),
                        str(file_data),
                        self._log,
                        mode="w",
                    )
        return True
        # END_BLOCK_UPLOAD

    # START_CONTRACT: TaskDeployer._exec_spawn_command
    #   PURPOSE: Execute spawn command on remote machine via SSH.
    #   INPUTS: { machine, engine, task, task_dir, eng_path, ncpus }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Runs background process on remote machine.
    #   LINKS: M-SSH-OPS-DEPLOY
    # END_CONTRACT: TaskDeployer._exec_spawn_command
    async def _exec_spawn_command(
        self,
        machine: ConnectedMachine,
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
                task_path=self._repository.get_quote(machine.ip)(str(task_dir)),
                ncpus=ncpus,
            )
            await self._operations.run_bg(machine, run_cmd, cwd=str(task_dir))
        except Exception as err:
            self._log.error("SSH spawn cmd error: %s", err)
            raise err
        # END_BLOCK_SPAWN

    # START_CONTRACT: TaskDeployer.start_task_on_machine
    #   PURPOSE: Upload task inputs and spawn calculation process on remote machine.
    #   INPUTS: {
    #     machine: ConnectedMachine - Target machine,
    #     engine: Engine - Engine metadata (spawn template, input files),
    #     task: Task - Task being deployed,
    #     ncpus: int - CPU cores for spawn command formatting,
    #     engines_dir: PurePath - Remote engines directory for engine path resolution
    #   }
    #   OUTPUTS: { bool - True on successful spawn }
    #   SIDE_EFFECTS: Uploads files via SFTP, marks machine busy, runs spawn command via run_bg.
    #   LINKS: M-SSH-OPS-DEPLOY, M-SSH-REPOSITORY
    # END_CONTRACT: TaskDeployer.start_task_on_machine
    async def start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: Engine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        from yascheduler.domain import MachineState

        # START_BLOCK_START_TASK
        self._log.info(
            "Submitting task_id=%s %s with %s to %s",
            task.task_id,
            task.label,
            engine.name,
            self._repository.get_hostname(machine.ip),
        )
        assert task.context.remote_folder is not None
        self._repository.occupy(machine.ip)

        # START_BLOCK_DEPLOY_SPAWN
        try:
            path_type = self._repository.get_path(machine.ip)
            remote_folder = path_type(task.context.remote_folder)
            # START_BLOCK_DEPLOY
            async with self._operations.get_sftp(machine.ip) as sftp:
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
                        machine.ip, task, task_dir, engine.input_files
                    )
                except Exception as err:
                    self._log.error(
                        "Can't upload task_id=%s files: %s", task.task_id, err
                    )
                    raise err
            # END_BLOCK_DEPLOY

            await self._exec_spawn_command(
                machine, engine, task, task_dir, engine_path, ncpus
            )
        except BaseException as err:
            # START_BLOCK_ROLLBACK_BUSY
            # Roll back the repository BUSY marking on any deploy/spawn failure (incl.
            # CancelledError during daemon shutdown) so the machine is not left stuck.
            state = self._repository._get_machine_state(machine.ip)
            if state is None:
                self._log.warning(
                    "task_id=%s on %s: already disconnected, skipping rollback (%s)",
                    task.task_id,
                    machine.ip,
                    err,
                )
                raise
            if state.machine.state != MachineState.BUSY:
                self._log.warning(
                    "unexpected state %s, expected BUSY (task_id=%s on %s)",
                    state.machine.state,
                    task.task_id,
                    machine.ip,
                )
            else:
                self._log.info(
                    "task_id=%s on %s (%s); rolling back repository BUSY",
                    task.task_id,
                    machine.ip,
                    err,
                )
            self._repository.update_machine(state.machine.release())
            raise
            # END_BLOCK_ROLLBACK_BUSY
        # END_BLOCK_DEPLOY_SPAWN

        return True
        # END_BLOCK_START_TASK
