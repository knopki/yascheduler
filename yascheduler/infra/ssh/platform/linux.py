"""Linux-specific remote commands: package install, process listing, CPU detection."""
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

#   LAST_CHANGE: v1.5.0 - Remove injected `log` parameter from all platform functions; bind module-global logger = logging.getLogger(__name__) (rename _log → logger) and use it directly, dropping `if log:` guards; drop vestigial UPGRADE DEBUG trace (carried no extra fields, not asserted in tests).
#   PREVIOUS_CHANGE: v1.4.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...).
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
import re
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
    from pathlib import PurePath

    from asyncssh.connection import SSHClientConnection
    from asyncssh.sftp import SFTPClient

logger = logging.getLogger(__name__)


# START_CONTRACT: linux_get_cpu_cores
#   PURPOSE: Get number of CPU cores on remote Linux via getconf
#   INPUTS: { run: OuterRunCallable - async command runner }
#   OUTPUTS: { int - number of CPU cores (defaults to 1 on error) }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_get_cpu_cores
async def linux_get_cpu_cores(run: OuterRunCallable) -> int:
    """Get number of CPU cores.

    :raises asyncssh.Error: An SSH error has occurred.
    """
    r = await run("getconf NPROCESSORS_ONLN 2> /dev/null || getconf _NPROCESSORS_ONLN")
    try:
        return int((r.stdout and r.stdout.strip()) or "1")
    except ValueError:
        return 1


# START_CONTRACT: linux_list_processes
#   PURPOSE: Yield running process info from remote Linux via ps
#   INPUTS: { conn: SSHClientConnection - SSH connection } | { query: Optional[str] - optional pgrep query prefix }
#   OUTPUTS: { AsyncGenerator[ProcessInfo, None] - stream of process info }
#   SIDE_EFFECTS: Runs command on remote machine.
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: linux_list_processes
async def linux_list_processes(
    conn: SSHClientConnection,
    query: str | None = None,
) -> AsyncGenerator[ProcessInfo, None]:
    """Return information about all running processes.

    :raises asyncssh.Error: An SSH error has occurred.
    """
    columns = ["pid", "comm", "args"]
    columns_part = ",".join([f"{x}:255" for x in columns])
    if query:
        ps_cmd = f"{query} | xargs --no-run-if-empty ps -o {columns_part}"
    else:
        ps_cmd = f"ps -eo {columns_part}"
    logger.debug("LIST_PROCESSES", extra={"cmd": ps_cmd})
    async with conn.create_process(ps_cmd) as proc:
        await proc.stdout.readline()  # skip headers
        line_count = 0
        skipped_broken = 0
        skipped_self = 0
        async for line in proc.stdout:
            line_count += 1
            parts = [x.strip() for x in filter(None, str(line).split(" " * 10))]
            min_parts = 3
            if len(parts) < min_parts:
                skipped_broken += 1
                logger.debug(
                    "BROKEN_LINE",
                    extra={"line": line_count, "parts": len(parts), "raw": line},
                )
                continue
            if parts[2].startswith(f"bash -c {ps_cmd}"):
                skipped_self += 1
                continue
            logger.debug(
                "YIELD",
                extra={"pid": parts[0], "comm": parts[1], "proc_args": parts[2][:80]},
            )
            yield ProcessInfo(int(parts[0]), *parts[1:3])
        logger.debug(
            "DONE",
            extra={
                "lines": line_count,
                "broken": skipped_broken,
                "self_skip": skipped_self,
            },
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
    pattern: str | Pattern[str],
    *,
    full: bool = True,
) -> AsyncGenerator[ProcessInfo, None]:
    """Return information about running processes matching a name pattern.

    If `full`, check match against name or full cmd.
    :raises asyncssh.Error: An SSH error has occurred.
    """
    str_pattern = pattern.pattern if isinstance(pattern, re.Pattern) else pattern
    pgrep_query = " ".join(
        filter(None, ["pgrep", "-f" if full else None, quote(str_pattern)]),
    )
    async for x in linux_list_processes(conn, query=pgrep_query):
        yield x


# START_CONTRACT: deploy_local_files
#   PURPOSE: Upload local binary files to remote via SFTP
#   INPUTS: { sftp: SFTPClient - SFTP connection, engine_dir: PurePath - destination directory, files: Sequence[PurePath] - local file paths }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Uploads files to remote machine
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: deploy_local_files
async def deploy_local_files(
    sftp: SFTPClient,
    engine_dir: PurePath,
    files: Sequence[PurePath],
) -> None:
    """Upload binary from local; requires broadband connection."""
    lpaths = list(map(str, files))
    logger.debug("UPLOAD", extra={"dir": engine_dir, "files": ", ".join(lpaths)})
    await sftp.put(lpaths, engine_dir, preserve=True)


