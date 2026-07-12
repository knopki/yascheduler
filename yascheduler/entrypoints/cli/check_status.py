# FILE: yascheduler/entrypoints/cli/check_status.py
# VERSION: 1.7.0
# START_MODULE_CONTRACT
#   PURPOSE: yastatus CLI command — query and display task status with optional remote output and convergence.
#   SCOPE: check_status command — query and display task status.
#   DEPENDS: M-ENTRYPOINTS-CONFIG, M-DI, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS, M-DOMAIN-MODEL, M-SHARED, M-APPLICATION-UOW, M-ENTRYPOINTS-CLI-ARGS
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS, M-DI, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   check_status - Sync entry point: asyncio.run(_check_status_async(argv))
#   _check_status_async - Parse flags, query tasks, dispatch renderer, exit 0/1/2
#   _parse_status_args - Parse yastatus argparse flags
#   _query_tasks - Conditional task query within single UoW
#   _render_default - AiiDA-compatible default renderer (<id> <STATUS>)
#   _render_info - Tab-separated one-line-per-task renderer
#   _render_json - Raw-domain-values JSON renderer
#   _render_view - Verbose renderer: SSH tail of OUTPUT, optional convergence
#   _display_remote_output - Connect via SSH, tail OUTPUT file
#   _download_convergence_snippet - Download OUTPUT file via SFTP
#   _parse_convergence - Parse CRYSTAL output for convergence info
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - node-owns-connection-identity: _resolve_conn_params / _ConnParams deleted; _display_remote_output drops conn_params; _render_view reads username from node/config directly, not from resolved params. connect passes no jump kwargs — repository reads jump from node.
#   PREVIOUS_CHANGE: v1.8.0 - _render_json node object: ip→hostname + all new node fields (jump_host, jump_port, jump_username, external_id, status, created_at, updated_at); _render_view: node.ip→node.hostname; _display_remote_output: "NO ALLOCATED IP"→"NO ALLOCATED HOSTNAME".
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from yascheduler.domain import NodeId, TaskId, TaskStatus
from yascheduler.entrypoints import CLIDeps, Config, make_cli_deps
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.infra import SSHMachineRepository
from yascheduler.infra.ssh.keys import list_private_keys

from .args import add_config_arg, add_log_level_arg

if TYPE_CHECKING:
    from yascheduler.application import AbstractUnitOfWork
    from yascheduler.domain import MachineSession, Node, Task


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
#   SIDE_EFFECTS: Writes to stdout.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _render_default
def _render_default(tasks: list[Task]) -> None:
    for task in tasks:
        print(f"{task.task_id}   {task.status.name}")


# START_CONTRACT: _render_info
#   PURPOSE: Tab-separated one-line-per-task renderer (task_id, status, label, node_id).
#   INPUTS: { tasks: list[Task] }
#   OUTPUTS: { None - prints one tab-separated line per task to stdout }
#   SIDE_EFFECTS: Writes to stdout.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _render_info
def _render_info(tasks: list[Task]) -> None:
    for task in tasks:
        print(
            "task_id={}\tstatus={}\tlabel={}\tnode_id={}".format(
                task.task_id,
                task.status.name,
                task.label,
                task.allocated_node_id or "-",
            )
        )


