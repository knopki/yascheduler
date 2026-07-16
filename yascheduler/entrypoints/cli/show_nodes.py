"""yanodes CLI command — list nodes and their running tasks with filter flags and table/JSON output."""
# region MODULE_CONTRACT
# PURPOSE: yanodes CLI command — list nodes and their running tasks with filter flags (enabled/disabled/busy/free/cloud/no-cloud) and table/JSON output.
# SCOPE: show_nodes command — list nodes with filter flags (enabled/disabled, busy/free, cloud/no-cloud) and table/JSON output.
# KEYWORDS: nodes, cli, list, filter, table, json
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yascheduler.domain import NodeId, NodeStatus, TaskId, TaskStatus
from yascheduler.entrypoints import make_cli_deps
from yascheduler.entrypoints.config_parser import parse_config

from .args import add_config_arg, add_log_level_arg

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from yascheduler.application import AbstractUnitOfWork
    from yascheduler.domain import Task

logger = logging.getLogger(__name__)

_DEFAULT_SSH_PORT = 22


@dataclass(frozen=True)
class _NodeView:
    node_id: NodeId
    hostname: str
    port: int
    ncpus: int | None
    enabled: bool
    cloud: str | None
    jump_host: str | None
    jump_port: int
    jump_username: str
    external_id: str | None
    status: NodeStatus
    created_at: datetime
    updated_at: datetime
    task_id: TaskId | None
    label: str | None


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
    # region BLOCK_parse_args
    return parser.parse_args(argv)
    # endregion BLOCK_parse_args


# region FUNC__fetch_nodes_view
# PURPOSE: Read nodes and running tasks within one UoW and join them in memory into a list of _NodeView.
async def _fetch_nodes_view(uow: AbstractUnitOfWork) -> list[_NodeView]:
    # region BLOCK_read_nodes
    logger.debug("READ", extra={"detail": "nodes and running tasks"})
    tasks = await uow.tasks.list_by_status(statuses={TaskStatus.RUNNING})
    nodes = await uow.nodes.list_all()
    # endregion BLOCK_read_nodes
    # region BLOCK_join
    # Single pass O(m) build; the one-RUNNING-task-per-node invariant means a later task
    # on the same node would overwrite, but the invariant forbids that. If it ever relaxes,
    # this becomes a dict[NodeId, list[Task]] and the row/object shape changes together.
    # Keyed by NodeId (was ip) — dup-IP nodes now disambiguated via node_id.
    tasks_by_node_id: dict[NodeId, Task] = {
        t.allocated_node_id: t for t in tasks if t.allocated_node_id is not None
    }
    rows: list[_NodeView] = []
    for node in nodes:
        task = tasks_by_node_id.get(node.node_id)
        rows.append(
            _NodeView(
                node_id=node.node_id,
                hostname=node.hostname,
                port=node.port,
                ncpus=node.ncpus,
                enabled=node.enabled,
                cloud=node.cloud,
                jump_host=node.jump_host,
                jump_port=node.jump_port,
                jump_username=node.jump_username,
                external_id=node.external_id,
                status=node.status,
                created_at=node.created_at,
                updated_at=node.updated_at,
                task_id=task.task_id if task else None,
                label=task.label if task else None,
            ),
        )
    # endregion BLOCK_join
    return rows


# endregion FUNC__fetch_nodes_view


def _filter_rows(rows: list[_NodeView], args: argparse.Namespace) -> list[_NodeView]:
    # region BLOCK_filter
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
    # endregion BLOCK_filter


# region FUNC__render_nodes_table
# PURPOSE: Render rows as a fixed-width text table with display transformations.
def _render_nodes_table(rows: list[_NodeView]) -> str:
    # region BLOCK_render_table
    headers = [
        "NODE_ID",
        "HOSTNAME",
        "PORT",
        "NCPUS",
        "ENABLED",
        "CLOUD",
        "TASK_ID",
        "LABEL",
    ]
    sep = "  "

    def _cells(row: _NodeView) -> list[str]:
        return [
            str(row.node_id),
            row.hostname,
            "-" if row.port == _DEFAULT_SSH_PORT else str(row.port),
            "MAX" if row.ncpus is None else str(row.ncpus),
            "yes" if row.enabled else "no",
            "-" if row.cloud is None else row.cloud,
            "-" if row.task_id is None else str(row.task_id),
            "-" if row.label is None else row.label,
        ]

    all_rows = [headers] + [_cells(r) for r in rows]
    col_widths = [
        max(len(all_rows[i][col_idx]) for i in range(len(all_rows)))
        for col_idx in range(len(headers))
    ]
    lines = [
        sep.join(cell.ljust(width) for cell, width in zip(line, col_widths))
        for line in all_rows
    ]
    return "\n".join(lines)
    # endregion BLOCK_render_table


# endregion FUNC__render_nodes_table


# region FUNC__render_nodes_json
# PURPOSE: Render rows as a JSON list of objects with raw domain values (no display transformations).
def _render_nodes_json(rows: list[_NodeView]) -> str:
    # region BLOCK_render_json
    objects = [
        {
            "node_id": r.node_id.value,
            "hostname": r.hostname,
            "port": r.port,
            "ncpus": r.ncpus,
            "enabled": r.enabled,
            "cloud": r.cloud,
            "jump_host": r.jump_host,
            "jump_port": r.jump_port,
            "jump_username": r.jump_username,
            "external_id": r.external_id,
            "status": r.status.name,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
            "occupied_by": (
                {"task_id": r.task_id.value, "label": r.label}
                if r.task_id is not None
                else None
            ),
        }
        for r in rows
    ]
    return json.dumps(objects, indent=2)
    # endregion BLOCK_render_json


# endregion FUNC__render_nodes_json


# region FUNC__show_nodes_async
# PURPOSE: Parse flags, read nodes+tasks via DI, filter, render, print; exit 0/1/2.
async def _show_nodes_async(argv: list[str] | None) -> None:
    args = _parse_nodes_args(argv)
    # region BLOCK_handle_failure
    try:
        # region BLOCK_configure_logger
        root = logging.getLogger()
        root.setLevel(logging.getLevelName(args.log_level))
        if not root.handlers:
            root.addHandler(logging.StreamHandler(sys.stderr))
        # endregion BLOCK_configure_logger

        config = parse_config(args.config)
        deps = make_cli_deps(config)
        # region BLOCK_orchestrate
        async with deps.uow_factory() as uow:
            rows = await _fetch_nodes_view(uow)
        rows = _filter_rows(rows, args)
        if args.json:
            sys.stdout.write(f"{_render_nodes_json(rows)}\n")
        else:
            sys.stdout.write(f"{_render_nodes_table(rows)}\n")
        # endregion BLOCK_orchestrate
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    # endregion BLOCK_handle_failure


# endregion FUNC__show_nodes_async


# region FUNC_show_nodes
# PURPOSE: Sync entry point — run _show_nodes_async via asyncio.run (no @to_sync; CLI entry points have no async caller).
def show_nodes(argv: list[str] | None = None) -> None:
    """Sync entry point — run _show_nodes_async via asyncio."""
    asyncio.run(_show_nodes_async(argv))


# endregion FUNC_show_nodes

if __name__ == "__main__":
    show_nodes()
