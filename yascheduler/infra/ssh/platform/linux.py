#!/usr/bin/env python3
# FILE: yascheduler/infra/ssh/platform/linux.py
# VERSION: 1.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Linux-specific remote commands: package install, process listing, CPU detection.
#   SCOPE: Linux setup_node, get_cpu_cores, list_processes, pgrep implementations.
#   DEPENDS: M-DOMAIN-ENGINE, M-PLATFORM-PROTOCOL
#   LINKS: M-PLATFORM-ADAPTERS, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   linux_get_cpu_cores - Get number of CPU cores via getconf
#   linux_list_processes - List running processes via ps
#   linux_pgrep - Find processes matching a pattern via pgrep
#   deploy_local_files - Upload local binary files via SFTP
#   deploy_local_archive - Upload and extract local archive via SFTP
#   deploy_remote_archive - Download and extract remote archive via wget
#   linux_deploy_engines - Deploy all engines for a node
#   log_mpi_version - Log MPI version info
#   linux_setup_node - Setup generic Linux node
#   linux_setup_deb_node - Setup Debian-like node with apt packages
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Migrate from logging.getLogger to get_logger factory; logging.Logger → YaLogger type annotations; remove # type: ignore[attr-defined].
#   PREVIOUS_CHANGE: v1.2.0 - Import ProcessInfo from .protocol (not .common); list_processes/pgrep return AsyncGenerator[ProcessInfo, None].
# END_CHANGE_SUMMARY

import re
from collections.abc import AsyncGenerator, Sequence
from pathlib import PurePath
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
from yascheduler.shared import get_logger

from .protocol import OuterRunCallable, ProcessInfo, QuoteCallable

if TYPE_CHECKING:
    from yascheduler.shared import YaLogger


# START_CONTRACT: linux_get_cpu_cores
#   PURPOSE: Get number of CPU cores on remote Linux via getconf
#   INPUTS: { run: OuterRunCallable - async command runner }
#   OUTPUTS: { int - number of CPU cores (defaults to 1 on error) }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_get_cpu_cores
async def linux_get_cpu_cores(run: OuterRunCallable) -> int:
    """
    Get number of CPU cores
    :raises asyncssh.Error: An SSH error has occurred.
    """
    r = await run("getconf NPROCESSORS_ONLN 2> /dev/null || getconf _NPROCESSORS_ONLN")
    try:
        return int(r.stdout and r.stdout.strip() or "1")
    except ValueError:
        return 1


# START_CONTRACT: linux_list_processes
#   PURPOSE: Yield running process info from remote Linux via ps
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { query: Optional[str] - optional pgrep query prefix }
#   OUTPUTS: { AsyncGenerator[ProcessInfo, None] - stream of process info }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_list_processes
_log = get_logger("M-PLATFORM-LINUX")


async def linux_list_processes(
    conn: SSHClientConnection, query: Optional[str] = None
) -> AsyncGenerator[ProcessInfo, None]:
    """
    Returns information about all running processes
    :raises asyncssh.Error: An SSH error has occurred.
    """
    columns = ["pid", "comm", "args"]
    columns_part = ",".join([f"{x}:255" for x in columns])
    if query:
        ps_cmd = " ".join([query, "| xargs --no-run-if-empty ps -o", columns_part])
    else:
        ps_cmd = f"ps -eo {columns_part}"
    _log.trace("LIST_PROCESSES", cmd=ps_cmd)
    async with conn.create_process(ps_cmd) as proc:
        await proc.stdout.readline()  # skip headers
        line_count = 0
        skipped_broken = 0
        skipped_self = 0
        async for line in proc.stdout:
            line_count += 1
            parts = list(
                map(lambda x: x.strip(), filter(None, str(line).split(" " * 10)))
            )
            if len(parts) < 3:
                skipped_broken += 1
                _log.trace(
                    "BROKEN_LINE",
                    line=line_count,
                    parts=len(parts),
                    raw=line,
                )
                continue
            if parts[2].startswith(f"bash -c {ps_cmd}"):
                skipped_self += 1
                continue
            _log.trace(
                "YIELD",
                pid=parts[0],
                comm=parts[1],
                args=parts[2][:80],
            )
            yield ProcessInfo(int(parts[0]), *parts[1:3])
        _log.trace(
            "DONE",
            lines=line_count,
            broken=skipped_broken,
            self_skip=skipped_self,
        )


