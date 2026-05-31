# FILE: yascheduler/adapters/ssh/gateway.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: SSH machine gateway implementing MachineGateway protocol via asyncssh.
#   SCOPE: SSHMachineGateway class with connection lifecycle, command execution, SFTP, occupancy monitoring.
#   DEPENDS: M-DOMAIN-PORTS, M-DOMAIN-MODEL, M-PLATFORM-ADAPTERS, M-PLATFORM-PROTOCOL
#   LINKS: M-SSH-GATEWAY, M-REMOTE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _MachineState - Internal mutable state holder for a connected machine
#   _open_connection - Build SSH options and open a connection
#   SSHMachineGateway - SSH implementation of MachineGateway protocol
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Fix race: start_occupancy_check now occupies ConnectedMachine so _meta_sync sees BUSY. Return True on SSH failure in occupancy_check.
#   PREVIOUS_CHANGE: v1.1.0 - Extract _open_connection from connect to reduce function size.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, ItemsView, KeysView, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path, PurePath
from re import Pattern
from typing import Any

import asyncssh
import backoff
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions
from asyncssh.process import SSHClientProcess, SSHCompletedProcess
from asyncssh.sftp import SFTPClient

from yascheduler.adapters.ssh.platform.adapters import RemoteMachineAdapter
from yascheduler.adapters.ssh.platform.protocol import (
    AllSSHRetryExc,
    PEngine,
    PEngineRepository,
    PProcessInfo,
    SSHRetryExc,
)
from yascheduler.domain.model import ConnectedMachine, MachineState, ProcessResult
from yascheduler.remote_machine.remote_machine import (
    ADAPTERS,
    DEFAULT_CONN_OPTS,
    _detect_platform,
    _init_paths,
    _resolve_tunnel,
)

my_backoff_exc = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SSHRetryExc,
)


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
#   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS, M-REMOTE
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
        self._log.debug("Open connection to %s", ip)
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
    #   PURPOSE: Open SSH connection, detect platform, create&store domain machine.
    #   SIDE_EFFECTS: Opens SSH, detects platform, stores _MachineState
    #   LINKS: M-SSH-GATEWAY, M-REMOTE, M-PLATFORM-ADAPTERS
    # END_CONTRACT: SSHMachineGateway.connect
    @my_backoff_exc()
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
        """Open SSH connection, detect platform, return domain machine."""
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
        self._log.debug("Detected platform %s on %s", adapter.platform, ip)
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
            self._log.debug("Close connection to %s", ip)
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

    # START_CONTRACT: SSHMachineGateway.run
    #   PURPOSE: Run command, return ProcessResult.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.run
    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult:
        """Run command and return structured result."""
        proc = await self.run_full(machine, cmd)
        return ProcessResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
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
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.run_bg
    async def run_bg(
        self,
        machine: ConnectedMachine,
        cmd: str,
        *,
        cwd: str | None = None,
    ) -> SSHClientProcess:
        """Start background process on remote machine."""
        state = self._machines[machine.ip]
        return await state.adapter.run_bg(state.conn, state.adapter.quote, cmd, cwd=cwd)

    # START_CONTRACT: SSHMachineGateway.upload
    #   PURPOSE: Upload file via SFTP.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.upload
    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None:
        """Upload file to remote machine via SFTP."""
        state = self._machines[machine.ip]
        async with state.conn.start_sftp_client() as sftp:
            await sftp.put(str(local), remote)

    # START_CONTRACT: SSHMachineGateway.download
    #   PURPOSE: Download file via SFTP.
    #   LINKS: M-SSH-GATEWAY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineGateway.download
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

    def get_machine_state(self, ip: str) -> _MachineState | None:
        """Return internal machine state or None."""
        return self._machines.get(ip)

    def update_machine(self, machine: ConnectedMachine) -> None:
        """Replace ConnectedMachine in state (occupy/release transitions)."""
        state = self._machines.get(machine.ip)
        if state is not None:
            self._machines[machine.ip] = replace(state, machine=machine)

    # START_CONTRACT: SSHMachineGateway.occupancy_check
    #   PURPOSE: Check if engine process is still running via pgrep or check_cmd.
    #     Returns True (busy) when process found OR when SSH fails (safe default).
    #     Returns False (free) only when check succeeds and finds no process.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.occupancy_check
    async def occupancy_check(self, ip: str, engine: PEngine) -> bool:
        """Check if engine process is still running.

        Returns True (busy) when the engine process is found OR when the SSH
        check fails — the machine is presumed busy to avoid releasing a machine
        that still has a running task.
        Returns False (free) only when the check succeeds and finds no process.
        """
        if engine.check_pname:
            try:
                count = 0
                async for proc in self.pgrep(ip, engine.check_pname):
                    count += 1
                    self._log.debug(
                        "[occupancy][%s] pgrep found: pid=%s name=%s cmd=%s",
                        ip,
                        proc.pid,
                        proc.name,
                        proc.command,
                    )
                    return True
                self._log.debug(
                    "[occupancy][%s] pgrep '%s' found %d processes -> free",
                    ip,
                    engine.check_pname,
                    count,
                )
                return False
            except SSHRetryExc as exc:
                self._log.warning("Machine %s pgrep failed, assuming busy: %s", ip, exc)
                return True
        elif engine.check_cmd:
            try:
                state = self._machines[ip]
                proc = await self.run_full(state.machine, engine.check_cmd)
                self._log.debug(
                    "[occupancy][%s] check_cmd '%s' exit=%d (expected=%d)",
                    ip,
                    engine.check_cmd,
                    proc.returncode,
                    engine.check_cmd_code,
                )
                if proc.returncode == engine.check_cmd_code:
                    return True
                return False
            except SSHRetryExc as exc:
                self._log.warning(
                    "Machine %s check_cmd failed, assuming busy: %s", ip, exc
                )
                return True
        self._log.debug("[occupancy][%s] no check configured -> free", ip)
        return False

    # START_CONTRACT: SSHMachineGateway.start_occupancy_check
    #   PURPOSE: Background task periodically checks occupancy, releases machine when done.
    #   SIDE_EFFECTS: Creates asyncio task
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: SSHMachineGateway.start_occupancy_check
    def start_occupancy_check(self, ip: str, engine: PEngine) -> None:
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
                    await asyncio.sleep(engine.sleep_interval)
                    try:
                        busy = await asyncio.wait_for(
                            self.occupancy_check(ip, engine),
                            timeout=engine.sleep_interval,
                        )
                        if not busy:
                            state = self._machines.get(ip)
                            if state is not None:
                                self.update_machine(state.machine.release())
                            break
                    except asyncio.TimeoutError:
                        self._log.warning(
                            "Engine %s busy check timed out on %s",
                            engine.name,
                            ip,
                        )
                    except Exception:  # noqa: BLE001
                        self._log.exception(
                            "Occupancy check failed for %s on %s",
                            engine.name,
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

    def get_quote(self, ip: str):
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
        self._log.debug("Connection %s is closed - reopening", ip)
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

    def _make_run_fn(self, conn: SSHClientConnection, adapter: RemoteMachineAdapter):
        """Build OuterRunCallable with pre-bound conn and quote."""

        async def _run_fn(
            *args: object,
            cwd: str | None = None,
            **kwargs: Any,
        ) -> SSHCompletedProcess:
            return await adapter.run(conn, adapter.quote, *args, cwd=cwd, **kwargs)

        return _run_fn
