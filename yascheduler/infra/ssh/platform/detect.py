"""Platform detection — run adapter checks on a connected host, return first match and all matched platforms."""
# FILE: yascheduler/infra/ssh/platform/detect.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Platform detection — run adapter checks on a connected host, return first match and all matched platforms.
#   SCOPE: _detect_platform + MAX_SESSIONS.
#   DEPENDS: M-PLATFORM-ADAPTERS, M-PLATFORM-PROTOCOL, M-PLATFORM-EXC
#   LINKS: M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MAX_SESSIONS - Default MaxSessions on OpenSSH server (10); bounds detection concurrency.
#   _detect_platform - Run adapter checks on connected host, return first match and all matched platforms.
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from infra/ssh/helpers.py; _detect_platform + MAX_SESSIONS moved verbatim, no behavioral change.
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

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

MAX_SESSIONS = 10  # default MaxSessions on OpenSSH server


# START_CONTRACT: _detect_platform
#   PURPOSE: Run adapter checks on connected host, return first match and all matched platforms
#   SIDE_EFFECTS: Runs check commands on remote host
#   LINKS: M-PLATFORM-ADAPTERS, M-PLATFORM-PROTOCOL
# END_CONTRACT: _detect_platform
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
