# FILE: yascheduler/adapters/ssh/gateway.py
# VERSION: 1.4.0
# START_MODULE_CONTRACT
#   PURPOSE: SSH machine gateway implementing MachineGateway protocol via asyncssh.
#   SCOPE: SSHMachineGateway class with connection lifecycle, command execution, SFTP, occupancy monitoring, output download.
#   DEPENDS: M-DOMAIN-PORTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-PLATFORM-ADAPTERS, M-PLATFORM-PROTOCOL
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _safe_b64decode - Decode base64 with lenient padding handling
#   _write_remote_file - Write data to remote file via SFTP with error handling
#   _MachineState - Internal mutable state holder for a connected machine
#   _open_connection - Build SSH options and open a connection
#   my_backoff_sftp - Partial backoff decorator for SFTPRetryExc
#   SSHMachineGateway - SSH implementation of MachineGateway protocol
#   SSHMachineGateway._upload_task_data - Upload task input files to remote machine via SFTP
#   SSHMachineGateway._exec_spawn_command - Execute spawn command on remote machine via SSH
#   SSHMachineGateway.start_task_on_machine - Upload task inputs and spawn calculation process (port contract)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Move deferred helpers (_start_task_on_machine, _upload_task_data, _exec_spawn_command, _write_remote_file, _safe_b64decode) from orchestrator to gateway; expose as public start_task_on_machine (gateway-port-cleanup scope expansion).
#   PREVIOUS_CHANGE: v1.3.0 - Add @my_backoff_exc on run_bg/get_cpu_cores; @my_backoff_sftp on upload/download; split connect into outer + _connect_impl; rename get_machine_state -> _get_machine_state and add new port get_machine_state returning ConnectedMachine; add list_connected; add download_outputs (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import base64
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import PurePath, PurePosixPath
from typing import TYPE_CHECKING, Any

import asyncssh
import backoff
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions
from asyncssh.sftp import SFTPError

from yascheduler.domain import (
    ConnectedMachine,
    MachineState,
    ProcessResult,
    Task,
    TaskExecutionEngine,
)
from yascheduler.domain.exceptions import MachineConnectionError

from .exceptions import AllSSHRetryExc, SFTPRetryExc, SSHRetryExc
from .helpers import (
    ADAPTERS,
    DEFAULT_CONN_OPTS,
    _detect_platform,
    _init_paths,
    _resolve_tunnel,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, ItemsView, KeysView, Sequence
    from pathlib import Path, PurePath
    from re import Pattern

    from asyncssh.process import SSHCompletedProcess
    from asyncssh.sftp import SFTPClient

    from yascheduler.domain import OccupancyConfig

    from .platform import (
        OuterRunCallable,
        PEngineRepository,
        PProcessInfo,
        QuoteCallable,
        RemoteMachineAdapter,
    )

my_backoff_exc = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SSHRetryExc,
)

my_backoff_sftp = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SFTPRetryExc,
)


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
#   LINKS: M-SSH-GATEWAY
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
    except Exception as e:
        log.error("Error processing file %s: %s", path, e)
    # END_BLOCK_WRITE_FILE


# START_CONTRACT: _MachineState
#   PURPOSE: Internal state holder: connection, adapter, paths, domain machine.
#   LINKS: M-SSH-GATEWAY
# END_CONTRACT: _MachineState
@dataclass(frozen=True)
class _MachineState:
    """Internal state holder for a connected remote machine."""

    conn: SSHClientConnection
    conn_opts: SSHClientConnectionOptions
    machine: ConnectedMachine
    adapter: RemoteMachineAdapter
    platforms: Sequence[str]
    data_dir: PurePath
    engines_dir: PurePath
    tasks_dir: PurePath


