# FILE: yascheduler/entrypoints/cli/check_status.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: yastatus CLI command — query and display task status with optional remote output and convergence.
#   SCOPE: check_status command + argparse + single query-phase UoW + default/info/json/view renderers + connection-params resolver + remote output + convergence helpers.
#   DEPENDS: M-ENTRYPOINTS-CONFIG, M-DI, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS, M-DOMAIN-MODEL, M-SHARED, M-APPLICATION-UOW, M-ENTRYPOINTS-CLI-ARGS
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS, M-DI, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   check_status - Sync entry point: asyncio.run(_check_status_async(argv))
#   _check_status_async - Parse flags, query tasks via DI, dispatch renderer, exit 0/1/2
#   _parse_status_args - Parse yastatus argparse flags (mutex renderers, -o requires -v)
#   _query_tasks - Conditional task query within the single query-phase UoW
#   _render_default - AiiDA-compatible default renderer (<id>   <STATUS>)
#   _render_info - Tab-separated one-line-per-task renderer
#   _render_json - Raw-domain-values JSON (9 fields)
#   _render_view - Verbose renderer: SSH tail of OUTPUT, optional convergence snippet
#   _resolve_conn_params - Resolve SSH conn params mirroring orchestrator._connect_machine_consumer
#   _display_remote_output - Connect via SSHMachineRepository / SSHMachineOperations, tail OUTPUT file
#   _download_convergence_snippet - Download OUTPUT file via SFTP
#   _parse_convergence - Parse CRYSTAL output for convergence info
#   _ConnParams - Frozen SSH connection params DTO
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Carry TaskId through the query/render path (add-task-id-identity): _query_tasks wraps [TaskId(j) for j in args.jobs] before list_by_jobs (CLI-internal int→TaskId wrap, same pattern as the facade); _render_json extracts task.task_id.value (json.dumps would raise TypeError on a TaskId); _render_default/_render_info render via __str__ unchanged.
#   PREVIOUS_CHANGE: v1.2.0 - session-based-machine-handle: _download_convergence_snippet takes MachineSession instead of (repository, operations, ip); _display_remote_output uses session directly (session.path, session.quote, session.run_full) and returns (session, remote_folder, repository) triple; _render_view unpacking updated.
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from yascheduler.domain import TaskId, TaskStatus
from yascheduler.entrypoints import CLIDeps, Config, make_cli_deps
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.infra import SSHMachineRepository
from yascheduler.infra.ssh.keys import list_private_keys

from .args import add_config_arg, add_log_level_arg

if TYPE_CHECKING:
    from yascheduler.application import AbstractUnitOfWork
    from yascheduler.domain import MachineSession, Node, Task


# START_CONTRACT: _parse_status_args
#   PURPOSE: Parse yastatus CLI flags — mutex renderers (-v/-i/--json) plus -o (requires -v) and -j filter.
#   INPUTS: { argv: list[str] | None - optional argv for argparse, None reads sys.argv }
#   OUTPUTS: { argparse.Namespace - parsed flags }
#   SIDE_EFFECTS: argparse may call sys.exit on --help/error (exit 0/2); parser.error exits 2 for -o-without--v.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _parse_status_args
def _parse_status_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yastatus",
        description="Show status of tasks",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        nargs="*",
        type=int,
        default=None,
        help="Filter to the given job ids (composes with any renderer)",
    )
    # The three renderers are mutually exclusive; none means the default AiiDA-compatible renderer.
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument(
        "-v",
        "--view",
        action="store_true",
        default=False,
        help="Verbose renderer: tail remote OUTPUT (and optional convergence)",
    )
    mutex.add_argument(
        "-i",
        "--info",
        action="store_true",
        default=False,
        help="Tab-separated one-line-per-task renderer",
    )
    mutex.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit JSON with raw domain values (no display transformations)",
    )
    # -o modifies -v, so it is OUTSIDE the mutex group; the body-check below enforces the dependency.
    parser.add_argument(
        "-o",
        "--convergence",
        action="store_true",
        default=False,
        help="Download + parse a CRYSTAL convergence snippet (requires --view)",
    )
    add_config_arg(parser)
    add_log_level_arg(parser, default="WARNING")
    # START_BLOCK_PARSE_ARGS
    args = parser.parse_args(argv)
    if args.convergence and not args.view:
        parser.error("--convergence requires --view")
    # END_BLOCK_PARSE_ARGS
    return args