# START_CONTRACT: _render_json
#   PURPOSE: Render tasks as a JSON list of objects with raw domain values (no display transformations); nested node object + audit timestamps.
#   INPUTS: { tasks: list[Task], nodes_by_id: dict[NodeId, Node] - node lookup by allocated_node_id }
#   OUTPUTS: { str - json.dumps(list_of_objects) }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_CONTRACT: _render_json
def _render_json(tasks: list[Task], nodes_by_id: dict[NodeId, Node]) -> str:
    # START_BLOCK_RENDER_JSON
    objects = []
    for task in tasks:
        node = (
            nodes_by_id.get(task.allocated_node_id) if task.allocated_node_id else None
        )
        objects.append(
            {
                "task_id": task.task_id.value,
                "status": task.status.name,
                "label": task.label,
                "engine": task.engine,
                "local_folder": task.local_folder,
                "remote_folder": task.remote_folder,
                "created_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
                "node": (
                    {
                        "hostname": node.hostname,
                        "port": node.port,
                        "username": node.username,
                        "cloud": node.cloud,
                        "jump_host": node.jump_host,
                        "jump_port": node.jump_port,
                        "jump_username": node.jump_username,
                        "external_id": node.external_id,
                        "status": node.status.name,
                        "created_at": node.created_at.isoformat(),
                        "updated_at": node.updated_at.isoformat(),
                    }
                    if node is not None
                    else None
                ),
            }
        )
    return json.dumps(objects)
    # END_BLOCK_RENDER_JSON


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
#   INPUTS: { task - for remote_folder, node - resolved node (None skips connect), config - for keys_dir }
#   OUTPUTS: { tuple[MachineSession, str, SSHMachineRepository] | None - (session, remote_folder, repository) or None if skipped }
#   SIDE_EFFECTS: Connects via SSH (session registers under node.node_id), reads remote file, prints to stdout.
#   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
# END_CONTRACT: _display_remote_output
async def _display_remote_output(
    task: Task, node: Node | None, config: Config
) -> tuple[MachineSession, str, SSHMachineRepository] | None:
    """Connect to machine via repository (under node.node_id), display tail of remote OUTPUT."""
    if node is None:
        print("NO ALLOCATED HOSTNAME")
        return None
    repository = SSHMachineRepository()
    try:
        session = await repository.connect(
            node=node,
            client_keys=list_private_keys(config.local.keys_dir),
        )
    except Exception:
        print("CAN'T CONNECT")
        return None
    remote_folder = task.remote_folder
    if not remote_folder:
        print("OUTDATED TASK, SKIPPING")
        await repository.disconnect(session.machine.node_id)
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
#   PURPOSE: Verbose renderer — for each RUNNING task with an allocated node, print a header, tail remote OUTPUT, optionally download+parse a convergence snippet into a tempfile. Connection identity (username, jump) is read from Node (not resolved from CloudConfig).
#   INPUTS: { tasks: list[Task], nodes_by_id: dict[NodeId, Node], config, fetch_convergence, deps: CLIDeps }
#   OUTPUTS: { Path | None - path to the convergence snippet tempfile (cleaned by the caller), or None }
#   SIDE_EFFECTS: Connects to remote machines via SSH, writes a tempfile, prints to stdout.
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-ENTRYPOINTS-CONFIG
# END_CONTRACT: _render_view
async def _render_view(
    tasks: list[Task],
    nodes_by_id: dict[NodeId, Node],
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
            node = (
                nodes_by_id.get(task.allocated_node_id)
                if task.allocated_node_id
                else None
            )
            username = node.username if node is not None else config.remote.username
            cloud_str = node.cloud if node and node.cloud else ""
            print(
                "." * 50
                + "ID{} {} at {}@{}:{}:{}".format(
                    task.task_id,
                    task.label,
                    username,
                    node.hostname if node else "",
                    cloud_str,
                    task.remote_folder or "",
                )
            )
            conn = await _display_remote_output(task, node, config)
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
                await repository.disconnect(session.machine.node_id)
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
#   SIDE_EFFECTS: Opens query-phase UoW, reads config, may connect via SSH, writes/removes convergence tempfile.
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
            nodes_by_id: dict[NodeId, Node] = {}
            if args.view or args.json:
                node_ids = [t.allocated_node_id for t in tasks if t.allocated_node_id]
                if node_ids:
                    nodes_by_id = await uow.nodes.get_by_ids(node_ids)
        # RENDER PHASE — no DB connection held during SSH.
        if args.view:
            snippet = await _render_view(
                tasks, nodes_by_id, config, bool(args.convergence), deps
            )
        elif args.info:
            _render_info(tasks)
        elif args.json:
            print(_render_json(tasks, nodes_by_id))
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