# START_CONTRACT: SSHMachineGateway
#   PURPOSE: SSH implementation of MachineGateway protocol.
#   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
# END_CONTRACT: SSHMachineGateway
class SSHMachineGateway:
    """SSH gateway implementing MachineGateway protocol."""

    def __init__(self, log: logging.Logger | None = None) -> None:
        """Initialise SSH gateway."""
        self._machines: dict[str, _MachineState] = {}
        self._log = log or logging.getLogger("SSHMachineGateway")
        self._bg_tasks: set[asyncio.Task] = set()

    # START_CONTRACT: SSHMachineGateway._open_connection
    #   PURPOSE: Build SSH options and open connection.
    #   SIDE_EFFECTS: Opens SSH connection.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway._open_connection
    async def _open_connection(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> tuple[SSHClientConnection, SSHClientConnectionOptions]:
        """Build SSH options and open connection."""
        # START_BLOCK_BUILD_OPTS
        conn_opts = SSHClientConnectionOptions(
            options=DEFAULT_CONN_OPTS,
            host=ip,
            port=port,
            username=username,
            tunnel=_resolve_tunnel(jump_host, jump_username),
            client_keys=client_keys or (),
            ignore_encrypted=True,
            connect_timeout=connect_timeout,
        )
        # END_BLOCK_BUILD_OPTS
        # START_BLOCK_CONNECT
        self._log.debug("[SSHGateway][_open_connection][CONNECT] ip=%s", ip)
        conn = await asyncssh.connection.connect(
            options=conn_opts,
            host=conn_opts.host,
            port=conn_opts.port,
            tunnel=conn_opts.tunnel,
            config=[],
            known_hosts=None,
        )
        # END_BLOCK_CONNECT
        return conn, conn_opts

    # START_CONTRACT: SSHMachineGateway.connect
    #   PURPOSE: Public API — translates transport errors into domain MachineConnectionError.
    #   INPUTS: { ip: str, username: str, client_keys, *, port, connect_timeout, data_dir, engines_dir, tasks_dir, jump_host, jump_username }
    #   OUTPUTS: { ConnectedMachine - the newly registered machine }
    #   SIDE_EFFECTS: Opens SSH connection, detects platform, stores _MachineState.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-EXCEPTIONS
    # END_CONTRACT: SSHMachineGateway.connect
    async def connect(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> ConnectedMachine:
        """Open SSH connection, detect platform, return domain machine.

        Translates (asyncssh.misc.Error, OSError) into MachineConnectionError
        after _connect_impl's backoff exhausts retries.
        """
        try:
            return await self._connect_impl(
                ip,
                username,
                client_keys,
                port=port,
                connect_timeout=connect_timeout,
                data_dir=data_dir,
                engines_dir=engines_dir,
                tasks_dir=tasks_dir,
                jump_host=jump_host,
                jump_username=jump_username,
            )
        except (asyncssh.misc.Error, OSError) as err:
            raise MachineConnectionError(ip, str(err)) from err

    # START_CONTRACT: SSHMachineGateway._connect_impl
    #   PURPOSE: Inner connection implementation with backoff retry on SSHRetryExc.
    #   INPUTS: { same as connect }
    #   OUTPUTS: { ConnectedMachine }
    #   SIDE_EFFECTS: Opens SSH, detects platform, stores _MachineState.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway._connect_impl
    @my_backoff_exc()
    async def _connect_impl(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> ConnectedMachine:
        """Open SSH connection, detect platform, return domain machine (inner impl with backoff)."""
        conn, conn_opts = await self._open_connection(
            ip,
            username,
            client_keys,
            port=port,
            connect_timeout=connect_timeout,
            jump_host=jump_host,
            jump_username=jump_username,
        )
        # START_BLOCK_DETECT
        adapter, platforms = await _detect_platform(conn, ADAPTERS)
        self._log.debug(
            "[SSHGateway][connect][DETECT] platform=%s ip=%s", adapter.platform, ip
        )
        # END_BLOCK_DETECT
        # START_BLOCK_PATHS
        rd, re, rt = _init_paths(adapter, data_dir, engines_dir, tasks_dir)
        # END_BLOCK_PATHS
        # START_BLOCK_CREATE_MACHINE
        ncpus = await adapter.get_cpu_cores(self._make_run_fn(conn, adapter))
        machine = ConnectedMachine(
            ip=ip,
            platform=adapter.platform,
            ncpus=ncpus,
            state=MachineState.FREE,
            free_since=time.monotonic(),
        )
        # END_BLOCK_CREATE_MACHINE
        self._machines[ip] = _MachineState(
            conn=conn,
            conn_opts=conn_opts,
            machine=machine,
            adapter=adapter,
            platforms=platforms,
            data_dir=rd,
            engines_dir=re,
            tasks_dir=rt,
        )
        return machine

    # START_CONTRACT: SSHMachineGateway.disconnect
    #   PURPOSE: Close SSH, cancel bg tasks, remove state.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.disconnect
    async def disconnect(self, ip: str) -> None:
        """Close connection for a machine."""
        state = self._machines.pop(ip, None)
        if state is None:
            return
        for task in list(self._bg_tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if state.conn._transport:
            self._log.debug("[SSHGateway][disconnect] ip=%s", ip)
            state.conn.close()
            await state.conn.wait_closed()

    # START_CONTRACT: SSHMachineGateway.disconnect_all
    #   PURPOSE: Disconnect all machines.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.disconnect_all
    async def disconnect_all(self) -> None:
        """Close all connections."""
        for ip in list(self._machines):
            await self.disconnect(ip)

    # START_CONTRACT: SSHMachineGateway.list_free
    #   PURPOSE: Return FREE machines filtered by platform, oldest first.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.list_free
    def list_free(self, platforms: list[str] | None) -> list[ConnectedMachine]:
        """Return FREE machines, optionally filtered by platform."""
        result: list[ConnectedMachine] = []
        for state in self._machines.values():
            m = state.machine
            if m.state != MachineState.FREE:
                continue
            if platforms is not None and m.platform not in platforms:
                continue
            result.append(m)
        result.sort(key=lambda m: m.free_since or 0.0)
        return result

    # START_CONTRACT: SSHMachineGateway.list_connected
    #   PURPOSE: Return all registered ConnectedMachine objects (port contract).
    #   INPUTS: { None }
    #   OUTPUTS: { list[ConnectedMachine] }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.list_connected
    def list_connected(self) -> list[ConnectedMachine]:
        """Return all registered ConnectedMachine objects."""
        return [s.machine for s in self._machines.values()]

    # START_CONTRACT: SSHMachineGateway.run
    #   PURPOSE: Run command, return ProcessResult.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.run
    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult:
        """Run command and return structured result."""
        proc = await self.run_full(machine, cmd)
        return ProcessResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=proc.stdout
            if isinstance(proc.stdout, str)
            else str(proc.stdout or ""),
            stderr=proc.stderr
            if isinstance(proc.stderr, str)
            else str(proc.stderr or ""),
        )

    # START_CONTRACT: SSHMachineGateway.run_full
    #   PURPOSE: Run command, return raw SSHCompletedProcess.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.run_full
    @my_backoff_exc()
    async def run_full(
        self, machine: ConnectedMachine, cmd: str
    ) -> SSHCompletedProcess:
        """Run command and return raw SSHCompletedProcess."""
        state = self._machines[machine.ip]
        return await state.adapter.run(state.conn, state.adapter.quote, cmd)

    # START_CONTRACT: SSHMachineGateway.run_bg
    #   PURPOSE: Start background process via SSH.
    #   OUTPUTS: { None - matches port contract }
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.run_bg
    @my_backoff_exc()
    async def run_bg(
        self,
        machine: ConnectedMachine,
        cmd: str,
        *,
        cwd: str | None = None,
    ) -> None:
        """Start background process on remote machine."""
        state = self._machines[machine.ip]
        await state.adapter.run_bg(state.conn, state.adapter.quote, cmd, cwd=cwd)

    # START_CONTRACT: SSHMachineGateway.upload
    #   PURPOSE: Upload file via SFTP.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.upload
    @my_backoff_sftp()
    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None:
        """Upload file to remote machine via SFTP."""
        state = self._machines[machine.ip]
        async with state.conn.start_sftp_client() as sftp:
            await sftp.put(str(local), remote)

    # START_CONTRACT: SSHMachineGateway.download
    #   PURPOSE: Download file via SFTP.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.download
    @my_backoff_sftp()
    async def download(
        self, machine: ConnectedMachine, remote: str, local: Path
    ) -> None:
        """Download file from remote machine via SFTP."""
        state = self._machines[machine.ip]
        async with state.conn.start_sftp_client() as sftp:
            await sftp.get(remote, str(local))

    # START_CONTRACT: SSHMachineGateway.get_sftp
    #   PURPOSE: Async context manager yielding SFTP client.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.get_sftp
    @asynccontextmanager
    async def get_sftp(self, ip: str) -> AsyncGenerator[SFTPClient, None]:
        """Open SFTP client for machine (async context manager)."""
        state = self._machines[ip]
        async with state.conn.start_sftp_client() as sftp:
            yield sftp

    def _get_machine_state(self, ip: str) -> _MachineState | None:
        """Return adapter-internal state for ip, or None."""
        return self._machines.get(ip)

    # START_CONTRACT: SSHMachineGateway.get_machine_state
    #   PURPOSE: Return ConnectedMachine registered for ip, or None (port contract).
    #   INPUTS: { ip: str }
    #   OUTPUTS: { ConnectedMachine | None }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.get_machine_state
    def get_machine_state(self, ip: str) -> ConnectedMachine | None:
        """Return ConnectedMachine for ip (port contract), or None."""
        state = self._machines.get(ip)
        return state.machine if state is not None else None

    def update_machine(self, machine: ConnectedMachine) -> None:
        """Replace ConnectedMachine in state (occupy/release transitions)."""
        state = self._machines.get(machine.ip)
        if state is not None:
            self._machines[machine.ip] = replace(state, machine=machine)

    # START_CONTRACT: SSHMachineGateway._upload_task_data
    #   PURPOSE: Upload task input files to remote machine via SFTP.
    #   INPUTS: { ip, task, remote_dir, input_files }
    #   OUTPUTS: { bool - True on success }
    #   SIDE_EFFECTS: Creates remote directories, writes files via SFTP.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway._upload_task_data
    async def _upload_task_data(
        self,
        ip: str,
        task: Task,
        remote_dir: PurePath,
        input_files: Sequence[str],
    ) -> bool:
        # START_BLOCK_UPLOAD
        async with self.get_sftp(ip) as sftp:
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

    # START_CONTRACT: SSHMachineGateway._exec_spawn_command
    #   PURPOSE: Execute spawn command on remote machine via SSH.
    #   INPUTS: { machine, engine, task, task_dir, eng_path, ncpus }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Runs background process on remote machine.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway._exec_spawn_command
    async def _exec_spawn_command(
        self,
        machine: ConnectedMachine,
        engine: TaskExecutionEngine,
        task: Task,
        task_dir: PurePath,
        eng_path: PurePath,
        ncpus: int,
    ) -> None:
        # START_BLOCK_SPAWN
        try:
            run_cmd = engine.spawn.format(
                engine_path=str(eng_path),
                task_path=self.get_quote(machine.ip)(str(task_dir)),
                ncpus=ncpus,
            )
            await self.run_bg(machine, run_cmd, cwd=str(task_dir))
        except Exception as err:
            self._log.error("SSH spawn cmd error: %s", err)
            raise err
        # END_BLOCK_SPAWN

    # START_CONTRACT: SSHMachineGateway.start_task_on_machine
    #   PURPOSE: Upload task inputs and spawn calculation process on remote machine.
    #   INPUTS: {
    #     machine: ConnectedMachine - Target machine,
    #     engine: TaskExecutionEngine - Engine metadata (spawn template, input files),
    #     task: Task - Task being deployed,
    #     ncpus: int - CPU cores for spawn command formatting,
    #     engines_dir: PurePath - Remote engines directory for engine path resolution
    #   }
    #   OUTPUTS: { bool - True on successful spawn }
    #   SIDE_EFFECTS: Uploads files via SFTP, marks machine busy, runs spawn command via run_bg.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.start_task_on_machine
    async def start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: TaskExecutionEngine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        # START_BLOCK_START_TASK
        self._log.info(
            "Submitting task_id=%s %s with %s to %s",
            task.task_id,
            task.label,
            engine.name,
            self.get_hostname(machine.ip),
        )
        assert task.context.remote_folder is not None
        self.update_machine(machine.occupy())
        path_type = self.get_path(machine.ip)
        remote_folder = path_type(task.context.remote_folder)

        # START_BLOCK_DEPLOY
        async with self.get_sftp(machine.ip) as sftp:
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
                self._log.error("Can't upload task_id=%s files: %s", task.task_id, err)
                raise err
        # END_BLOCK_DEPLOY

        await self._exec_spawn_command(
            machine, engine, task, task_dir, engine_path, ncpus
        )

        return True
        # END_BLOCK_START_TASK

    # START_CONTRACT: SSHMachineGateway.download_outputs
    #   PURPOSE: SFTP session, per-file download with retry, remote dir cleanup; catch all exceptions.
    #   INPUTS: {
    #     ip: str - Machine IP,
    #     remote_dir: str - Remote directory path to clean after download,
    #     local_dir: Path - Local destination directory,
    #     files: list[str] - Remote file paths to download,
    #     task_id: int | None - Optional task ID for log correlation
    #   }
    #   OUTPUTS: { tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]] - (meta_add, sftp_errors) }
    #   SIDE_EFFECTS: Downloads files via SFTP, removes remote directory tree.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.download_outputs
    async def download_outputs(
        self,
        ip: str,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: int | None = None,
    ) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]:
        # START_BLOCK_DOWNLOAD_OUTPUTS
        meta_add: list[tuple[str, Any]] = [
            ("remote_folder", remote_dir),
            ("local_folder", str(local_dir)),
        ]
        sftp_errors: list[tuple[str | None, Exception]] = []
        path_type = self.get_path(ip)
        file_get_retry = my_backoff_sftp()
        job_retry = my_backoff_sftp()

        async def _session() -> None:
            async with self.get_sftp(ip) as sftp:
                for out_file in files:
                    try:
                        await file_get_retry(sftp.get)(
                            out_file, local_dir, preserve=True
                        )
                    except (OSError, SFTPError) as err:
                        sftp_errors.append((out_file, err))
                        self._log.warning(
                            "Cannot download file for task_id=%s from %s: %s",
                            task_id,
                            out_file,
                            err,
                        )
                await sftp.rmtree(path_type(remote_dir))

        try:
            await job_retry(_session)()
        except Exception as err:
            # Catch-all: whole-session failure (lost connection, etc.)
            self._log.warning("Cannot scp from %s: %s", remote_dir, err)
            sftp_errors.append((remote_dir, err))
        # END_BLOCK_DOWNLOAD_OUTPUTS
        return meta_add, sftp_errors

    # START_CONTRACT: SSHMachineGateway.occupancy_check
    #   PURPOSE: Check if engine process is still running via pgrep or check_cmd.
    #     Returns True (busy) when process found OR when SSH fails (safe default).
    #     Returns False (free) only when check succeeds and finds no process.
    #   INPUTS: { ip: str, config: OccupancyConfig - engine metadata for checks }
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.occupancy_check
    async def occupancy_check(self, ip: str, config: OccupancyConfig) -> bool:
        """Check if engine process is still running.

        Returns True (busy) when the engine process is found OR when the SSH
        check fails — the machine is presumed busy to avoid releasing a machine
        that still has a running task.
        Returns False (free) only when the check succeeds and finds no process.
        """
        # FIXME: split to 2 branch helpers
        if config.check_pname:
            try:
                count = 0
                async for proc in self.pgrep(ip, config.check_pname):
                    count += 1
                    self._log.debug(
                        "[SSHGateway][occupancy_check][PGREP] ip=%s pid=%s name=%s cmd=%s",
                        ip,
                        proc.pid,
                        proc.name,
                        proc.command,
                    )
                    return True
                self._log.debug(
                    "[SSHGateway][occupancy_check][PGREP_FREE] ip=%s pattern=%s count=%d",
                    ip,
                    config.check_pname,
                    count,
                )
                return False
            except SSHRetryExc as exc:
                self._log.warning("Machine %s pgrep failed, assuming busy: %s", ip, exc)
                return True
        elif config.check_cmd:
            try:
                state = self._machines[ip]
                proc = await self.run_full(state.machine, config.check_cmd)
                self._log.debug(
                    "[SSHGateway][occupancy_check][CHECK_CMD] ip=%s cmd=%s exit=%d expected=%d",
                    ip,
                    config.check_cmd,
                    proc.returncode,
                    config.check_cmd_code,
                )
                if proc.returncode == config.check_cmd_code:
                    return True
                return False
            except SSHRetryExc as exc:
                self._log.warning(
                    "Machine %s check_cmd failed, assuming busy: %s", ip, exc
                )
                return True
        self._log.debug("[SSHGateway][occupancy_check][NO_CHECK] ip=%s", ip)
        return False

    # START_CONTRACT: SSHMachineGateway.start_occupancy_check
    #   PURPOSE: Background task periodically checks occupancy, releases machine when done.
    #   INPUTS: { ip: str, config: OccupancyConfig - engine metadata for occupancy checks }
    #   SIDE_EFFECTS: Creates asyncio task
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.start_occupancy_check
    def start_occupancy_check(self, ip: str, config: OccupancyConfig) -> None:
        """Start background occupancy monitoring.

        Occupies the ConnectedMachine at the gateway level so that
        _meta_sync sees BUSY instead of FREE while the task runs.
        """
        state = self._machines.get(ip)
        if state is not None and state.machine.state == MachineState.FREE:
            self.update_machine(state.machine.occupy())

        async def _checker() -> None:
            try:
                while True:
                    await asyncio.sleep(config.sleep_interval)
                    try:
                        busy = await asyncio.wait_for(
                            self.occupancy_check(ip, config),
                            timeout=config.sleep_interval,
                        )
                        if not busy:
                            state = self._machines.get(ip)
                            if state is not None:
                                self.update_machine(state.machine.release())
                            break
                    except asyncio.TimeoutError:
                        self._log.warning(
                            "Engine %s busy check timed out on %s",
                            config.name,
                            ip,
                        )
                    except Exception:  # noqa: BLE001
                        self._log.exception(
                            "Occupancy check failed for %s on %s",
                            config.name,
                            ip,
                        )
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_checker())
        task.add_done_callback(self._bg_tasks.discard)
        self._bg_tasks.add(task)

    # START_CONTRACT: SSHMachineGateway.setup_node
    #   PURPOSE: Install engine dependencies on remote node.
    #   SIDE_EFFECTS: Installs software
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.setup_node
    async def setup_node(self, ip: str, engines: PEngineRepository) -> None:
        """Install engine dependencies on remote node."""
        state = self._machines[ip]
        self._log.info("CPUs count: %s", state.machine.ncpus)
        retry = my_backoff_exc(exception=AllSSHRetryExc)
        await retry(state.adapter.setup_node)(
            conn=state.conn,
            run=self._make_run_fn(state.conn, state.adapter),
            quote=state.adapter.quote,
            engines=engines.filter_platforms(state.platforms),
            engines_dir=state.engines_dir,
            log=self._log,
        )

    @my_backoff_exc()
    async def get_cpu_cores(self, ip: str) -> int:
        """Return CPU core count for machine."""
        state = self._machines[ip]
        return await state.adapter.get_cpu_cores(
            self._make_run_fn(state.conn, state.adapter)
        )

    async def pgrep(
        self,
        ip: str,
        pattern: str | Pattern[str],
        full: bool = True,
    ) -> AsyncGenerator[PProcessInfo, None]:
        """Yield remote processes matching pattern."""
        state = self._machines[ip]
        async for proc in state.adapter.pgrep(
            state.conn, state.adapter.quote, pattern, full
        ):
            yield proc

    async def list_processes(self, ip: str) -> AsyncGenerator[PProcessInfo, None]:
        """Yield all running processes on remote machine."""
        state = self._machines[ip]
        async for proc in state.adapter.list_processes(state.conn, None):
            yield proc

    def get_adapter(self, ip: str) -> RemoteMachineAdapter:
        return self._machines[ip].adapter

    def get_platforms(self, ip: str) -> Sequence[str]:
        return self._machines[ip].platforms

    def get_path(self, ip: str) -> type[PurePath]:
        return self._machines[ip].adapter.path

    def get_quote(self, ip: str) -> QuoteCallable:
        return self._machines[ip].adapter.quote

    def get_data_dir(self, ip: str) -> PurePath:
        return self._machines[ip].data_dir

    def get_engines_dir(self, ip: str) -> PurePath:
        return self._machines[ip].engines_dir

    def get_tasks_dir(self, ip: str) -> PurePath:
        return self._machines[ip].tasks_dir

    async def get_conn(self, ip: str) -> SSHClientConnection:
        """Return current SSH connection; reconnect if closed."""
        state = self._machines[ip]
        if state.conn._transport and not state.conn._transport.is_closing():
            return state.conn
        self._log.debug("[SSHGateway][get_conn][REOPEN] ip=%s", ip)
        conn = await asyncssh.connection.connect(
            options=state.conn_opts,
            host=state.conn_opts.host,
            tunnel=state.conn_opts.tunnel,
            config=[],
            known_hosts=None,
        )
        self._machines[ip] = replace(state, conn=conn)
        return conn

    def get_hostname(self, ip: str) -> str:
        return self._machines[ip].conn_opts.host

    def contains(self, ip: str) -> bool:
        return ip in self._machines

    def keys(self) -> KeysView[str]:
        return self._machines.keys()

    def __contains__(self, ip: str) -> bool:
        return ip in self._machines

    def __len__(self) -> int:
        return len(self._machines)

    def items(self) -> ItemsView[str, _MachineState]:
        return self._machines.items()

    def register_machine(self, ip: str, state: _MachineState) -> None:
        self._machines[ip] = state

    def _make_run_fn(
        self, conn: SSHClientConnection, adapter: RemoteMachineAdapter
    ) -> OuterRunCallable:
        """Build OuterRunCallable with pre-bound conn and quote."""

        async def _run_fn(
            *args: object,
            cwd: str | None = None,
            **kwargs: Any,  # noqa: ANN401
        ) -> SSHCompletedProcess:
            return await adapter.run(
                conn,
                adapter.quote,
                str(args[0]) if args else "",
                *args[1:],
                cwd=cwd,
                **kwargs,
            )

        return _run_fn