# START_CONTRACT: linux_pgrep
#   PURPOSE: Find processes matching a pattern via pgrep and yield their info
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { quote: QuoteCallable - shell quoting function } | { pattern: Union[str, Pattern[str]] - match pattern } | { full: bool - match against full cmdline if True }
#   OUTPUTS: { AsyncGenerator[ProcessInfo, None] - stream of matching process info }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_pgrep
async def linux_pgrep(
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
    pgrep_query = " ".join(
        filter(None, ["pgrep", "-f" if full else None, quote(str_pattern)])
    )
    async for x in linux_list_processes(conn, query=pgrep_query):
        yield x


# START_CONTRACT: deploy_local_files
#   PURPOSE: Upload local binary files to remote via SFTP
#   INPUTS: { sftp: SFTPClient - SFTP connection } | { engine_dir: PurePath - destination directory } | { files: Sequence[PurePath] - local file paths } | { log: "YaLogger | None" - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Uploads files to remote machine
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: deploy_local_files
async def deploy_local_files(
    sftp: SFTPClient,
    engine_dir: PurePath,
    files: Sequence[PurePath],
    log: "YaLogger | None" = None,
) -> None:
    "Uploading binary from local; requires broadband connection"
    lpaths = list(map(str, files))
    if log:
        log.trace("UPLOAD", dir=engine_dir, files=", ".join(lpaths))
    await sftp.put(lpaths, engine_dir, preserve=True)


# START_CONTRACT: deploy_local_archive
#   PURPOSE: Upload local archive via SFTP and extract via tar on remote
#   INPUTS: { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - shell quoting function } | { sftp: SFTPClient - SFTP connection } | { engine_dir: PurePath - destination directory } | { archive: PurePath - local archive path } | { log: "YaLogger | None" - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Uploads archive, extracts it, removes archive file on remote
#   LINKS: M-REMOTE-LINUX
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
    await run(f"tar xfv {quote(str(archive.name))}", cwd=str(engine_dir), check=True)
    await sftp.remove(rpath)


# START_CONTRACT: deploy_remote_archive
#   PURPOSE: Download remote archive via wget and extract via tar on remote
#   INPUTS: { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - shell quoting function } | { sftp: SFTPClient - SFTP connection } | { engine_dir: PurePath - destination directory } | { url: str - download URL } | { log: "YaLogger | None" - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Downloads archive from URL, extracts it, removes archive file on remote
#   LINKS: M-REMOTE-LINUX
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
    name = "archive.tar.gz"
    rpath = engine_dir / name
    if log:
        log.trace("DOWNLOAD", url=url, path=str(rpath))
    await run(f"wget {quote(url)} -O {quote(name)}", cwd=str(engine_dir), check=True)
    if log:
        log.trace("EXTRACT", name=name)
    await run(f"tar xfv {quote(str(name))}", cwd=str(engine_dir), check=True)
    await sftp.remove(rpath)


# START_CONTRACT: linux_deploy_engines
#   PURPOSE: Deploy all engines for a node by iterating engine repository and dispatching deploy strategies
#   INPUTS: { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - shell quoting function } | { sftp: SFTPClient - SFTP connection } | { engines: EngineRepository - engine definitions } | { engines_dir: PurePath - base engines directory } | { log: "YaLogger | None" - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates engine directories, uploads files/archives, downloads remote archives
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_deploy_engines
async def linux_deploy_engines(
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
        engine_dir = engines_dir / engine.name
        await sftp.makedirs(engine_dir, exist_ok=True)
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


# START_CONTRACT: log_mpi_version
#   PURPOSE: Log MPI version info from remote via mpirun
#   INPUTS: { run: OuterRunCallable - async command runner } | { log: "YaLogger | None" - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Runs mpirun on remote, logs version string
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: log_mpi_version
async def log_mpi_version(run: OuterRunCallable, log: "YaLogger | None" = None) -> None:
    r = await run("mpirun --allow-run-as-root -V", check=True)
    if not r.returncode and log:
        log.trace("VERSION", version=str(r.stdout or "").split("\n")[0])


# START_CONTRACT: linux_setup_node
#   PURPOSE: Setup generic Linux node by deploying engines via SFTP
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - shell quoting function } | { engines: EngineRepository - engine definitions } | { engines_dir: PurePath - base engines directory } | { log: "YaLogger | None" - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates SFTP client, deploys all engines
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_setup_node
async def linux_setup_node(
    conn: SSHClientConnection,
    run: OuterRunCallable,
    quote: QuoteCallable,
    engines: EngineRepository,
    engines_dir: PurePath,
    log: "YaLogger | None" = None,
) -> None:
    "Setup generic linux node"
    async with conn.start_sftp_client() as sftp:
        await linux_deploy_engines(run, quote, sftp, engines, engines_dir, log)


# START_CONTRACT: linux_setup_deb_node
#   PURPOSE: Setup Debian-like node with apt package installation and engine deployment
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { run: OuterRunCallable - async command runner } | { quote: QuoteCallable - shell quoting function } | { engines: EngineRepository - engine definitions } | { engines_dir: PurePath - base engines directory } | { log: "YaLogger | None" - logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Runs apt update/upgrade/install, logs MPI version, deploys engines via SFTP
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_setup_deb_node
async def linux_setup_deb_node(
    conn: SSHClientConnection,
    run: OuterRunCallable,
    quote: QuoteCallable,
    engines: EngineRepository,
    engines_dir: PurePath,
    log: "YaLogger | None" = None,
) -> None:
    "Setup debian-like node"

    is_root = conn.get_extra_info("username") == "root"
    sudo_prefix = "" if is_root else "sudo "
    apt_cmd = f"{sudo_prefix}apt-get -o DPkg::Lock::Timeout=600 -y"
    pkgs = engines.get_platform_packages()

    if log:
        log.trace("UPGRADE")
    await run(f"{apt_cmd} update", check=True)
    await run(f"{apt_cmd} upgrade", check=True)
    if pkgs:
        if log:
            log.trace("INSTALL", packages=" ".join(pkgs))
        await run(f"{apt_cmd} install {' '.join(pkgs)}", check=True)
    if [x for x in pkgs if "mpi" in x]:
        await log_mpi_version(run, log)

    async with conn.start_sftp_client() as sftp:
        await linux_deploy_engines(run, quote, sftp, engines, engines_dir, log)
