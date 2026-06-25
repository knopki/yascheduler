# FILE: yascheduler/entrypoints/cli/show_nodes.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: yanodes CLI command — list nodes and their running tasks with filter flags and table/JSON output.
#   SCOPE: show_nodes command + argparse + in-memory node-to-task join + table/JSON renderers.
#   DEPENDS: M-DI, M-CONFIG, M-DOMAIN-MODEL, M-SHARED, M-ENTRYPOINTS-CLI-ARGS
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES, M-APPLICATION-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   show_nodes - Sync entry point: asyncio.run(_show_nodes_async(argv))
#   _show_nodes_async - Parse flags, read nodes+tasks via DI, filter, render, print; exit 0/1/2
#   _parse_nodes_args - Parse yanodes argparse flags
#   _fetch_nodes_view - Read nodes+tasks within one UoW, join in memory
#   _filter_rows - AND-compose active filters
#   _render_nodes_table - Fixed-width table with display transformations
#   _render_nodes_json - Raw-domain-values JSON
#   _NodeView - Private CLI-only node+task projection DTO
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - consolidate-daemon-entrypoints: added --config (type=existing_path, default=CONFIG_FILE) and --log-level (default WARNING) via args.py helpers; Config.from_config_parser now reads args.config; root logger level from args.log_level via logging.getLevelName with a StreamHandler→stderr (no basicConfig); converted @to_sync async def show_nodes to def show_nodes(argv): asyncio.run(_show_nodes_async(argv)) + async def _show_nodes_async(argv).
#   PREVIOUS_CHANGE: v1.0.0 - Reimplemented at entrypoints/cli/ in relocate-show-nodes-command: moved from infra/cli/show_nodes.py, added --json/--enabled/--disabled/--busy/--free/--cloud/--no-cloud argparse flags, exit-code contract 0/1/2, fixed-width table + raw-values JSON renderers, in-memory O(n+m) join, _NodeView private DTO.
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yascheduler.config import Config
from yascheduler.domain import TaskStatus
from yascheduler.entrypoints import make_cli_deps

from .args import add_config_arg, add_log_level_arg

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.application import AbstractUnitOfWork
    from yascheduler.domain import Task


@dataclass(frozen=True)
class _NodeView:
    ip: str
    port: int
    ncpus: int
    enabled: bool
    cloud: str | None
    task_id: int | None
    label: str | None


# START_CONTRACT: _parse_nodes_args
#   PURPOSE: Parse yanodes CLI flags plus shared --config and --log-level.
#   INPUTS: { argv: list[str] | None - optional argv for argparse, None reads sys.argv }
#   OUTPUTS: { argparse.Namespace - parsed flags }
#   SIDE_EFFECTS: None — argparse may call sys.exit on --help/error.
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES, M-ENTRYPOINTS-CLI-ARGS
# END_CONTRACT: _parse_nodes_args
def _parse_nodes_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yanodes",
        description="Show nodes and their running tasks",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the default table",
    )
    parser.add_argument(
        "--enabled",
        action="store_true",
        help="Only enabled nodes",
    )
    parser.add_argument(
        "--disabled",
        action="store_true",
        help="Only disabled nodes",
    )
    parser.add_argument(
        "--busy",
        action="store_true",
        help="Only nodes with a running task",
    )
    parser.add_argument(
        "--free",
        action="store_true",
        help="Only nodes without a running task",
    )
    # --cloud and --no-cloud are the ONLY mutex group (design D3):
    # --enabled/--disabled and --busy/--free are subset selectors, not mutex.
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument(
        "--cloud",
        default=None,
        help="Only nodes whose cloud equals NAME (exact match)",
    )
    mutex.add_argument(
        "--no-cloud",
        action="store_true",
        help="Only static nodes (cloud is None)",
    )
    add_config_arg(parser)
    add_log_level_arg(parser, default="WARNING")
    # START_BLOCK_PARSE_ARGS
    args = parser.parse_args(argv)
    # END_BLOCK_PARSE_ARGS
    return args


# START_CONTRACT: _fetch_nodes_view
#   PURPOSE: Read nodes and running tasks within one UoW and join them in memory into a list of _NodeView.
#   INPUTS: { uow: AbstractUnitOfWork - open UoW }
#   OUTPUTS: { list[_NodeView] - one per node, in list_all() order }
#   SIDE_EFFECTS: Two reads within one UoW (nodes + tasks); no commit.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL
#   NOTE: Promotion to application/query_nodes.py awaits a second consumer; today the daemon tracks
#         occupancy via ConnectedMachine/AllocationTracker and the client does not query nodes.
# END_CONTRACT: _fetch_nodes_view
async def _fetch_nodes_view(uow: AbstractUnitOfWork) -> list[_NodeView]:
    # START_BLOCK_READ_NODES
    logging.debug(
        "[ShowNodes][_fetch_nodes_view][READ] reading nodes and running tasks"
    )
    tasks = await uow.tasks.list_by_status(statuses={TaskStatus.RUNNING})
    nodes = await uow.nodes.list_all()
    # END_BLOCK_READ_NODES
    # START_BLOCK_JOIN
    # Single pass O(m) build; the one-RUNNING-task-per-node invariant means a later task
    # on the same ip would overwrite, but the invariant forbids that. If it ever relaxes,
    # this becomes a dict[str, list[Task]] and the row/object shape changes together.
    tasks_by_ip: dict[str, Task] = {
        t.allocated_ip: t for t in tasks if t.allocated_ip is not None
    }
    rows: list[_NodeView] = []
    for node in nodes:
        task = tasks_by_ip.get(node.ip)
        rows.append(
            _NodeView(
                ip=node.ip,
                port=node.port,
                ncpus=node.ncpus,
                enabled=node.enabled,
                cloud=node.cloud,
                task_id=task.task_id if task else None,
                label=task.label if task else None,
            )
        )
    # END_BLOCK_JOIN
    return rows


