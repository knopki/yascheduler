# FILE: yascheduler/infra/cli/check_status.py
# VERSION: 1.1.2
# START_MODULE_CONTRACT
#   PURPOSE: yastatus CLI command — query and display task status with optional remote output.
#   SCOPE: check_status command + arg parser, display formatters, remote output + convergence helpers.
#   DEPENDS: M-DI, M-CONFIG, M-SSH-GATEWAY, M-DOMAIN-MODEL, M-SHARED
#   LINKS: M-CLI-COMMANDS, M-DI, M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   check_status - Show status of tasks
#   _parse_status_args - Parse yastatus CLI arguments
#   _print_status_info - Display task info in verbose format
#   _print_status_default - Display tasks in default tabular format
#   _print_status_view - Display detailed view with remote output and convergence
#   _display_remote_output - Connect via SSHMachineGateway, tail OUTPUT file
#   _download_convergence_snippet - Download OUTPUT file via SFTP
#   _parse_convergence - Parse CRYSTAL output for convergence info
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.2 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.1.1 - Import to_sync/CONFIG_FILE from yascheduler.shared facade (shared-kernel-extraction).
# END_CHANGE_SUMMARY
# FIXME: split adapter and application layer (business logic)

import argparse
import os
from pathlib import Path
from typing import Optional

from yascheduler.config import Config
from yascheduler.di import make_cli_deps
from yascheduler.domain import Task, TaskStatus
from yascheduler.infra import SSHMachineGateway
from yascheduler.shared import CONFIG_FILE, to_sync


def _parse_status_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show status of tasks")
    parser.add_argument("-j", "--jobs", required=False, default=None, nargs="*")
    parser.add_argument(
        "-v", "--view", required=False, default=None, nargs="?", type=bool, const=True
    )
    parser.add_argument(
        "-o",
        "--convergence",
        required=False,
        default=None,
        nargs="?",
        type=bool,
        const=True,
        help="needs -v option",
    )
    parser.add_argument(
        "-i", "--info", required=False, default=None, nargs="?", type=bool, const=True
    )
    return parser.parse_args()


def _print_status_info(tasks: list[Task]) -> None:
    """Display task info in verbose format."""
    for task in tasks:
        print(
            "task_id={}\tstatus={}\tlabel={}\tip={}".format(
                task.task_id,
                task.status.name,
                task.label,
                task.allocated_ip or "-",
            )
        )


def _print_status_default(tasks: list[Task]) -> None:
    """Display tasks in default tabular format."""
    for task in tasks:
        print(f"{task.task_id}   {task.status.name}")


async def _download_convergence_snippet(
    gateway: SSHMachineGateway, ip: str, remote_folder: str, local_path: Path
) -> bool:
    """Download OUTPUT file via SFTP for convergence parsing. Returns True on success."""
    try:
        r_output = gateway.get_path(ip)(remote_folder) / "OUTPUT"
        async with gateway.get_sftp(ip) as sftp:
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
#   PURPOSE: Connect to remote machine via gateway, tail OUTPUT file, return (gateway, ip, remote_folder) or None
#   INPUTS: { task: Task, ssh_user: str, config: Config }
#   OUTPUTS: { Optional[tuple[SSHMachineGateway, str, str]] - (gateway, ip, remote_folder) or None if skipped }
#   SIDE_EFFECTS: Connects via SSH, reads remote file, prints to stdout
#   LINKS: M-SSH-GATEWAY
# END_CONTRACT: _display_remote_output
async def _display_remote_output(
    task: Task, ssh_user: str, config: Config
) -> Optional[tuple[SSHMachineGateway, str, str]]:
    """Connect to machine via gateway, display tail of remote OUTPUT."""
    if not task.allocated_ip:
        print("NO ALLOCATED IP")
        return None
    ip = task.allocated_ip
    gateway = SSHMachineGateway()
    try:
        await gateway.connect(
            ip=ip,
            username=ssh_user,
            client_keys=config.local.get_private_keys(),
        )
    except Exception:
        print("CAN'T CONNECT")
        return None
    remote_folder = task.context.remote_folder
    if not remote_folder:
        print("OUTDATED TASK, SKIPPING")
        await gateway.disconnect(ip)
        return None
    r_output = gateway.get_path(ip)(remote_folder) / "OUTPUT"
    state = gateway._get_machine_state(ip)  # FIXME: use of private method
    if state is None:
        print("CAN'T CONNECT")
        return None
    result = await gateway.run_full(
        state.machine,
        f"tail -n15 {gateway.get_quote(ip)(str(r_output))}",
    )
    if result.returncode:
        print("OUTDATED TASK, SKIPPING")
    else:
        print(result.stdout)
    return gateway, ip, remote_folder


