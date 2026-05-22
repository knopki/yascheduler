# FILE: yascheduler/remote_machine/remote_machine.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: SSH connection to a remote machine with platform detection, command execution, and SFTP.
#   SCOPE: RemoteMachine, RemoteMachineMetadata, MySSHClient, connection management, command execution, platform detection, SFTP file transfer, occupancy checking.
#   DEPENDS: M-REMOTE-ADAPTERS, M-REMOTE-EXC, M-REMOTE-PROTOCOL, M-COMPAT
#   LINKS: M-REMOTE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   RemoteMachine - Main class representing a connected remote SSH machine
#   RemoteMachineMetadata - Tracks whether a machine is busy and free-since timestamp
#   MySSHClient - Custom SSH client that trusts all host keys (insecure, bypasses MiM protection)
#   DEFAULT_CONN_OPTS - Default SSH client connection options
#   ADAPTERS - Ordered list of platform adapters for remote machine detection
#   MAX_SESSIONS - Default maximum concurrent SSH sessions (10)
#   my_backoff_exc - Partially applied backoff decorator for SSH retry exceptions
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"Remote machine"

import asyncio
import logging
from asyncio.locks import Event, Semaphore
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import partial
from pathlib import PurePath
from re import Pattern
from typing import AnyStr, Optional, Union

import asyncssh
import backoff
from asyncssh.client import SSHClient
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions
from asyncssh.process import SSHClientProcess, SSHCompletedProcess
from asyncssh.public_key import SSHKey
from asyncssh.sftp import SFTPClient
from asyncstdlib import all as aall
from asyncstdlib import map as amap
from attrs import define, field, validators

from ..compat import Self
from .adapters import (
    RemoteMachineAdapter,
    darwin_adapter,
    debian_10_adapter,
    debian_11_adapter,
    debian_12_adapter,
    debian_13_adapter,
    debian_14_adapter,
    debian_15_adapter,
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    windows7_adapter,
    windows8_adapter,
    windows10_adapter,
    windows11_adapter,
    windows12_adapter,
    windows_adapter,
)
from .exc import PlatformGuessFailed
from .protocol import (
    AllSSHRetryExc,
    PEngine,
    PEngineRepository,
    PProcessInfo,
    SSHCheck,
    SSHRetryExc,
)

ADAPTERS: Sequence[RemoteMachineAdapter] = [
    debian_10_adapter,
    debian_11_adapter,
    debian_12_adapter,
    debian_13_adapter,
    debian_14_adapter,
    debian_15_adapter,
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    darwin_adapter,
    windows10_adapter,
    windows11_adapter,
    windows12_adapter,
    windows7_adapter,
    windows8_adapter,
    windows_adapter,
]

# default value of MaxSessions on OpenSSH server is 10
MAX_SESSIONS = 10

my_backoff_exc = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SSHRetryExc,
)


class MySSHClient(SSHClient):
    def validate_host_public_key(
        self, host: str, addr: str, port: int, key: SSHKey
    ) -> bool:
        "Trust all host keys"
        # NOTE: this is insecure for MiM attacks
        return True


DEFAULT_CONN_OPTS = SSHClientConnectionOptions(
    client_factory=MySSHClient,
    preferred_auth="publickey",
    keepalive_interval=10,
    keepalive_count_max=10,
    compression_algs=[],
    agent_path="",
    username="root",
)


@define
class RemoteMachineMetadata:
    _busy: Optional[bool]
    free_since: Optional[datetime]

    def __init__(self):
        self._busy = None
        self.free_since = datetime.now()

    @property
    def busy(self) -> Optional[bool]:
        return self._busy

    @busy.setter
    def busy(self, new_busy: bool):
        if new_busy:
            self._busy = True
            self.free_since = None
        else:
            self._busy = False
            self.free_since = datetime.now()

    def is_free_longer_than(self, delta: timedelta) -> bool:
        if not self.free_since or self.busy:
            return False
        return datetime.now() - delta > self.free_since


