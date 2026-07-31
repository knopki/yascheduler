"""Windows-specific remote commands: engine deployment, process listing, CPU detection."""
# region MODULE_CONTRACT
# PURPOSE: Windows-specific remote machine operations — setup_node, get_cpu_cores, process listing, pgrep, engine deployment helpers.
# SCOPE:
# - MyPureWindowsPath custom path class
# - windows_quote, windows_get_cpu_cores, windows_list_processes, windows_pgrep
# - Deploy helpers (deploy_local_files/archive, deploy_remote_archive)
# - windows_deploy_engines, windows_setup_node
# DEPENDENCIES: USES API: asyncssh (SSHClientConnection, SFTPClient)
# KEYWORDS: windows, ssh, remote, deploy, engines, cpu, processes, powershell
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import PurePath, PureWindowsPath
from re import Pattern
from typing import TYPE_CHECKING

from yascheduler.domain import (
    EngineRepository,
    LocalArchiveDeploy,
    LocalFilesDeploy,
    RemoteArchiveDeploy,
)

from .protocol import OuterRunCallable, ProcessInfo, QuoteCallable

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from asyncssh.connection import SSHClientConnection
    from asyncssh.sftp import SFTPClient

__all__ = [
    "MyPureWindowsPath",
    "deploy_local_archive",
    "deploy_local_files",
    "deploy_remote_archive",
    "windows_deploy_engines",
    "windows_get_cpu_cores",
    "windows_list_processes",
    "windows_pgrep",
    "windows_quote",
    "windows_setup_node",
]
logger = logging.getLogger(__name__)


# region CLASS_MyPureWindowsPath
# PURPOSE: Subclass PureWindowsPath so SSH SFTP paths returned by a Windows remote arrive at the session without a spurious leading backslash that breaks SFTP makedirs/file placement.
# INVARIANTS: Subclass of PureWindowsPath. Both pathlib parse hooks are overridden — ``_parse_args`` (<=3.11) and ``_parse_path`` (3.12+) — so each drops a leading \ only when the next part is a drive letter (X:), turning \C:\Users\user into C:\Users\user while leaving \Users\user (absolute, no drive) and \\server\share (UNC) untouched. The ``_parse_args`` branch also re-introduces a \\ root when parsing a PurePath instance whose first part equals its drive.
# RATIONALE:
# - Q: why subclass PureWindowsPath instead of using PureWindowsPath directly?
#   A: asyncssh's SFTP realpath on Windows returns paths with a leading \ (the SFTP protocol's POSIX-like prefix); PureWindowsPath("\C:\Users") parses the leading \ as a UNC root and produces an unusable \C:\Users form — the subclass rewrites the parse to drop the leading \ when the next part looks like a drive letter.
class MyPureWindowsPath(PureWindowsPath):
    """Custom ``PureWindowsPath`` subclass preventing leading slashes."""

    # region METHOD__parse_args
    # PURPOSE: Custom path parsing to drop a spurious leading backslash before a drive letter.
    # NOTE: pathlib <=3.11 calls ``_parse_args``; 3.12+ renamed it to ``_parse_path`` with a
    # different ``parts`` layout (anchor excluded), so both hooks are overridden to keep
    # ``str(MyPureWindowsPath(r"\C:\Users\user")) == "C:\Users\user"`` on every version.
    @classmethod
    def _parse_args(cls, path: str) -> tuple[str, str, list[str]]:
        drv, root, parts = super()._parse_args(path)  # type: ignore[misc]
        # <=3.11: r"\C:\Users\user" -> drv='', root='\\', parts=['\\', 'C:', 'Users', 'user']
        parts_len = 3
        if (
            not drv
            and root == "\\"
            and len(parts) >= parts_len
            and parts[0] == "\\"
            and re.fullmatch(r"[A-Za-z]:", parts[1])
        ):
            drv = parts[1]
            parts = parts[1:]
        # prevent eating first part when parsing PurePath instance
        if len(parts) > 1 and drv == parts[0] and not root:
            root = "\\"
        return drv, root, parts

    # endregion METHOD__parse_args

    # region METHOD__parse_path
    # PURPOSE: 3.12+ hook; same normalization as ``_parse_args`` for the new parser layout.
    @classmethod
    def _parse_path(cls, path: str) -> tuple[str, str, list[str]]:
        drv, root, parts = super()._parse_path(path)  # type: ignore[misc]
        # 3.12+: r"\C:\Users\user" -> drv='', root='\\', parts=['C:', 'Users', 'user']
        if not drv and root == "\\" and parts and re.fullmatch(r"[A-Za-z]:", parts[0]):
            drv = parts[0]
            parts = parts[1:]
        return drv, root, parts

    # endregion METHOD__parse_path


