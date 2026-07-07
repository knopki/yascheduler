#!/usr/bin/env python3
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
#   SetupNodeCallable        - Protocol: async node setup (engines, dirs, logging).
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Consolidate ProcessInfo into protocol.py (frozen dataclass); remove PProcessInfo and PNode Protocols. Consumers import ProcessInfo from .protocol; ListProcessesCallable/PgrepCallable now annotate AsyncGenerator[ProcessInfo, None].
#   PREVIOUS_CHANGE: v1.1.0 - Delete PEngine and PEngineRepository Protocols; consumers import Engine/EngineRepository from yascheduler.domain directly. Switch Deploy* import from yascheduler.config to yascheduler.domain. SetupNodeCallable.__call__ now references EngineRepository (TYPE_CHECKING import from yascheduler.domain).
# END_CHANGE_SUMMARY

import asyncio
import logging
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable, Coroutine
from dataclasses import dataclass
from pathlib import PurePath
from re import Pattern
from typing import TYPE_CHECKING, Any, Optional, Protocol, Union

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
from asyncssh.process import SSHClientProcess, SSHCompletedProcess
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
    pid: int
    name: str
    command: str


SSHCheck = Callable[[SSHClientConnection], Coroutine[Any, Any, bool]]
QuoteCallable = Callable[[str], str]


class RunCallable(Protocol):
    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        quote: QuoteCallable,
        command: str,
        *args: object,
        cwd: Optional[str] = None,
        **kwargs: dict[str, Any],
    ) -> Coroutine[Any, Any, SSHCompletedProcess]:
        pass


class RunBgCallable(Protocol):
    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        quote: QuoteCallable,
        command: str,
        *args: object,
        cwd: Optional[str] = None,
        **kwargs: object,
    ) -> Coroutine[Any, Any, SSHClientProcess[Any]]:
        pass


class OuterRunCallable(Protocol):
    @abstractmethod
    def __call__(
        self,
        *args: object,
        cwd: Optional[str] = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> Coroutine[Any, Any, SSHCompletedProcess]:
        pass


GetCPUCoresCallable = Callable[[OuterRunCallable], Coroutine[Any, Any, int]]


class ListProcessesCallable(Protocol):
    @abstractmethod
    def __call__(
        self, conn: SSHClientConnection, query: Optional[str] = None
    ) -> AsyncGenerator[ProcessInfo, None]:
        pass


class PgrepCallable(Protocol):
    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        quote: QuoteCallable,
        pattern: Union[str, Pattern[str]],
        full: bool = True,
    ) -> AsyncGenerator[ProcessInfo, None]:
        pass


class SetupNodeCallable(Protocol):
    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        run: OuterRunCallable,
        quote: QuoteCallable,
        engines: "EngineRepository",
        engines_dir: PurePath,
        log: Optional[logging.Logger] = None,
    ) -> Coroutine[Any, Any, None]:
        pass
