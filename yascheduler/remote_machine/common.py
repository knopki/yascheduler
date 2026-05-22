#!/usr/bin/env python3
# FILE: yascheduler/remote_machine/common.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Shared helpers for remote machine operations: process info, command execution.
#   SCOPE: ProcessInfo data class, run and run_bg command execution helpers.
#   DEPENDS: M-REMOTE-PROTOCOL
#   LINKS: M-REMOTE-COMMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ProcessInfo - Attrs struct holding pid, name, command
#   run - Run process on SSH connection and wait for exit
#   run_bg - Create background process on SSH connection
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#

from subprocess import DEVNULL
from typing import AnyStr, Optional

from asyncssh.connection import SSHClientConnection
from asyncssh.process import SSHClientProcess, SSHCompletedProcess
from attrs import define

from .protocol import QuoteCallable


@define
class ProcessInfo:
    pid: int
    name: str
    command: str


async def run(
    conn: SSHClientConnection,
    quote: QuoteCallable,
    command: str,
    *args: object,
    cwd: Optional[str] = None,
    **kwargs: object,
) -> SSHCompletedProcess:
    """
    Run process and wait for exit
    :raises asyncssh.Error: An SSH error has occurred.
    """
    if cwd:
        command = f"cd {quote(cwd)}; {command}"
    timeout = kwargs.pop("timeout", None)
    if not isinstance(timeout, float):
        timeout = None
    return await conn.run(
        command,
        *args,
        check=bool(kwargs.pop("check", False)),
        timeout=timeout,
        **kwargs,
    )


async def run_bg(
    conn: SSHClientConnection,
    quote: QuoteCallable,
    command: str,
    *args: object,
    cwd: Optional[str] = None,
    **kwargs: object,
) -> SSHClientProcess[AnyStr]:
    """
    Create background process.
    :raises asyncssh.ChannelOpenError: An SSH error has occurred.
    """
    if cwd:
        command = f"cd {quote(cwd)}; {command}"
    return await conn.create_process(
        command, *args, **kwargs, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL
    )