# START_CONTRACT: _filter_rows
#   PURPOSE: Apply active filters to rows with AND composition.
#   INPUTS: { rows: list[_NodeView], args: argparse.Namespace }
#   OUTPUTS: { list[_NodeView] - rows passing all active filters, order preserved }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES
# END_CONTRACT: _filter_rows
def _filter_rows(rows: list[_NodeView], args: argparse.Namespace) -> list[_NodeView]:
    # START_BLOCK_FILTER
    predicates: list[Callable[[_NodeView], bool]] = []
    if args.enabled and not args.disabled:
        predicates.append(lambda r: r.enabled is True)
    if args.disabled and not args.enabled:
        predicates.append(lambda r: r.enabled is False)
    if args.busy and not args.free:
        predicates.append(lambda r: r.task_id is not None)
    if args.free and not args.busy:
        predicates.append(lambda r: r.task_id is None)
    if args.cloud is not None:
        predicates.append(lambda r: r.cloud == args.cloud)
    if args.no_cloud and args.cloud is None:
        predicates.append(lambda r: r.cloud is None)
    return [r for r in rows if all(pred(r) for pred in predicates)]
    # END_BLOCK_FILTER


# START_CONTRACT: _render_nodes_table
#   PURPOSE: Render rows as a fixed-width text table with display transformations.
#   INPUTS: { rows: list[_NodeView] }
#   OUTPUTS: { str - table text with header + one row per node }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES
# END_CONTRACT: _render_nodes_table
def _render_nodes_table(rows: list[_NodeView]) -> str:
    # START_BLOCK_RENDER_TABLE
    headers = ["IP", "PORT", "NCPUS", "ENABLED", "CLOUD", "TASK_ID", "LABEL"]
    sep = "  "

    def _cells(row: _NodeView) -> list[str]:
        return [
            row.ip,
            "-" if row.port == 22 else str(row.port),
            "MAX" if row.ncpus == 0 else str(row.ncpus),
            "yes" if row.enabled else "no",
            "-" if row.cloud is None else row.cloud,
            "-" if row.task_id is None else str(row.task_id),
            "-" if row.label is None else row.label,
        ]

    all_rows = [headers]
    for r in rows:
        all_rows.append(_cells(r))
    col_widths = [
        max(len(all_rows[i][col_idx]) for i in range(len(all_rows)))
        for col_idx in range(len(headers))
    ]
    lines = [
        sep.join(cell.ljust(width) for cell, width in zip(line, col_widths))
        for line in all_rows
    ]
    return "\n".join(lines)
    # END_BLOCK_RENDER_TABLE


# START_CONTRACT: _render_nodes_json
#   PURPOSE: Render rows as a JSON list of objects with raw domain values (no display transformations).
#   INPUTS: { rows: list[_NodeView] }
#   OUTPUTS: { str - JSON text }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES
# END_CONTRACT: _render_nodes_json
def _render_nodes_json(rows: list[_NodeView]) -> str:
    # START_BLOCK_RENDER_JSON
    objects = [
        {
            "ip": r.ip,
            "port": r.port,
            "ncpus": r.ncpus,
            "enabled": r.enabled,
            "cloud": r.cloud,
            "occupied_by": (
                {"task_id": r.task_id, "label": r.label}
                if r.task_id is not None
                else None
            ),
        }
        for r in rows
    ]
    return json.dumps(objects, indent=2)
    # END_BLOCK_RENDER_JSON


# START_CONTRACT: _show_nodes_async
#   PURPOSE: Parse flags, read nodes+tasks via DI, filter, render, print; exit 0/1/2.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv }
#   OUTPUTS: None - prints to stdout, calls sys.exit on failure.
#   SIDE_EFFECTS: Opens a UoW for reading, prints output, may call sys.exit(1).
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES, M-DI, M-APPLICATION-UOW
# END_CONTRACT: _show_nodes_async
async def _show_nodes_async(argv: list[str] | None) -> None:
    args = _parse_nodes_args(argv)
    # START_BLOCK_HANDLE_FAILURE
    try:
        # START_BLOCK_CONFIGURE_LOGGER
        root = logging.getLogger()
        root.setLevel(logging.getLevelName(args.log_level))
        if not root.handlers:
            root.addHandler(logging.StreamHandler(sys.stderr))
        # END_BLOCK_CONFIGURE_LOGGER

        config = Config.from_config_parser(args.config)
        deps = make_cli_deps(config)
        # START_BLOCK_ORCHESTRATE
        async with deps.uow_factory() as uow:
            rows = await _fetch_nodes_view(uow)
        rows = _filter_rows(rows, args)
        if args.json:
            print(_render_nodes_json(rows))
        else:
            print(_render_nodes_table(rows))
        # END_BLOCK_ORCHESTRATE
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


# START_CONTRACT: show_nodes
#   PURPOSE: Sync entry point — run _show_nodes_async via asyncio.run (no @to_sync; CLI entry points have no async caller).
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv }
#   OUTPUTS: { None - delegates to asyncio.run }
#   SIDE_EFFECTS: Starts a fresh event loop via asyncio.run.
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES
# END_CONTRACT: show_nodes
def show_nodes(argv: list[str] | None = None) -> None:
    asyncio.run(_show_nodes_async(argv))


if __name__ == "__main__":
    show_nodes()
