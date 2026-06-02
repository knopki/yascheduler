# FILE: yascheduler/adapters/ssh/helpers.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Shared SSH infrastructure for adapters/ssh/ — platform adapter registry, SSH client factory, connection options, and helper functions.
#   SCOPE: ADAPTERS, MAX_SESSIONS, my_backoff_exc, MySSHClient, DEFAULT_CONN_OPTS, _resolve_tunnel, _detect_platform, _init_paths
#   DEPENDS: M-PLATFORM-ADAPTERS, M-PLATFORM-PROTOCOL, M-PLATFORM-EXC
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ADAPTERS - Ordered platform adapter instances
#   MAX_SESSIONS - Default MaxSessions on OpenSSH server (10)
#   my_backoff_exc - Partial backoff decorator for SSHRetryExc
#   MySSHClient - Insecure SSH client that trusts all host keys
#   DEFAULT_CONN_OPTS - Default SSH connection options
#   _resolve_tunnel - Build SSH tunnel string from jump host/username
#   _detect_platform - Run adapter checks on connected host, return first match and all matched platforms
#   _init_paths - Normalize remote data/engines/tasks dirs using adapter path type
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted shared SSH infrastructure from remote_machine/remote_machine.py.
# END_CHANGE_SUMMARY

from __future__ import annotations

from asyncio.locks import Semaphore
from functools import partial
from typing import TYPE_CHECKING

import backoff
from asyncssh.client import SSHClient
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions
from asyncstdlib import all as aall
from asyncstdlib import map as amap

from yascheduler.adapters.ssh.platform.adapters import (
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
from yascheduler.adapters.ssh.platform.exceptions import (
    PlatformGuessFailedError,
)
from yascheduler.adapters.ssh.platform.protocol import (
    SSHCheck,
    SSHRetryExc,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey

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
#   LINKS: M-PLATFORM-ADAPTERS, M-PLATFORM-PROTOCOL
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
