"""Protocol definitions for process info, SSH checks, and adapters."""
# FILE: yascheduler/infra/ssh/platform/protocol.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Protocol definitions for process info, SSH checks, and adapters.
#   SCOPE: SFTPRetryExc, SSHRetryExc, AllSSHRetryExc, ProcessInfo, SSHCheck, QuoteCallable, RunCallable, RunBgCallable, OuterRunCallable, GetCPUCoresCallable, ListProcessesCallable, PgrepCallable, SetupNodeCallable protocols and type aliases.
#   DEPENDS: M-DOMAIN-ENGINE
#   LINKS: M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SFTPRetryExc             - Tuple of retriable SFTP exception types.
#   SSHRetryExc              - Tuple of retriable SSH exception types.
#   AllSSHRetryExc           - Union of SSHRetryExc and SFTPRetryExc.
#   ProcessInfo              - Frozen dataclass holding pid, name, command.
#   SSHCheck                 - Callable alias: async SSH connection health check.
#   QuoteCallable            - Callable alias: string quoting function.
#   RunCallable              - Protocol: run a command via SSH and return completed process.
#   RunBgCallable            - Protocol: run a command in background via SSH.
#   OuterRunCallable         - Protocol: curried run callable with pre-bound conn/quote.
#   GetCPUCoresCallable      - Callable alias: async CPU core count retrieval.
#   ListProcessesCallable    - Protocol: async generator listing running processes.
#   PgrepCallable            - Protocol: async generator filtering processes by pattern.
#   SetupNodeCallable        - Protocol: async node setup (engines, dirs).
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.4.0 - Drop `log` parameter from SetupNodeCallable (platform functions now bind a module-global logger).
#   PREVIOUS_CHANGE: v1.3.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from asyncssh.connection import SSHClientConnection
from asyncssh.misc import (
    ChannelListenError,
    ChannelOpenError,
    CompressionError,
    ConnectionLost,
    KeyExchangeFailed,
    MACError,
    ProtocolError,
    ServiceNotAvailable,
)
from asyncssh.sftp import (
    SFTPBadMessage,
    SFTPByteRangeLockConflict,
    SFTPByteRangeLockRefused,
    SFTPConnectionLost,
    SFTPDeletePending,
    SFTPEOFError,
    SFTPFailure,
    SFTPInvalidHandle,
    SFTPLockConflict,
    SFTPNoConnection,
    SFTPNoMatchingByteRangeLock,
)

if TYPE_CHECKING:
    from pathlib import PurePath
    from re import Pattern

    from asyncssh.process import SSHClientProcess, SSHCompletedProcess

    from yascheduler.domain import EngineRepository

SFTPRetryExc = (
    asyncio.TimeoutError,
    SFTPEOFError,
    SFTPFailure,
    SFTPBadMessage,
    SFTPNoConnection,
    SFTPConnectionLost,
    SFTPInvalidHandle,
    SFTPLockConflict,
    SFTPByteRangeLockConflict,
    SFTPByteRangeLockRefused,
    SFTPDeletePending,
    SFTPNoMatchingByteRangeLock,
)
SSHRetryExc = (
    OSError,
    asyncio.TimeoutError,
    CompressionError,
    ConnectionLost,
    KeyExchangeFailed,
    MACError,
    ProtocolError,
    ServiceNotAvailable,
    ChannelOpenError,
    ChannelListenError,
)
AllSSHRetryExc = SSHRetryExc + SFTPRetryExc


@dataclass(frozen=True)
class ProcessInfo:
    """Remote process information — PID, name, and command line."""

    pid: int
    name: str
    command: str


SSHCheck = Callable[[SSHClientConnection], Coroutine[Any, Any, bool]]
QuoteCallable = Callable[[str], str]


class RunCallable(Protocol):
    """Callable protocol for synchronous SSH command execution."""

    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        quote: QuoteCallable,
        command: str,
        *args: object,
        cwd: str | None = None,
        **kwargs: dict[str, Any],
    ) -> Coroutine[Any, Any, SSHCompletedProcess]:
        """Call."""


class RunBgCallable(Protocol):
    """Callable protocol for background SSH command execution."""

    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        quote: QuoteCallable,
        command: str,
        *args: object,
        cwd: str | None = None,
        **kwargs: object,
    ) -> Coroutine[Any, Any, SSHClientProcess[Any]]:
        """Call."""


class OuterRunCallable(Protocol):
    """Callable protocol wrapping ``run``/``run_bg`` with platform dispatch."""

    @abstractmethod
    def __call__(
        self,
        *args: object,
        cwd: str | None = None,
        **kwargs: dict[str, Any],
    ) -> Coroutine[Any, Any, SSHCompletedProcess]:
        """Call."""


GetCPUCoresCallable = Callable[[OuterRunCallable], Coroutine[Any, Any, int]]


class ListProcessesCallable(Protocol):
    """Callable protocol for listing remote processes."""

    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        query: str | None = None,
    ) -> AsyncGenerator[ProcessInfo, None]:
        """Call."""


class PgrepCallable(Protocol):
    """Callable protocol for pattern-matching remote processes."""

    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        quote: QuoteCallable,
        pattern: str | Pattern[str],
        *,
        full: bool = True,
    ) -> AsyncGenerator[ProcessInfo, None]:
        """Call."""


class SetupNodeCallable(Protocol):
    """Callable protocol for node setup operations."""

    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        run: OuterRunCallable,
        quote: QuoteCallable,
        engines: EngineRepository,
        engines_dir: PurePath,
    ) -> Coroutine[Any, Any, None]:
        """Call."""
