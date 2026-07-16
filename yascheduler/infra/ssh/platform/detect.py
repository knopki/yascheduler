"""Platform detection — run adapter checks on a connected host, return first match and all matched platforms."""
# region MODULE_CONTRACT
# PURPOSE: Run adapter checks on a connected host, return first matching adapter and all matched platform tags.
# SCOPE: Platform detection by running each adapter's check sequence against the remote host.
# DEPENDENCIES: USES API: asyncstdlib (aall, amap)
# KEYWORDS: platform detection, adapter, detect, remote, checks
# endregion MODULE_CONTRACT

from __future__ import annotations

from asyncio.locks import Semaphore
from typing import TYPE_CHECKING

from asyncstdlib import all as aall
from asyncstdlib import map as amap

from .exceptions import PlatformGuessFailedError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from asyncssh.connection import SSHClientConnection

    from .adapters import RemoteMachineAdapter
    from .protocol import SSHCheck

__all__ = ["MAX_SESSIONS", "_detect_platform"]

MAX_SESSIONS = 10  # default MaxSessions on OpenSSH server


# region FUNC__detect_platform
# PURPOSE: Run adapter checks on connected host, return first match and all matched platforms.
# ENSURES: Raises PlatformGuessFailedError if no adapter matches.
async def _detect_platform(
    conn: SSHClientConnection,
    adapters: Sequence[RemoteMachineAdapter],
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
    for candidate, check in zip(adapters, checks):
        if check:
            platforms.append(candidate.platform)
        if check and not adapter:
            adapter = candidate
    if not adapter:
        raise PlatformGuessFailedError
    return adapter, platforms


# endregion FUNC__detect_platform