# START_CONTRACT: _query_tasks
#   PURPOSE: Conditional task query — list_by_jobs when -j is given, else list_by_status({RUNNING, TO_DO}).
#   INPUTS: { uow: AbstractUnitOfWork - open query-phase UoW, args: argparse.Namespace - parsed flags }
#   OUTPUTS: { list[Task] - tasks matching the filter, in repository order }
#   SIDE_EFFECTS: One read within the UoW; no commit.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL
# END_CONTRACT: _query_tasks
async def _query_tasks(uow: AbstractUnitOfWork, args: argparse.Namespace) -> list[Task]:
    # START_BLOCK_QUERY
    if args.jobs:
        # argparse yields list[int]; wrap to TaskId before crossing into the
        # repository (same int→TaskId marshalling pattern as the facade).
        return await uow.tasks.list_by_jobs(job_ids=[TaskId(j) for j in args.jobs])
    return await uow.tasks.list_by_status(
        statuses={TaskStatus.RUNNING, TaskStatus.TO_DO}
    )
    # END_BLOCK_QUERY


# START_CONTRACT: _render_default
#   PURPOSE: AiiDA-compatibility default renderer — emit <task_id><ws><STATUS_NAME> per task.
#   INPUTS: { tasks: list[Task] }
#   OUTPUTS: { None - prints one line per task to stdout }
#   SIDE_EFFECTS: Writes to stdout. Do NOT decorate: the AiiDA scheduler plugin parses this via
#                 `for job_id, status in job.split()` (exactly 2 elements per line) and maps STATUS_NAME
#                 through _MAP_STATUS_YASCHEDULER (keys {TO_DO, RUNNING, DONE}).
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _render_default
def _render_default(tasks: list[Task]) -> None:
    for task in tasks:
        print(f"{task.task_id}   {task.status.name}")


# START_CONTRACT: _render_info
#   PURPOSE: Tab-separated one-line-per-task renderer (task_id, status, label, allocated_ip).
#   INPUTS: { tasks: list[Task] }
#   OUTPUTS: { None - prints one tab-separated line per task to stdout }
#   SIDE_EFFECTS: Writes to stdout. Not used by the AiiDA plugin; free to change.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _render_info
def _render_info(tasks: list[Task]) -> None:
    for task in tasks:
        print(
            "task_id={}\tstatus={}\tlabel={}\tip={}".format(
                task.task_id,
                task.status.name,
                task.label,
                task.allocated_ip or "-",
            )
        )


# START_CONTRACT: _render_json
#   PURPOSE: Render tasks as a JSON list of 9-field objects with raw domain values (no display transformations).
#   INPUTS: { tasks: list[Task], nodes_by_ip: dict[str, Node] - node lookup by allocated ip }
#   OUTPUTS: { str - json.dumps(list_of_objects) }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _render_json
def _render_json(tasks: list[Task], nodes_by_ip: dict[str, Node]) -> str:
    # START_BLOCK_RENDER_JSON
    objects = []
    for task in tasks:
        node = nodes_by_ip.get(task.allocated_ip) if task.allocated_ip else None
        objects.append(
            {
                "task_id": task.task_id.value,
                "status": task.status.name,
                "label": task.label,
                "allocated_ip": task.allocated_ip,
                "port": node.port if node else None,
                "cloud": node.cloud if node else None,
                "engine": task.context.engine,
                "local_folder": task.context.local_folder,
                "remote_folder": task.context.remote_folder,
            }
        )
    return json.dumps(objects)
    # END_BLOCK_RENDER_JSON