@define(frozen=True)
class RemoteMachine:
    "Remote SSH machine"

    conn: SSHClientConnection = field()
    conn_opts: SSHClientConnectionOptions = field()

    meta: RemoteMachineMetadata = field()

    adapter: RemoteMachineAdapter = field()
    log: logging.Logger = field()

    # supported platforms (like debian-10, debian, debian-like and linux)
    platforms: Sequence[str] = field()

    data_dir: PurePath = field(validator=validators.instance_of(PurePath))
    engines_dir: PurePath = field(validator=validators.instance_of(PurePath))
    tasks_dir: PurePath = field(validator=validators.instance_of(PurePath))

    cancellation_event: Event = field(factory=Event, init=False)
    jobs: set[asyncio.Task[None]] = field(factory=set, init=False)
    sessions_limit: Semaphore = field(
        factory=lambda: Semaphore(MAX_SESSIONS), init=False
    )

    def __le__(self, other: Self) -> bool:
        if not self.meta.free_since:
            return True
        if not other.meta.free_since:
            return False
        return self.meta.free_since <= other.meta.free_since

    def __gt__(self, other: Self) -> bool:
        if not self.meta.free_since:
            return False
        if not other.meta.free_since:
            return True
        return self.meta.free_since > other.meta.free_since

    # START_CONTRACT: create
    #   PURPOSE: Async factory method: connect SSH, detect platform, create RemoteMachine instance
    #   INPUTS: { host: str - remote hostname, username: str - SSH username, client_keys: Optional[Sequence[PurePath]] - SSH key paths, port: int - SSH port, logger: Optional[logging.Logger] - optional logger, connect_timeout: Optional[int] - connection timeout, data_dir: Optional[PurePath] - remote data directory, engines_dir: Optional[PurePath] - remote engines directory, tasks_dir: Optional[PurePath] - remote tasks directory, jump_host: Optional[str] - SSH jump host, jump_username: Optional[str] - SSH jump username }
    #   OUTPUTS: { Self - RemoteMachine instance }
    #   SIDE_EFFECTS: Opens SSH connection, detects platform
    #   LINKS: M-REMOTE, M-REMOTE-ADAPTERS
    # END_CONTRACT: create
    @classmethod
    @my_backoff_exc()
    async def create(
        cls,
        host: str,
        username: str,
        client_keys: Optional[Sequence[PurePath]],
        port: int = 22,
        logger: Optional[logging.Logger] = None,
        connect_timeout: Optional[int] = None,
        data_dir: Optional[PurePath] = None,
        engines_dir: Optional[PurePath] = None,
        tasks_dir: Optional[PurePath] = None,
        jump_host: Optional[str] = None,
        jump_username: Optional[str] = None,
    ) -> Self:
        logger_name = f"{cls.__name__}:{username}@{host}:{port}"
        if logger:
            log = logger.getChild(logger_name)
        else:
            log = logging.getLogger(logger_name)
        # If our logging level is not set then asyncssh is too noisy
        asyncssh.logging.set_log_level(logging.WARNING if log.level == 0 else log.level)
        # asyncssh.logging.set_log_level("DEBUG")
        # asyncssh.logging.set_debug_level(2)

        # START_BLOCK_CONNECT
        # connection
        conn_opts = SSHClientConnectionOptions(
            options=DEFAULT_CONN_OPTS,
            host=host,
            port=port,
            username=username,
            tunnel=jump_host and jump_username and f"{jump_username}@{jump_host}",
            client_keys=client_keys or (),
            ignore_encrypted=True,
            connect_timeout=connect_timeout,
        )

        log.debug("Open connection")
        conn = await asyncssh.connection.connect(
            options=conn_opts,
            host=conn_opts.host,
            port=conn_opts.port,
            tunnel=conn_opts.tunnel,
        )
        # END_BLOCK_CONNECT

        # START_BLOCK_DETECT_PLATFORM
        # guess platform
        sess_lim = Semaphore(MAX_SESSIONS)

        async def with_limit(conn: SSHClientConnection, fn: SSHCheck):
            async with sess_lim:
                return await fn(conn)

        adapter = None
        platforms: Sequence[str] = []
        checks: Sequence[bool] = [
            await aall(amap(lambda y: with_limit(conn, y), x.checks)) for x in ADAPTERS
        ]

        for candidate, check in zip(ADAPTERS, checks):  # noqa: B905
            if check:
                platforms.append(candidate.platform)
            if check and not adapter:
                adapter = candidate

        if not adapter:
            raise PlatformGuessFailed()

        log.debug(f"Detected platform: {adapter.platform}")
        # END_BLOCK_DETECT_PLATFORM

        # START_BLOCK_INIT_PATHS
        Path = adapter.path
        if not isinstance(data_dir, Path):
            data_dir = Path(str(data_dir)) if data_dir else Path("./data")
        if not isinstance(engines_dir, Path):
            engines_dir = (
                Path(str(engines_dir)) if engines_dir else data_dir / "engines"
            )
        if not isinstance(tasks_dir, Path):
            tasks_dir = Path(str(tasks_dir)) if tasks_dir else data_dir / "tasks"
        # END_BLOCK_INIT_PATHS

        return cls(
            conn=conn,
            conn_opts=conn_opts,
            meta=RemoteMachineMetadata(),
            adapter=adapter,
            platforms=platforms,
            log=log,
            data_dir=data_dir,
            engines_dir=engines_dir,
            tasks_dir=tasks_dir,
        )

    @classmethod
    @asynccontextmanager
    async def create_ctx(cls, *args, **kwargs) -> AsyncGenerator["RemoteMachine", None]:
        """
        Create async context.
        :raises asyncssh.Error: An SSH error has occurred.
        """
        machine = await cls.create(*args, **kwargs)
        yield machine
        await machine.close()

    @property
    def hostname(self) -> str:
        return self.conn_opts.host

    # START_CONTRACT: close
    #   PURPOSE: Cancel running jobs and close SSH connection
    #   INPUTS: { None }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Cancels background jobs, closes SSH connection
    #   LINKS: M-REMOTE
    # END_CONTRACT: close
    async def close(self) -> None:
        "Close connections and free resources"
        # START_BLOCK_CANCEL_JOBS
        self.cancellation_event.set()
        for task in self.jobs:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # END_BLOCK_CANCEL_JOBS
        # START_BLOCK_CLOSE_CONN
        if self.conn._transport:
            self.log.debug("Close connection")
            self.conn.close()
            await self.conn.wait_closed()
        # END_BLOCK_CLOSE_CONN

    @asynccontextmanager
    async def sftp(self, **kwargs) -> AsyncGenerator[SFTPClient, None]:
        """
        Open SFTP connection
        :raises asyncssh.SFTPError: An SFTP error has occurred.
        """
        conn = await self.get_conn()
        async with conn.start_sftp_client(**kwargs) as sftp:
            yield sftp

    @my_backoff_exc()
    async def renew_conn(self) -> SSHClientConnection:
        """
        Reopen SSH connection
        """
        conn = await asyncssh.connection.connect(
            options=self.conn_opts,
            host=self.conn_opts.host,
            tunnel=self.conn_opts.tunnel,
        )
        # MUTATE OBJECT!
        object.__setattr__(self, "conn", conn)
        return conn

    async def get_conn(self) -> SSHClientConnection:
        """
        Return current SSH connection. Reopen if needed.
        """
        async with self.sessions_limit:
            if self.conn._transport and not self.conn._transport.is_closing():
                return self.conn
            self.log.debug("Connection is closed - reopening")
            return await self.renew_conn()

    @property
    def path(self) -> type[PurePath]:
        "Return path of the adapter"
        return self.adapter.path

    def quote(self, s: str) -> str:
        "Platform-specific shell quoting"
        return self.adapter.quote(s)

    # START_CONTRACT: run
    #   PURPOSE: Execute command on remote machine and wait for completion
    #   INPUTS: { args: tuple - command and arguments, cwd: Optional[str] - working directory, kwargs: dict - additional adapter-specific parameters }
    #   OUTPUTS: { SSHCompletedProcess - completed process result }
    #   SIDE_EFFECTS: Runs command on remote host
    #   LINKS: M-REMOTE
    # END_CONTRACT: run
    @my_backoff_exc()
    async def run(
        self, *args, cwd: Optional[str] = None, **kwargs
    ) -> SSHCompletedProcess:
        "Run process and wait for exit"
        conn = await self.get_conn()
        return await self.adapter.run(
            conn, self.adapter.quote, *args, cwd=cwd, **kwargs
        )

    async def run_bg(
        self, command: str, *args, cwd: Optional[str] = None, **kwargs
    ) -> SSHClientProcess[AnyStr]:
        "Run process in background"
        conn = await self.get_conn()
        return await self.adapter.run_bg(
            conn, self.adapter.quote, command, *args, cwd=cwd, **kwargs
        )

    @my_backoff_exc()
    async def get_cpu_cores(self) -> int:
        "Get number of CPU cores"
        return await self.adapter.get_cpu_cores(self.run)

    async def list_processes(self) -> AsyncGenerator[PProcessInfo, None]:
        "Returns information about all running processes"
        conn = await self.get_conn()
        async for x in self.adapter.list_processes(conn, None):
            yield x

    async def pgrep(
        self, pattern: Union[str, Pattern], full: bool = True
    ) -> AsyncGenerator[PProcessInfo, None]:
        """
        Returns information about running processes, that name matches a pattern.
        If `full`, check match against name or full cmd.
        """
        conn = await self.get_conn()
        async for x in self.adapter.pgrep(conn, self.adapter.quote, pattern, full):
            yield x

    # START_CONTRACT: setup_node
    #   PURPOSE: Install engine dependencies on the remote node
    #   INPUTS: { engines: PEngineRepository - repository of engines to install }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Installs engine dependencies on remote node
    #   LINKS: M-REMOTE
    # END_CONTRACT: setup_node
    async def setup_node(self, engines: PEngineRepository):
        """
        Setup node for target engines.
        :raises NotImplemented: Not supported on platform.
        """
        # START_BLOCK_SETUP
        self.log.info(f"CPUs count: {await self.get_cpu_cores()}")
        conn = await self.get_conn()
        retry = my_backoff_exc(exception=AllSSHRetryExc)
        await retry(self.adapter.setup_node)(
            conn=conn,
            run=self.run,
            quote=self.quote,
            engines=engines.filter_platforms(self.platforms),
            engines_dir=self.engines_dir,
            log=self.log,
        )
        # END_BLOCK_SETUP

    # START_CONTRACT: occupancy_check
    #   PURPOSE: Check if engine process is still running on the node
    #   INPUTS: { engine: PEngine - engine to check occupancy for }
    #   OUTPUTS: { bool - True if engine process is running }
    #   SIDE_EFFECTS: May renew SSH connection on SSH errors
    #   LINKS: M-REMOTE
    # END_CONTRACT: occupancy_check
    async def occupancy_check(self, engine: PEngine) -> bool:
        """
        Check if a node is occupied by an engine's task
        """
        # START_BLOCK_CHECK_PROCESS
        if engine.check_pname:
            try:
                if [x async for x in self.pgrep(engine.check_pname)]:
                    return True
            except SSHRetryExc as exc:
                self.log.info(f"Node {self.hostname} failed pgrep: {exc}")
                await self.renew_conn()
        elif engine.check_cmd:
            try:
                proc = await self.run(engine.check_cmd)
                if proc.returncode == engine.check_cmd_code:
                    return True
            except SSHRetryExc as exc:
                self.log.info(f"Node {self.hostname} failed command: {exc}")
                await self.renew_conn()
        return False
        # END_BLOCK_CHECK_PROCESS

    # START_CONTRACT: start_occupancy_check
    #   PURPOSE: Start periodic occupancy monitoring for an engine
    #   INPUTS: { engine: PEngine - engine to monitor }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Creates background task that periodically checks occupancy
    #   LINKS: M-REMOTE
    # END_CONTRACT: start_occupancy_check
    async def start_occupancy_check(self, engine: PEngine) -> None:
        """
        Start occupancy checker for engine.
        """
        # remove old tasks
        self.jobs.difference_update([t for t in self.jobs if t.done()])

        async def occupancy_checker():
            while not self.cancellation_event.is_set() and self.meta.busy is not False:
                await asyncio.sleep(engine.sleep_interval)

                try:
                    self.meta.busy = await asyncio.wait_for(
                        self.occupancy_check(engine), timeout=engine.sleep_interval
                    )
                except asyncio.TimeoutError:
                    tmpl = "Engine {} busy check timeouted on {}"
                    self.log.warning(tmpl.format(engine.name, self.hostname))
                except Exception as err:  # pylint: disable=broad-exception-caught
                    self.log.warning(err)

        self.jobs.add(asyncio.create_task(occupancy_checker()))
