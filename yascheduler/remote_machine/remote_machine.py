# FILE: yascheduler/remote_machine/remote_machine.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Thin RemoteMachine wrapper delegating SSH ops to SSHMachineGateway.
#   SCOPE: RemoteMachine (wrapper), RemoteMachineMetadata, MySSHClient, shared helpers for gateway.py.
#   DEPENDS: M-REMOTE-ADAPTERS, M-REMOTE-EXC, M-REMOTE-PROTOCOL, M-COMPAT, M-SSH-GATEWAY
#   LINKS: M-SCHEDULER, M-REMOTE-REPO, M-CLOUD-API, M-REMOTE-ADAPTERS, M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   RemoteMachine - Thin wrapper delegating to SSHMachineGateway
#   RemoteMachineMetadata - Busy/free-since tracking
#   MySSHClient - Insecure SSH client that trusts all host keys
#   DEFAULT_CONN_OPTS - Default SSH connection options
#   ADAPTERS - Ordered platform adapters
#   MAX_SESSIONS - Max concurrent SSH sessions (10)
#   my_backoff_exc - Backoff decorator for SSH retries
#   _resolve_tunnel - Build SSH tunnel string
#   _detect_platform - Run checks, return first matched adapter
#   _init_paths - Normalize dir paths via adapter path type
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - RemoteMachine refactored to thin wrapper delegating to SSHMachineGateway.
#   PREVIOUS_CHANGE: v1.7.0 - Extracted create classmethod blocks into private helpers.
# END_CHANGE_SUMMARY

"Remote machine"

from __future__ import annotations

import asyncio
import logging
from asyncio.locks import Semaphore
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

import backoff
from asyncssh.client import SSHClient
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions
from asyncstdlib import all as aall
from asyncstdlib import map as amap
from attrs import define, field