# endregion CLASS_MyPureWindowsPath


# region FUNC_windows_quote
# PURPOSE: Quote a string for PowerShell by wrapping in single quotes and escaping embedded single quotes.
def windows_quote(s: str) -> str:
    """Quote a string for PowerShell by wrapping in single quotes and escaping embedded single quotes."""
    return "'{}'".format(str(s).replace("'", "''"))


# endregion FUNC_windows_quote


# region FUNC_windows_get_cpu_cores
# PURPOSE: Get number of CPU cores on remote Windows via PowerShell.
async def windows_get_cpu_cores(run: OuterRunCallable) -> int:
    """Get number of CPU cores.

    :raises asyncssh.Error: An SSH error has occurred.
    """
    res = await run("[environment]::ProcessorCount")
    try:
        return int((res.stdout and res.stdout.strip()) or "1")
    except ValueError:
        return 1


# endregion FUNC_windows_get_cpu_cores


# region FUNC_windows_list_processes
# PURPOSE: Yield running process info from remote Windows via Get-CimInstance.
async def windows_list_processes(
    conn: SSHClientConnection,
    query: str | None = None,
) -> AsyncGenerator[ProcessInfo, None]:
    """Return information about all running processes.

    :raises asyncssh.Error: An SSH error has occurred.
    """
    where_pipe_cmd = f"| ?{{ {query} }}" if query else ""
    get_process_cmd = f"Get-CimInstance Win32_Process {where_pipe_cmd}"
    inline_obj = "@{'pid' = $_.ProcessId; 'name' = $_.Name; 'command' = $_.CommandLine}"
    for_each_cmd = f"%{{ {inline_obj} | ConvertTo-Json -compress }}"
    ps_cmd = f"{get_process_cmd} | {for_each_cmd}"
    async with conn.create_process(ps_cmd) as proc:
        async for line in proc.stdout:
            try:
                data = json.loads(line)
                if not data["command"]:
                    data["command"] = data["name"]
                if not isinstance(data["pid"], int):
                    continue
                if not isinstance(data["name"], str):
                    continue
                if not isinstance(data["command"], str):
                    continue
                # skip self
                if (
                    data["name"] == "powershell.exe"
                    and "Get-CimInstance Win32_Process" in data["command"]
                ):
                    continue
                yield ProcessInfo(**data)
            except Exception:  # noqa: S112
                continue


# endregion FUNC_windows_list_processes


# region FUNC_windows_pgrep
# PURPOSE: Find processes matching a pattern on Windows via where-filter and yield their info.
async def windows_pgrep(
    conn: SSHClientConnection,
    quote: QuoteCallable,
    pattern: str | Pattern[str],
    *,
    full: bool = True,
) -> AsyncGenerator[ProcessInfo, None]:
    """Return information about running processes matching a name pattern.

    If `full`, check match against name or full cmd.
    :raises asyncssh.Error: An SSH error has occurred.
    """
    str_pattern = pattern.pattern if isinstance(pattern, re.Pattern) else pattern
    match_tail = ["-match", quote(str_pattern)]
    name_expr = ["$_.Name", *match_tail]
    cmd_expr = ["$_.CommandLine", *match_tail]
    if full:
        where_expr = " ".join([*name_expr, "-or", *cmd_expr])
    else:
        where_expr = " ".join(name_expr)
    async for x in windows_list_processes(conn, query=where_expr):
        yield x


# endregion FUNC_windows_pgrep


# region FUNC_deploy_local_files
# PURPOSE: Upload local binary files to remote Windows via SFTP.
async def deploy_local_files(
    sftp: SFTPClient,
    engine_dir: PurePath,
    files: Sequence[PurePath],
) -> None:
    """Upload binary from local; requires broadband connection."""

    async def upload(src: PurePath, dst: PurePath) -> None:
        logger.debug("UPLOAD", extra={"src": str(src), "dst": str(dst)})
        await sftp.put([str(src)], str(dst))

    await asyncio.gather(*(upload(x, engine_dir / x.name) for x in files))