# START_CONTRACT: _print_status_view
#   PURPOSE: Display detailed view of running tasks with remote output and optional convergence info
#   INPUTS: { tasks: list[Task], config: Config, fetch_convergence: bool }
#   OUTPUTS: { Optional[Path] - Path to convergence snippet file, or None }
#   SIDE_EFFECTS: Connects to remote machines via SSH, writes temp file
#   LINKS: M-CLI-COMMANDS, M-DI, M-SSH-GATEWAY
# END_CONTRACT: _print_status_view
async def _print_status_view(
    tasks: list[Task], config: Config, fetch_convergence: bool = False
) -> Optional[Path]:
    deps = make_cli_deps(config)
    running = [t for t in tasks if t.status == TaskStatus.RUNNING]

    local_calc_snippet: Optional[Path] = None

    async with deps.uow_factory() as uow:
        ips = [t.allocated_ip for t in running if t.allocated_ip]
        nodes_by_ip = await uow.nodes.get_by_ips(ips) if ips else {}

    for task in running:
        ssh_user = None
        for c in config.clouds:
            ssh_user = c.username
        ssh_user = ssh_user or config.remote.username
        node = nodes_by_ip.get(task.allocated_ip) if task.allocated_ip else None
        cloud_str = node.cloud if node and node.cloud else ""
        print(
            "." * 50
            + "ID{} {} at {}@{}:{}:{}".format(
                task.task_id,
                task.label,
                ssh_user,
                task.allocated_ip or "",
                cloud_str,
                task.context.remote_folder or "",
            )
        )
        conn = await _display_remote_output(task, ssh_user, config)
        if conn is None:
            continue
        gateway, ip, remote_folder = conn

        if fetch_convergence:
            local_calc_snippet = Path(config.local.data_dir, "local_calc_snippet.tmp")
            success = await _download_convergence_snippet(
                gateway, ip, remote_folder, local_calc_snippet
            )
            if success:
                output = _parse_convergence(local_calc_snippet)
                if output:
                    print(output)

        await gateway.disconnect(ip)

    return local_calc_snippet


# START_CONTRACT: check_status
#   PURPOSE: Query and display task status, optionally with remote output and convergence info
#   INPUTS: { None - reads CLI args via argparse }
#   OUTPUTS: { None - prints status/output to stdout }
#   SIDE_EFFECTS: Connects to DB via UoW, optionally reads remote files via SSH/SFTP
#   LINKS: M-CLI-COMMANDS, M-DI, M-APPLICATION-UOW, M-SSH-GATEWAY
# END_CONTRACT: check_status
@to_sync
async def check_status() -> None:
    args = _parse_status_args()
    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)

    local_parsing_ready = bool(args.convergence)
    local_calc_snippet = None

    async with deps.uow_factory() as uow:
        if args.jobs:
            tasks: list[Task] = await uow.tasks.list_by_jobs(job_ids=args.jobs)
        else:
            tasks = await uow.tasks.list_by_status(
                statuses={TaskStatus.RUNNING, TaskStatus.TO_DO}
            )

        if args.view:
            local_calc_snippet = await _print_status_view(
                tasks, config, local_parsing_ready
            )
        elif args.info:
            _print_status_info(tasks)
        else:
            _print_status_default(tasks)

    if local_calc_snippet and os.path.exists(local_calc_snippet):  # noqa: ASYNC240
        os.unlink(local_calc_snippet)
