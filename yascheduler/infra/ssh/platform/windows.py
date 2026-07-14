#!/usr/bin/env python3
# FILE: yascheduler/infra/ssh/platform/windows.py
# VERSION: 1.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Windows-specific remote commands: engine deployment, process listing.
#   SCOPE: Windows setup_node, list_processes implementations.
#   DEPENDS: M-DOMAIN-ENGINE, M-PLATFORM-PROTOCOL
#   LINKS: M-PLATFORM-ADAPTERS, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MyPureWindowsPath - Custom PureWindowsPath that handles leading slashes correctly
#   windows_quote - Quote a string for PowerShell
#   windows_get_cpu_cores - Get number of CPU cores via PowerShell
#   windows_list_processes - List running processes via Get-CimInstance
#   windows_pgrep - Find processes matching a pattern
#   deploy_local_files - Upload local binary files via SFTP
#   deploy_local_archive - Upload and extract local archive via Expand-Archive
#   deploy_remote_archive - Download and extract remote archive via Invoke-WebRequest
#   windows_deploy_engines - Deploy all engines for a node
#   windows_setup_node - Setup Windows node
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Migrate from logging.Logger to YaLogger type annotations; remove # type: ignore[attr-defined].
#   PREVIOUS_CHANGE: v1.2.0 - Import ProcessInfo from .protocol (not .common); list_processes/pgrep return AsyncGenerator[ProcessInfo, None].
# END_CHANGE_SUMMARY

import asyncio
import json
import re
from collections.abc import AsyncGenerator, Sequence
from pathlib import PurePath, PureWindowsPath
from re import Pattern
from typing import TYPE_CHECKING, Optional, Union

from asyncssh.connection import SSHClientConnection
from asyncssh.sftp import SFTPClient

from yascheduler.domain import (
    EngineRepository,
    LocalArchiveDeploy,
    LocalFilesDeploy,
    RemoteArchiveDeploy,
)

from .protocol import OuterRunCallable, ProcessInfo, QuoteCallable

if TYPE_CHECKING:
    from yascheduler.shared import YaLogger


class MyPureWindowsPath(PureWindowsPath):
    # START_CONTRACT: MyPureWindowsPath._parse_args
    #   PURPOSE: Custom path parsing to prevent leading slash on Windows paths
    #   INPUTS: { path: - path string to parse }
    #   OUTPUTS: { tuple - (drv, root, parts) parsed path components }
    #   SIDE_EFFECTS: None
    #   LINKS: M-REMOTE-WINDOWS
    # END_CONTRACT: MyPureWindowsPath._parse_args
    @classmethod
    def _parse_args(cls, path: str) -> tuple[str, str, list[str]]:
        drv, root, parts = cls._parse_args(path)
        # prevent leading slash like \C:\Users\user
        if not drv and root == "\\" and len(parts) > 2 and parts[0] == "\\":
            drv = parts[1]
            parts = parts[1:]
        # prevent eating first part when parsing PurePath instance
        if len(parts) > 1 and drv == parts[0] and not root:
            root = "\\"

        return drv, root, parts


# START_CONTRACT: windows_quote
#   PURPOSE: Quote a string for PowerShell by wrapping in single quotes and escaping embedded single quotes
#   INPUTS: { s: str - string to quote }
#   OUTPUTS: { str - PowerShell-quoted string }
#   SIDE_EFFECTS: None
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: windows_quote
def windows_quote(s: str) -> str:
    return "'{}'".format(str(s).replace("'", "''"))


# START_CONTRACT: windows_get_cpu_cores
#   PURPOSE: Get number of CPU cores on remote Windows via PowerShell
#   INPUTS: { run: OuterRunCallable - async command runner }
#   OUTPUTS: { int - number of CPU cores (defaults to 1 on error) }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: windows_get_cpu_cores
async def windows_get_cpu_cores(run: OuterRunCallable) -> int:
    """
    Get number of CPU cores
    :raises asyncssh.Error: An SSH error has occurred.
    """
    res = await run("[environment]::ProcessorCount")
    try:
        return int(res.stdout and res.stdout.strip() or "1")
    except ValueError:
        return 1