@dataclass(frozen=True)
class _ConnParams:
    username: str
    port: int
    jump_host: str | None
    jump_username: str | None


# START_CONTRACT: _resolve_conn_params
#   PURPOSE: Resolve the four SSH connection parameters for a node — username/port from the node, jump host
#          from the matching cloud (prefix == node.cloud) or the config.remote fallback.
#   INPUTS: { node: Node, config: Config }
#   OUTPUTS: { _ConnParams - (username, port, jump_host, jump_username) }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-ENTRYPOINTS-CONFIG
#   NOTE: Mirrors orchestrator._connect_machine_consumer:209-214; duplicated (not shared) because the shape
#         differs (orchestrator connects inline; check_status returns a params object for the gateway call).
#         Promotion to a shared helper awaits a third consumer. The `break` below stops at the first matching
#         cloud; the orchestrator lacks it but the prefix match is unique so behavior is equivalent.
# END_CONTRACT: _resolve_conn_params
def _resolve_conn_params(node: Node, config: Config) -> _ConnParams:
    # START_BLOCK_RESOLVE_JUMP
    jump_host = config.remote.jump_host
    jump_username = config.remote.jump_username
    for cloud in config.clouds:
        if cloud.prefix == node.cloud:
            if cloud.jump_host and cloud.jump_username:
                jump_host, jump_username = cloud.jump_host, cloud.jump_username
            break
    # END_BLOCK_RESOLVE_JUMP
    return _ConnParams(
        username=node.username,
        port=node.port,
        jump_host=jump_host,
        jump_username=jump_username,
    )


# START_CONTRACT: _download_convergence_snippet
#   PURPOSE: Download the remote OUTPUT file via SFTP into a local temp path for convergence parsing.
#   INPUTS: { session: MachineSession, remote_folder: str, local_path: Path }
#   OUTPUTS: { bool - True on success, False on OSError (e.g. missing remote file) }
#   SIDE_EFFECTS: Opens an SFTP channel and writes to local_path.
#   LINKS: M-SSH-SESSION
# END_CONTRACT: _download_convergence_snippet
async def _download_convergence_snippet(
    session: MachineSession,
    remote_folder: str,
    local_path: Path,
) -> bool:
    """Download OUTPUT file via SFTP for convergence parsing. Returns True on success."""
    try:
        r_output = session.path(remote_folder) / "OUTPUT"
        async with session.open_sftp() as sftp:
            await sftp.get([str(r_output)], local_path)
        return True
    except OSError:
        return False


# START_CONTRACT: _parse_convergence
#   PURPOSE: Parse a CRYSTAL OUTPUT snippet into a human-readable convergence + optgeom summary string.
#   INPUTS: { filepath: Path - local path to a downloaded OUTPUT snippet }
#   OUTPUTS: { str - formatted convergence/optgeom lines, or the CRYSTOUT_Error message on parse failure }
#   SIDE_EFFECTS: Reads filepath; deferred-imports numpy/pycrystal (optional scientific deps) inside the body.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _parse_convergence
def _parse_convergence(filepath: Path) -> str:
    """Parse CRYSTAL output file for convergence and geometry optimization info."""
    from numpy import nan  # pyright: ignore[reportMissingImports]
    from pycrystal import (  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]
        CRYSTOUT,
        CRYSTOUT_Error,
    )

    try:
        calc = CRYSTOUT(filepath)
    except CRYSTOUT_Error as err:
        return str(err)

    output_lines = ""
    if calc.info["convergence"]:
        output_lines += str(calc.info["convergence"]) + "\n"
    if calc.info["optgeom"]:
        for n in range(len(calc.info["optgeom"])):
            try:
                ncycles = calc.info["ncycles"][n]
            except IndexError:
                ncycles = "^"
            output_lines += (
                "{:8f}".format(calc.info["optgeom"][n][0] or nan)
                + "  "
                + "{:8f}".format(calc.info["optgeom"][n][1] or nan)
                + "  "
                + "{:8f}".format(calc.info["optgeom"][n][2] or nan)
                + "  "
                + "{:8f}".format(calc.info["optgeom"][n][3] or nan)
                + "  "
                + "E={:12f}".format(calc.info["optgeom"][n][4] or nan)
                + " eV"
                + "  "
                + f"({ncycles})"
                + "\n"
            )
    return output_lines


