"""Shared helpers for remote machine operations: command execution."""
# region MODULE_CONTRACT
# PURPOSE: Run and run_bg command execution helpers for SSH remote calls.
# SCOPE: run (run-and-wait), run_bg (background process) — both use SSHClientConnection.
# DEPENDENCIES: USES API: asyncssh (SSHClientConnection, SSHClientProcess, SSHCompletedProcess)
# KEYWORDS: run, run_bg, ssh, command execution, remote
# endregion MODULE_CONTRACT

from __future__ import annotations

from subprocess import DEVNULL
from typing import TYPE_CHECKING, AnyStr

if TYPE_CHECKING:
    from asyncssh.connection import SSHClientConnection
    from asyncssh.process import SSHClientProcess, SSHCompletedProcess

    from .protocol import QuoteCallable

__all__ = ["run", "run_bg"]


# region FUNC_run
# PURPOSE: Run a command on remote via SSH and wait for completion.
async def run(
    conn: SSHClientConnection,
    quote: QuoteCallable,
    command: str,
    *args: object,
    cwd: str | None = None,
    **kwargs: object,
) -> SSHCompletedProcess:
    """Run process and wait for exit.

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


# endregion FUNC_run


# region FUNC_run_bg
# PURPOSE: Create a background process on remote via SSH without waiting.
async def run_bg(
    conn: SSHClientConnection,
    quote: QuoteCallable,
    command: str,
    *args: object,
    cwd: str | None = None,
    **kwargs: object,
) -> SSHClientProcess[AnyStr]:
    """Create background process.

    :raises asyncssh.ChannelOpenError: An SSH error has occurred.
    """
    if cwd:
        command = f"cd {quote(cwd)}; {command}"
    return await conn.create_process(
        command,
        *args,
        **kwargs,
        stdin=DEVNULL,
        stdout=DEVNULL,
        stderr=DEVNULL,
    )


# endregion FUNC_run_bg