# START_CONTRACT: windows_list_processes
#   PURPOSE: Yield running process info from remote Windows via Get-CimInstance
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { query: Optional[str] - optional PowerShell where filter }
#   OUTPUTS: { AsyncGenerator[ProcessInfo, None] - stream of process info }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: windows_list_processes
async def windows_list_processes(
    conn: SSHClientConnection, query: Optional[str] = None
) -> AsyncGenerator[ProcessInfo, None]:
    """
    Returns information about all running processes
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
                assert isinstance(data["pid"], int)
                assert isinstance(data["name"], str)
                assert isinstance(data["command"], str)
                # skip self
                if (
                    data["name"] == "powershell.exe"
                    and "Get-CimInstance Win32_Process" in data["command"]
                ):
                    continue
                yield ProcessInfo(**data)
            except Exception:
                continue


# START_CONTRACT: windows_pgrep
#   PURPOSE: Find processes matching a pattern on Windows via where-filter and yield their info
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { quote: QuoteCallable - PowerShell quoting function } | { pattern: Union[str, Pattern[str]] - match pattern } | { full: bool - match against name or full cmdline if True }
#   OUTPUTS: { AsyncGenerator[ProcessInfo, None] - stream of matching process info }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: windows_pgrep
async def windows_pgrep(
    conn: SSHClientConnection,
    quote: QuoteCallable,
    pattern: Union[str, Pattern[str]],
    full: bool = True,
) -> AsyncGenerator[ProcessInfo, None]:
    """
    Returns information about running processes, that name matches a pattern.
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


# START_CONTRACT: deploy_local_files
#   PURPOSE: Upload local binary files to remote Windows via SFTP
#   INPUTS: { sftp: SFTPClient - SFTP connection } | { engine_dir: PurePath - destination directory } | { files: Sequence[PurePath] - local file paths } | { log: Optional[ "YaLogger"] - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Uploads files to remote machine in parallel
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: deploy_local_files
async def deploy_local_files(
    sftp: SFTPClient,
    engine_dir: PurePath,
    files: Sequence[PurePath],
    log: "YaLogger | None" = None,
) -> None:
    "Uploading binary from local; requires broadband connection"

    async def upload(src: PurePath, dst: PurePath) -> None:
        if log:
            log.trace("UPLOAD", src=str(src), dst=str(dst))
        await sftp.put([str(src)], str(dst))

    await asyncio.gather(*map(lambda x: upload(x, engine_dir / x.name), files))


# START_CONTRACT: deploy_local_archive
#   PURPOSE: Upload local archive via SFTP and extract via Expand-Archive on remote Windows
#   INPUTS: { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - PowerShell quoting function } | { sftp: SFTPClient - SFTP connection } | { engine_dir: PurePath - destination directory } | { archive: PurePath - local archive path } | { log: Optional[ "YaLogger"] - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Uploads archive, extracts it, removes archive file on remote
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: deploy_local_archive
async def deploy_local_archive(
    run: OuterRunCallable,
    quote: QuoteCallable,
    sftp: SFTPClient,
    engine_dir: PurePath,
    archive: PurePath,
    log: "YaLogger | None" = None,
) -> None:
    """
    Upload local archive.
    Binary may be gzipped, without subfolders, with an arbitrary archive name.
    """
    rpath = engine_dir / archive.name
    if log:
        log.trace("UPLOAD", name=archive.name, path=str(rpath))
    await sftp.put([str(archive)], engine_dir)
    if log:
        log.trace("EXTRACT", name=archive.name)
    await run(
        f"""Expand-Archive {quote(str(rpath))} `
            -DestinationPath {quote(str(engine_dir))} `
            -Force""",
        check=True,
    )
    await sftp.remove(rpath)


