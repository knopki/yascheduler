"""Protocol definitions for process info, SSH checks, and adapters."""
# region MODULE_CONTRACT
# PURPOSE: Type aliases, exception tuples, and callable protocols for SSH remote machine operations.
# SCOPE:
# - Exception tuples: SFTPRetryExc, SSHRetryExc, AllSSHRetryExc
# - Data class: ProcessInfo
# - Protocols: RunCallable, RunBgCallable, OuterRunCallable, ListProcessesCallable, PgrepCallable, SetupNodeCallable
# - Callable aliases: SSHCheck, QuoteCallable, GetCPUCoresCallable
# KEYWORDS: protocol, type aliases, ssh, sftp, exceptions, callables
# endregion MODULE_CONTRACT

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

__all__ = [
    "AllSSHRetryExc",
    "GetCPUCoresCallable",
    "ListProcessesCallable",
    "OuterRunCallable",
    "PgrepCallable",
    "ProcessInfo",
    "QuoteCallable",
    "RunBgCallable",
    "RunCallable",
    "SFTPRetryExc",
    "SSHCheck",
    "SSHRetryExc",
    "SetupNodeCallable",
]

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
