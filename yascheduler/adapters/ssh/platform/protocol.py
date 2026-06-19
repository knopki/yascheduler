#!/usr/bin/env python3
# FILE: yascheduler/adapters/ssh/platform/protocol.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Protocol definitions for engines, process info, SSH checks, and adapters.
#   SCOPE: SFTPRetryExc, SSHRetryExc, AllSSHRetryExc, PProcessInfo, PEngine, PEngineRepository, PNode, SSHCheck, QuoteCallable, RunCallable, RunBgCallable, OuterRunCallable, GetCPUCoresCallable, ListProcessesCallable, PgrepCallable, SetupNodeCallable protocols and type aliases.
#   DEPENDS: M-CONFIG-ENGINE
#   LINKS: M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SFTPRetryExc             - Tuple of retriable SFTP exception types.
#   SSHRetryExc              - Tuple of retriable SSH exception types.
#   AllSSHRetryExc           - Union of SSHRetryExc and SFTPRetryExc.
#   PProcessInfo             - Protocol: pid, name, command fields for a process.
#   PEngine                  - Protocol: engine metadata (name, deployable, platforms, checks).
#   PEngineRepository        - Protocol: query interface for engine packages and platforms.
#   PNode                    - Protocol: node identity (ip, username).
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
#   LAST_CHANGE: v1.0.0 - Copied from yascheduler/remote_machine/protocol.py for platform adapters.
# END_CHANGE_SUMMARY

import asyncio
import logging
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable, Coroutine, Sequence, ValuesView
from pathlib import PurePath
from re import Pattern
from typing import Any, Optional, Protocol, Union

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

from yascheduler.config import (
    LocalArchiveDeploy,
    LocalFilesDeploy,
    RemoteArchiveDeploy,
)

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


class PProcessInfo(Protocol):
    pid: int
    name: str
    command: str


class PEngine(Protocol):
    name: str
    deployable: tuple[
        Union[LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy], ...
    ]
    platforms: tuple[str, ...]
    check_pname: Optional[str]
    check_cmd: Optional[str]
    check_cmd_code: int
    sleep_interval: int


class PEngineRepository(Protocol):
    @abstractmethod
    def get_platform_packages(self) -> Sequence[str]:
        raise NotImplementedError

    @abstractmethod
    def filter_platforms(self, platforms: Sequence[str]) -> "PEngineRepository":
        raise NotImplementedError

    @abstractmethod
    def values(self) -> ValuesView[PEngine]:
        raise NotImplementedError


class PNode(Protocol):
    ip: str
    username: str


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
    ) -> AsyncGenerator[PProcessInfo, None]:
        pass


class PgrepCallable(Protocol):
    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        quote: QuoteCallable,
        pattern: Union[str, Pattern[str]],
        full: bool = True,
    ) -> AsyncGenerator[PProcessInfo, None]:
        pass


class SetupNodeCallable(Protocol):
    @abstractmethod
    def __call__(
        self,
        conn: SSHClientConnection,
        run: OuterRunCallable,
        quote: QuoteCallable,
        engines: PEngineRepository,
        engines_dir: PurePath,
        log: Optional[logging.Logger] = None,
    ) -> Coroutine[Any, Any, None]:
        pass