# START_CONTRACT: deploy_remote_archive
#   PURPOSE: Download remote archive via Invoke-WebRequest and extract via Expand-Archive on remote Windows
#   INPUTS: { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - PowerShell quoting function } | { sftp: SFTPClient - SFTP connection } | { engine_dir: PurePath - destination directory } | { url: str - download URL } | { log: Optional[ "YaLogger"] - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Downloads archive from URL, extracts it, removes archive file on remote
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: deploy_remote_archive
async def deploy_remote_archive(
    run: OuterRunCallable,
    quote: QuoteCallable,
    sftp: SFTPClient,
    engine_dir: PurePath,
    url: str,
    log: "YaLogger | None" = None,
) -> None:
    """
    Downloading binary from a trusted non-public address.
    Binary may be gzipped, without subfolders, with an arbitrary archive name.
    """
    name = "archive.zip"
    rpath = engine_dir / name
    if log:
        log.trace("DOWNLOAD", url=url, path=str(rpath))
    await run(
        f"""Invoke-WebRequest -Uri {quote(url)} `
            -OutFile {quote(str(rpath))} -Force""",
        check=True,
    )
    if log:
        log.trace("EXTRACT", name=name)
    await run(
        f"""Expand-Archive {quote(str(rpath))} `
            -DestinationPath {quote(str(engine_dir))} `
            -Force""",
        check=True,
    )
    await sftp.remove(rpath)


# START_CONTRACT: windows_deploy_engines
#   PURPOSE: Deploy all engines for a Windows node by iterating engine repository and dispatching deploy strategies
#   INPUTS: { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - PowerShell quoting function } | { sftp: SFTPClient - SFTP connection } | { engines: EngineRepository - engine definitions } | { engines_dir: PurePath - base engines directory } | { log: Optional[ "YaLogger"] - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates engine directories, uploads files/archives, downloads remote archives
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: windows_deploy_engines
async def windows_deploy_engines(
    run: OuterRunCallable,
    quote: QuoteCallable,
    sftp: SFTPClient,
    engines: EngineRepository,
    engines_dir: PurePath,
    log: "YaLogger | None" = None,
) -> None:
    """
    Setup node for target engines.
    """
    for engine in engines.values():
        if log:
            log.info(f"Setup {engine.name} engine...")
        engine_dir = PureWindowsPath(
            (await sftp.realpath(engines_dir / engine.name))[1:]
        )
        # sftp.makedirs is broken for PureWindowsPath
        await sftp.makedirs(PurePath(engine_dir), exist_ok=True)
        for deployment in engine.deployable:
            if isinstance(deployment, LocalFilesDeploy):
                await deploy_local_files(sftp, engine_dir, deployment.files, log)

            if isinstance(deployment, LocalArchiveDeploy):
                await deploy_local_archive(
                    run, quote, sftp, engine_dir, deployment.file
                )

            if isinstance(deployment, RemoteArchiveDeploy):
                await deploy_remote_archive(
                    run, quote, sftp, engine_dir, deployment.url
                )
        if log:
            log.info(f"Setup of {engine.name} engine is done...")


# START_CONTRACT: windows_setup_node
#   PURPOSE: Setup Windows node by deploying engines via SFTP
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - PowerShell quoting function } | { engines: EngineRepository - engine definitions } | { engines_dir: PurePath - base engines directory } | { log: Optional[ "YaLogger"] - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates SFTP client, deploys all engines on Windows
#   LINKS: M-REMOTE-WINDOWS
# END_CONTRACT: windows_setup_node
async def windows_setup_node(
    conn: SSHClientConnection,
    run: OuterRunCallable,
    quote: QuoteCallable,
    engines: EngineRepository,
    engines_dir: PurePath,
    log: "YaLogger | None" = None,
) -> None:
    "Setup Windows node"
    async with conn.start_sftp_client() as sftp:
        await windows_deploy_engines(run, quote, sftp, engines, engines_dir, log)