# endregion FUNC_deploy_local_files


# region FUNC_deploy_local_archive
# PURPOSE: Upload local archive via SFTP and extract via Expand-Archive on remote Windows.
async def deploy_local_archive(
    run: OuterRunCallable,
    quote: QuoteCallable,
    sftp: SFTPClient,
    engine_dir: PurePath,
    archive: PurePath,
) -> None:
    """Upload local archive.

    Binary may be gzipped, without subfolders, with an arbitrary archive name.
    """
    rpath = engine_dir / archive.name
    logger.debug("UPLOAD", extra={"archive": archive.name, "path": str(rpath)})
    await sftp.put([str(archive)], engine_dir)
    logger.debug("EXTRACT", extra={"archive": archive.name})
    await run(
        f"""Expand-Archive {quote(str(rpath))} `
            -DestinationPath {quote(str(engine_dir))} `
            -Force""",
        check=True,
    )
    await sftp.remove(rpath)


# endregion FUNC_deploy_local_archive


# region FUNC_deploy_remote_archive
# PURPOSE: Download remote archive via Invoke-WebRequest and extract via Expand-Archive on remote Windows.
async def deploy_remote_archive(
    run: OuterRunCallable,
    quote: QuoteCallable,
    sftp: SFTPClient,
    engine_dir: PurePath,
    url: str,
) -> None:
    """Download a binary from a trusted non-public address.

    Binary may be gzipped, without subfolders, with an arbitrary archive name.
    """
    name = "archive.zip"
    rpath = engine_dir / name
    logger.debug("DOWNLOAD", extra={"url": url, "path": str(rpath)})
    await run(
        f"""Invoke-WebRequest -Uri {quote(url)} `
            -OutFile {quote(str(rpath))} -Force""",
        check=True,
    )
    logger.debug("EXTRACT", extra={"archive": name})
    await run(
        f"""Expand-Archive {quote(str(rpath))} `
            -DestinationPath {quote(str(engine_dir))} `
            -Force""",
        check=True,
    )
    await sftp.remove(rpath)


# endregion FUNC_deploy_remote_archive


# region FUNC_windows_deploy_engines
# PURPOSE: Deploy all engines for a Windows node by iterating engine repository and dispatching deploy strategies.
async def windows_deploy_engines(
    run: OuterRunCallable,
    quote: QuoteCallable,
    sftp: SFTPClient,
    engines: EngineRepository,
    engines_dir: PurePath,
) -> None:
    """Set up node for target engines."""
    for engine in engines.values():
        logger.info("Setup %s engine...", engine.name)
        engine_dir = PureWindowsPath(
            (await sftp.realpath(engines_dir / engine.name))[1:],
        )
        # sftp.makedirs is broken for PureWindowsPath
        await sftp.makedirs(PurePath(engine_dir), exist_ok=True)
        for deployment in engine.deployable:
            if isinstance(deployment, LocalFilesDeploy):
                await deploy_local_files(sftp, engine_dir, deployment.files)

            if isinstance(deployment, LocalArchiveDeploy):
                await deploy_local_archive(
                    run,
                    quote,
                    sftp,
                    engine_dir,
                    deployment.file,
                )

            if isinstance(deployment, RemoteArchiveDeploy):
                await deploy_remote_archive(
                    run,
                    quote,
                    sftp,
                    engine_dir,
                    deployment.url,
                )
        logger.info("Setup of %s engine is done...", engine.name)


# endregion FUNC_windows_deploy_engines


# region FUNC_windows_setup_node
# PURPOSE: Setup Windows node by deploying engines via SFTP.
async def windows_setup_node(
    conn: SSHClientConnection,
    run: OuterRunCallable,
    quote: QuoteCallable,
    engines: EngineRepository,
    engines_dir: PurePath,
) -> None:
    """Set up Windows node."""
    async with conn.start_sftp_client() as sftp:
        await windows_deploy_engines(run, quote, sftp, engines, engines_dir)


# endregion FUNC_windows_setup_node
