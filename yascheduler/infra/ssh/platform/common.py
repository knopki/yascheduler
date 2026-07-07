#!/usr/bin/env python3
# FILE: yascheduler/infra/ssh/platform/common.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Shared helpers for remote machine operations: command execution.
#   SCOPE: run and run_bg command execution helpers.
#   DEPENDS: M-PLATFORM-PROTOCOL
#   LINKS: M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   run - Run process on SSH connection and wait for exit
#   run_bg - Create background process on SSH connection
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Relocate ProcessInfo dataclass to protocol.py; module now hosts only run/run_bg.
#   PREVIOUS_CHANGE: v1.1.0 - Migrated ProcessInfo from attrs.define to stdlib dataclasses.dataclass; no behavioral change.
# END_CHANGE_SUMMARY
#

from subprocess import DEVNULL
from typing import AnyStr, Optional

from asyncssh.connection import SSHClientConnection
from asyncssh.process import SSHClientProcess, SSHCompletedProcess

from .protocol import QuoteCallable


# START_CONTRACT: run
#   PURPOSE: Run a command on remote via SSH and wait for completion
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { quote: QuoteCallable - shell quoting function } | { command: str - command to run } | { args: object - extra args } | { cwd: Optional[str] - working directory } | { kwargs: object - extra kwargs including timeout, check }
#   OUTPUTS: { SSHCompletedProcess - completed process result }
#   SIDE_EFFECTS: Runs remote command, may raise asyncssh.Error
#   LINKS: M-REMOTE-COMMON
# END_CONTRACT: run
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


# START_CONTRACT: run_bg
#   PURPOSE: Create a background process on remote via SSH without waiting
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { quote: QuoteCallable - shell quoting function } | { command: str - command to run } | { args: object - extra args } | { cwd: Optional[str] - working directory } | { kwargs: object - extra kwargs }
#   OUTPUTS: { SSHClientProcess - background process handle }
#   SIDE_EFFECTS: Starts remote process, may raise asyncssh.ChannelOpenError
#   LINKS: M-REMOTE-COMMON
# END_CONTRACT: run_bg
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