from yascheduler.domain.model import MachineState

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
from .exc import PlatformGuessFailedError
from .protocol import (
    PEngine,
    PEngineRepository,
    PProcessInfo,
    SSHCheck,
    SSHRetryExc,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from pathlib import PurePath

    from asyncssh.process import SSHClientProcess, SSHCompletedProcess
    from asyncssh.public_key import SSHKey
    from asyncssh.sftp import SFTPClient

    from ..compat import Self

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

MAX_SESSIONS = 10  # default MaxSessions on OpenSSH server

my_backoff_exc = partial(
    backoff.on_exception, wait_gen=backoff.fibo, max_time=60, exception=SSHRetryExc
)


class MySSHClient(SSHClient):
    def validate_host_public_key(
        self, host: str, addr: str, port: int, key: SSHKey
    ) -> bool:
        # NOTE: trust all host keys — insecure for MiM attacks
        return True


DEFAULT_CONN_OPTS = SSHClientConnectionOptions(
    client_factory=MySSHClient,
    preferred_auth="publickey",
    keepalive_interval=10,
    keepalive_count_max=10,
    compression_algs=[],
    agent_path="",
    config=[],
    known_hosts=None,
    username="root",
)


def _resolve_tunnel(jump_host: str | None, jump_username: str | None) -> str | None:
    return jump_host and jump_username and f"{jump_username}@{jump_host}"


# START_CONTRACT: _detect_platform
#   PURPOSE: Run adapter checks on connected host, return first match and all matched platforms
#   SIDE_EFFECTS: Runs check commands on remote host
#   LINKS: M-REMOTE-ADAPTERS
# END_CONTRACT: _detect_platform
async def _detect_platform(
    conn: SSHClientConnection, adapters: Sequence[RemoteMachineAdapter]
) -> tuple[RemoteMachineAdapter, Sequence[str]]:
    sess_lim = Semaphore(MAX_SESSIONS)

    async def with_limit(conn: SSHClientConnection, fn: SSHCheck) -> bool:
        async with sess_lim:
            return await fn(conn)

    adapter = None
    platforms: list[str] = []
    checks: Sequence[bool] = [
        await aall(amap(lambda y: with_limit(conn, y), x.checks)) for x in adapters
    ]
    for candidate, check in zip(adapters, checks):  # noqa: B905
        if check:
            platforms.append(candidate.platform)
        if check and not adapter:
            adapter = candidate
    if not adapter:
        raise PlatformGuessFailedError()
    return adapter, platforms


# START_CONTRACT: _init_paths
#   PURPOSE: Normalize remote data/engines/tasks dirs using adapter path type
#   LINKS: none
# END_CONTRACT: _init_paths
def _init_paths(
    adapter: RemoteMachineAdapter,
    data_dir: PurePath | None,
    engines_dir: PurePath | None,
    tasks_dir: PurePath | None,
) -> tuple[PurePath, PurePath, PurePath]:
    path_cls = adapter.path
    if not isinstance(data_dir, path_cls):
        data_dir = path_cls(str(data_dir)) if data_dir else path_cls("./data")
    if not isinstance(engines_dir, path_cls):
        engines_dir = (
            path_cls(str(engines_dir)) if engines_dir else data_dir / "engines"
        )
    if not isinstance(tasks_dir, path_cls):
        tasks_dir = path_cls(str(tasks_dir)) if tasks_dir else data_dir / "tasks"
    return data_dir, engines_dir, tasks_dir


@define
class RemoteMachineMetadata:
    _busy: bool | None
    free_since: datetime | None

    def __init__(self) -> None:
        self._busy = None
        self.free_since = datetime.now()

    @property
    def busy(self) -> bool | None:
        return self._busy

    @busy.setter
    def busy(self, new_busy: bool) -> None:
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


@define
class RemoteMachine:
    """Compatibility wrapper — delegates to SSHMachineGateway."""

    ip: str = field()
    _gateway: Any = field(alias="_gateway", repr=False)
    meta: RemoteMachineMetadata = field()
    log: logging.Logger = field(repr=False)
    hostname: str = field()

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

    @property
    def platforms(self) -> Sequence[str]:
        return self._gateway.get_platforms(self.ip)

    @property
    def path(self) -> type[PurePath]:
        return self._gateway.get_path(self.ip)

    def quote(self, s: str) -> str:
        return self._gateway.get_quote(self.ip)(s)

    @property
    def data_dir(self) -> PurePath:
        return self._gateway.get_data_dir(self.ip)

    @property
    def engines_dir(self) -> PurePath:
        return self._gateway.get_engines_dir(self.ip)

    @property
    def tasks_dir(self) -> PurePath:
        return self._gateway.get_tasks_dir(self.ip)

    @classmethod
    async def create(
        cls,
        host: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        port: int = 22,
        logger: logging.Logger | None = None,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
        gateway: Any | None = None,  # noqa: ANN401
    ) -> Self:
        from yascheduler.adapters.ssh.gateway import SSHMachineGateway

        if gateway is None:
            gateway = SSHMachineGateway(log=logger)
        machine = await gateway.connect(
            ip=host,
            username=username,
            client_keys=client_keys,
            port=port,
            connect_timeout=connect_timeout,
            data_dir=data_dir,
            engines_dir=engines_dir,
            tasks_dir=tasks_dir,
            jump_host=jump_host,
            jump_username=jump_username,
        )
        log = (
            logger.getChild(f"{cls.__name__}:{username}@{host}:{port}")
            if logger
            else logging.getLogger(f"{cls.__name__}:{username}@{host}:{port}")
        )
        meta = RemoteMachineMetadata()
        meta.busy = machine.state == MachineState.BUSY
        return cls(
            ip=host,
            _gateway=gateway,
            meta=meta,
            log=log,
            hostname=gateway.get_hostname(host),
        )

    @classmethod
    @asynccontextmanager
    async def create_ctx(cls, *args, **kwargs) -> AsyncGenerator[RemoteMachine, None]:  # noqa: ANN002, ANN003
        machine = await cls.create(*args, **kwargs)
        yield machine
        await machine.close()

    async def close(self) -> None:
        await self._gateway.disconnect(self.ip)

    @asynccontextmanager
    async def sftp(self, **kwargs) -> AsyncGenerator[SFTPClient, None]:  # noqa: ANN003
        async with self._gateway.get_sftp(self.ip) as sftp:
            yield sftp

    @my_backoff_exc()
    async def run(self, *args, cwd: str | None = None, **kwargs) -> SSHCompletedProcess:  # noqa: ANN002, ANN003
        state = self._gateway.get_machine_state(self.ip)
        conn = await self._gateway.get_conn(self.ip)
        return await state.adapter.run(
            conn, state.adapter.quote, *args, cwd=cwd, **kwargs
        )

    async def run_bg(
        self,
        command: str,
        *args,  # noqa: ANN002
        cwd: str | None = None,
        **kwargs,  # noqa: ANN003
    ) -> SSHClientProcess:
        state = self._gateway.get_machine_state(self.ip)
        conn = await self._gateway.get_conn(self.ip)
        return await state.adapter.run_bg(
            conn, state.adapter.quote, command, *args, cwd=cwd, **kwargs
        )

    async def get_cpu_cores(self) -> int:
        return await self._gateway.get_cpu_cores(self.ip)

    async def list_processes(self) -> AsyncGenerator[PProcessInfo, None]:
        async for x in self._gateway.list_processes(self.ip):
            yield x

    async def pgrep(
        self, pattern: str, full: bool = True
    ) -> AsyncGenerator[PProcessInfo, None]:
        async for x in self._gateway.pgrep(self.ip, pattern, full):
            yield x

    async def setup_node(self, engines: PEngineRepository) -> None:
        self.log.info(f"CPUs count: {await self.get_cpu_cores()}")
        await self._gateway.setup_node(self.ip, engines)

    async def occupancy_check(self, engine: PEngine) -> bool:
        return await self._gateway.occupancy_check(self.ip, engine)

    async def start_occupancy_check(self, engine: PEngine) -> None:
        self._gateway.start_occupancy_check(self.ip, engine)
        self.meta.busy = True

        async def _meta_sync() -> None:
            try:
                while self.meta.busy is not False:
                    await asyncio.sleep(engine.sleep_interval)
                    s = self._gateway.get_machine_state(self.ip)
                    if s is None or s.machine.state == MachineState.FREE:
                        self.meta.busy = False
            except asyncio.CancelledError:
                pass

        asyncio.create_task(_meta_sync())

    @my_backoff_exc()
    async def renew_conn(self) -> SSHClientConnection:
        return await self._gateway.get_conn(self.ip)

    async def get_conn(self) -> SSHClientConnection:
        return await self._gateway.get_conn(self.ip)