# START_CONTRACT: deploy_local_archive
#   PURPOSE: Upload local archive via SFTP and extract via tar on remote
#   INPUTS: { run: OuterRunCallable - async command runner, quote: QuoteCallable - shell quoting function, sftp: SFTPClient - SFTP connection, engine_dir: PurePath - destination directory, archive: PurePath - local archive path }
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
) -> None:
    """Upload local archive.

    Binary may be gzipped, without subfolders, with an arbitrary archive name.
    """
    rpath = engine_dir / archive.name
    logger.debug("UPLOAD", extra={"archive": archive.name, "path": str(rpath)})
    await sftp.put([str(archive)], engine_dir)
    logger.debug("EXTRACT", extra={"archive": archive.name})
    await run(f"tar xfv {quote(str(archive.name))}", cwd=str(engine_dir), check=True)
    await sftp.remove(rpath)


# START_CONTRACT: deploy_remote_archive
#   PURPOSE: Download remote archive via wget and extract via tar on remote
#   INPUTS: { run: OuterRunCallable - async command runner, quote: QuoteCallable - shell quoting function, sftp: SFTPClient - SFTP connection, engine_dir: PurePath - destination directory, url: str - download URL }
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
) -> None:
    """Download a binary from a trusted non-public address.

    Binary may be gzipped, without subfolders, with an arbitrary archive name.
    """
    name = "archive.tar.gz"
    rpath = engine_dir / name
    logger.debug("DOWNLOAD", extra={"url": url, "path": str(rpath)})
    await run(f"wget {quote(url)} -O {quote(name)}", cwd=str(engine_dir), check=True)
    logger.debug("EXTRACT", extra={"archive": name})
    await run(f"tar xfv {quote(str(name))}", cwd=str(engine_dir), check=True)
    await sftp.remove(rpath)


# START_CONTRACT: linux_deploy_engines
#   PURPOSE: Deploy all engines for a node by iterating engine repository and dispatching deploy strategies
#   INPUTS: { run: OuterRunCallable - async command runner, quote: QuoteCallable - shell quoting function, sftp: SFTPClient - SFTP connection, engines: EngineRepository - engine definitions, engines_dir: PurePath - base engines directory }
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
) -> None:
    """Set up node for target engines."""
    for engine in engines.values():
        logger.info("Setup %s engine...", engine.name)
        engine_dir = engines_dir / engine.name
        await sftp.makedirs(engine_dir, exist_ok=True)
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


# START_CONTRACT: log_mpi_version
#   PURPOSE: Log MPI version info from remote via mpirun
#   INPUTS: { run: OuterRunCallable - async command runner }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Runs mpirun on remote, logs version string
#   LINKS: M-REMOTE-LINUX
# END_CONTRACT: log_mpi_version
async def log_mpi_version(run: OuterRunCallable) -> None:
    """Log MPI version info from remote via mpirun."""
    r = await run("mpirun --allow-run-as-root -V", check=True)
    if not r.returncode:
        logger.debug("VERSION", extra={"version": str(r.stdout or "").split("\n")[0]})


# START_CONTRACT: linux_setup_node
#   PURPOSE: Setup generic Linux node by deploying engines via SFTP
#   INPUTS: { conn: SSHClientConnection - SSH connection, run: OuterRunCallable - async command runner, quote: QuoteCallable - shell quoting function, engines: EngineRepository - engine definitions, engines_dir: PurePath - base engines directory }
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
) -> None:
    """Set up generic linux node."""
    async with conn.start_sftp_client() as sftp:
        await linux_deploy_engines(run, quote, sftp, engines, engines_dir)


# START_CONTRACT: linux_setup_deb_node
#   PURPOSE: Setup Debian-like node with apt package installation and engine deployment
#   INPUTS: { conn: SSHClientConnection - SSH connection, run: OuterRunCallable - async command runner, quote: QuoteCallable - shell quoting function, engines: EngineRepository - engine definitions, engines_dir: PurePath - base engines directory }
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
) -> None:
    """Set up debian-like node."""
    is_root = conn.get_extra_info("username") == "root"
    sudo_prefix = "" if is_root else "sudo "
    apt_cmd = f"{sudo_prefix}apt-get -o DPkg::Lock::Timeout=600 -y"
    pkgs = engines.get_platform_packages()

    await run(f"{apt_cmd} update", check=True)
    await run(f"{apt_cmd} upgrade", check=True)
    if pkgs:
        logger.debug("INSTALL", extra={"packages": " ".join(pkgs)})
        await run(f"{apt_cmd} install {' '.join(pkgs)}", check=True)
    if [x for x in pkgs if "mpi" in x]:
        await log_mpi_version(run)

    async with conn.start_sftp_client() as sftp:
        await linux_deploy_engines(run, quote, sftp, engines, engines_dir)