# START_CONTRACT: _display_remote_output
#   PURPOSE: Connect to the remote machine via repository, tail the OUTPUT file, return (session, remote_folder) or None.
#   INPUTS: { task: Task, conn_params: _ConnParams - resolved SSH params, config: Config }
#   OUTPUTS: { tuple[MachineSession, str, SSHMachineRepository] | None - (session, remote_folder, repository) or None if skipped }
#   SIDE_EFFECTS: Connects via SSH, reads remote file, prints to stdout.
#   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
# END_CONTRACT: _display_remote_output
async def _display_remote_output(
    task: Task, conn_params: _ConnParams, config: Config
) -> tuple[MachineSession, str, SSHMachineRepository] | None:
    """Connect to machine via repository, display tail of remote OUTPUT."""
    if not task.allocated_ip:
        print("NO ALLOCATED IP")
        return None
    ip = task.allocated_ip
    repository = SSHMachineRepository()
    try:
        session = await repository.connect(
            ip=ip,
            username=conn_params.username,
            client_keys=list_private_keys(config.local.keys_dir),
            port=conn_params.port,
            jump_host=conn_params.jump_host,
            jump_username=conn_params.jump_username,
        )
    except Exception:
        print("CAN'T CONNECT")
        return None
    remote_folder = task.context.remote_folder
    if not remote_folder:
        print("OUTDATED TASK, SKIPPING")
        await repository.disconnect(ip)
        return None
    if session.is_closed:
        print("CAN'T CONNECT")
        return None
    r_output = session.path(remote_folder) / "OUTPUT"
    result = await session.run_full(
        f"tail -n15 {session.quote(str(r_output))}",
    )
    if result.returncode:
        print("OUTDATED TASK, SKIPPING")
    else:
        print(result.stdout)
    return session, remote_folder, repository


# START_CONTRACT: _render_view
#   PURPOSE: Verbose renderer — for each RUNNING task with an allocated IP, resolve conn params, print a
#          header, tail remote OUTPUT, optionally download+parse a convergence snippet into a tempfile.
#   INPUTS: { tasks: list[Task], nodes_by_ip: dict[str, Node], config: Config, fetch_convergence: bool, deps: CLIDeps }
#   OUTPUTS: { Path | None - path to the convergence snippet tempfile (cleaned by the caller), or None }
#   SIDE_EFFECTS: Connects to remote machines via SSH, writes a tempfile, prints to stdout.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-ENTRYPOINTS-CONFIG
# END_CONTRACT: _render_view
async def _render_view(
    tasks: list[Task],
    nodes_by_ip: dict[str, Node],
    config: Config,
    fetch_convergence: bool,
    deps: CLIDeps,  # noqa: ARG001 (passed per design D8; nodes are pre-fetched, no re-query needed)
) -> Path | None:
    running = [t for t in tasks if t.status == TaskStatus.RUNNING]
    snippet: Path | None = None
    # START_BLOCK_CREATE_SNIPPET
    if fetch_convergence:
        fd, name = tempfile.mkstemp(suffix=".tmp")  # noqa: ASYNC241
        os.close(fd)  # noqa: ASYNC230
        snippet = Path(name)
    # END_BLOCK_CREATE_SNIPPET
    try:
        # START_BLOCK_ITERATE_RUNNING
        for task in running:
            node = nodes_by_ip.get(task.allocated_ip) if task.allocated_ip else None
            if node is not None:
                conn_params = _resolve_conn_params(node, config)
            else:
                conn_params = _ConnParams(
                    username=config.remote.username,
                    port=22,
                    jump_host=config.remote.jump_host,
                    jump_username=config.remote.jump_username,
                )
            cloud_str = node.cloud if node and node.cloud else ""
            print(
                "." * 50
                + "ID{} {} at {}@{}:{}:{}".format(
                    task.task_id,
                    task.label,
                    conn_params.username,
                    task.allocated_ip or "",
                    cloud_str,
                    task.context.remote_folder or "",
                )
            )
            conn = await _display_remote_output(task, conn_params, config)
            if conn is None:
                continue
            session, remote_folder, repository = conn
            try:
                if fetch_convergence and snippet is not None:
                    success = await _download_convergence_snippet(
                        session, remote_folder, snippet
                    )
                    if success:
                        output = _parse_convergence(snippet)
                        if output:
                            print(output)
            finally:
                await repository.disconnect(session.ip)
        # END_BLOCK_ITERATE_RUNNING
    except Exception:
        # Self-clean the snippet on exception so the temp file never leaks; re-raise to the caller's
        # top-level handler (which prints "Error: ..." and exits 1).
        if snippet is not None and os.path.exists(snippet):  # noqa: ASYNC240
            os.unlink(snippet)  # noqa: ASYNC230
        raise
    return snippet


# START_CONTRACT: _check_status_async
#   PURPOSE: Query and display task status (default/info/json/view), optionally tailing remote output and
#          parsing convergence. Exit 0 on success, 1 on runtime failure, 2 on argparse error.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - prints to stdout; calls sys.exit(1) on failure }
#   SIDE_EFFECTS: Opens ONE short query-phase UoW (closed before any SSH), reads config, may connect via SSH,
#                 writes/removes a convergence tempfile in view mode.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS, M-DI, M-APPLICATION-UOW, M-SSH-REPOSITORY, M-SSH-OPERATIONS
# END_CONTRACT: _check_status_async
async def _check_status_async(argv: list[str] | None) -> None:
    snippet: Path | None = None
    # START_BLOCK_HANDLE_FAILURE
    try:
        args = _parse_status_args(argv)
        # START_BLOCK_CONFIGURE_LOGGER
        root = logging.getLogger()
        root.setLevel(logging.getLevelName(args.log_level))
        if not root.handlers:
            root.addHandler(logging.StreamHandler(sys.stderr))
        # END_BLOCK_CONFIGURE_LOGGER

        config = parse_config(args.config)
        deps = make_cli_deps(config)
        # QUERY PHASE — one short UoW, closed before any SSH work.
        async with deps.uow_factory() as uow:
            tasks = await _query_tasks(uow, args)
            nodes_by_ip: dict[str, Node] = {}
            if args.view or args.json:
                ips = [t.allocated_ip for t in tasks if t.allocated_ip]
                if ips:
                    nodes_by_ip = await uow.nodes.get_by_ips(ips)
        # RENDER PHASE — no DB connection held during SSH.
        if args.view:
            snippet = await _render_view(
                tasks, nodes_by_ip, config, bool(args.convergence), deps
            )
        elif args.info:
            _render_info(tasks)
        elif args.json:
            print(_render_json(tasks, nodes_by_ip))
        else:
            _render_default(tasks)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE
    finally:
        if snippet is not None and os.path.exists(snippet):  # noqa: ASYNC240
            os.unlink(snippet)  # noqa: ASYNC230


# START_CONTRACT: check_status
#   PURPOSE: Sync entry point — run _check_status_async via asyncio.run (no @to_sync; CLI entry points have no async caller).
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - delegates to asyncio.run }
#   SIDE_EFFECTS: Starts a fresh event loop via asyncio.run.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: check_status
def check_status(argv: list[str] | None = None) -> None:
    asyncio.run(_check_status_async(argv))


if __name__ == "__main__":
    check_status()
