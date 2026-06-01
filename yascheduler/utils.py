# FILE: yascheduler/utils.py
# VERSION: 2.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Console scripts for yascheduler: submit, status, init, node management, daemon startup.
#   SCOPE: CLI commands for task submission, status checking, service initialization, node management, daemon startup.
#   DEPENDS: M-CLIENT, M-CONFIG, M-DB, M-REMOTE, M-VARIABLES, M-DI, M-DOMAIN-MODEL
#   LINKS: M-CLIENT, M-DI, M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit - Submit task to yascheduler via AiiDA script
#   check_status - Show status of tasks
#   _print_status_view - Display detailed view with remote output and convergence
#   _display_remote_output - Connect to remote machine, tail OUTPUT file
#   init - Service initialization (systemd/sysv + DB)
#   show_nodes - Show enabled nodes and running tasks
#   manage_node - Add/remove nodes from daemon
#   daemonize - Start yascheduler daemon via make_daemon()
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.2.0 - Extract _display_remote_output from _print_status_view to comply with 60-line function limit.
#   PREVIOUS_CHANGE: v2.1.0 - Refactor check_status, show_nodes, manage_node to use DI/UoW (make_cli_deps + domain ports).
# END_CHANGE_SUMMARY

import argparse
import asyncio
import base64
import logging
import os
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional, Union

from pg8000 import ProgrammingError

from .client import to_sync
from .config import Config
from .db import DB
from .di import make_cli_deps, make_daemon
from .domain.model import Node, Task, TaskStatus
from .remote_machine import RemoteMachine
from .variables import CONFIG_FILE


def _parse_script_metadata(script_text: str) -> dict[str, str]:
    """Parse key=value pairs from script file content."""
    script_params = {}
    for line in script_text.splitlines():
        try:
            k, v = line.split("=")
            script_params[k.strip()] = v.strip()
        except ValueError:
            pass
    return script_params


def _read_input_files(engine, local_folder: str) -> dict[str, str]:
    """Read input files specified by engine config, return dict of filename -> content."""
    metadata: dict[str, str] = {}
    for input_file in engine.input_files:
        path = Path(local_folder, input_file)
        try:
            metadata[input_file] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            with open(path, "rb") as f:
                metadata[input_file] = base64.b64encode(f.read()).decode("ascii")
    return metadata


# START_CONTRACT: submit
#   PURPOSE: Parse AiiDA script file and submit a task via CLIDeps
#   INPUTS: { None - reads CLI args via argparse }
#   OUTPUTS: { None - prints task ID to stdout }
#   SIDE_EFFECTS: Reads script file and input files from disk, creates DB task
#   LINKS: M-UTILS, M-DI
# END_CONTRACT: submit
@to_sync
async def submit() -> None:
    parser = argparse.ArgumentParser(
        description="Submit task to yascheduler via AiiDA script"
    )
    parser.add_argument("script")

    args = parser.parse_args()
    script_file = Path(args.script)
    if not script_file.exists():
        raise ValueError("Script parameter is not a file name")

    logging.captureWarnings(True)
    log = logging.getLogger()
    log.setLevel(logging.WARN)

    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)

    script_params = _parse_script_metadata(script_file.read_text())

    label = script_params.get("LABEL", "AiiDA job")
    metadata: dict[str, Any] = {"local_folder": os.getcwd()}

    engine_name = script_params.get("ENGINE")
    if not engine_name:
        raise ValueError("Script has not defined an engine")

    engine = config.engines.get(engine_name)
    if not engine:
        raise ValueError(f"Engine {engine_name} is not supported")

    metadata.update(_read_input_files(engine, metadata["local_folder"]))

    if "PARENT" in script_params and config.local.webhook_url:
        metadata["webhook_url"] = config.local.webhook_url
        metadata["webhook_custom_params"] = {"parent": script_params["PARENT"]}

    task_id = await deps.submit(label, dict(metadata), engine.name)
    print(str(task_id))


def _parse_status_args():
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
    machine, remote_folder: str, local_path: Path
) -> bool:
    """Download OUTPUT file via SFTP for convergence parsing. Returns True on success."""
    try:
        r_output = machine.path(remote_folder) / "OUTPUT"
        async with machine.sftp() as sftp:
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
#   PURPOSE: Connect to remote machine, tail OUTPUT file, return (machine, remote_folder) or None
#   INPUTS: { task: Task, ssh_user: str, config: Config }
#   OUTPUTS: { Optional[tuple[RemoteMachine, str]] - (machine, remote_folder) or None if skipped }
#   SIDE_EFFECTS: Connects via SSH, reads remote file, prints to stdout
#   LINKS: M-REMOTE
# END_CONTRACT: _display_remote_output
async def _display_remote_output(
    task: Task, ssh_user: str, config: Config
) -> Optional[tuple[RemoteMachine, str]]:
    """Connect to machine, display tail of remote OUTPUT, return (machine, remote_folder) or None."""
    if not task.allocated_ip:
        print("NO ALLOCATED IP")
        return None
    machine = await RemoteMachine.create(
        host=task.allocated_ip,
        username=ssh_user,
        client_keys=config.local.get_private_keys(),
    )
    remote_folder = task.context.remote_folder
    if not remote_folder:
        print("OUTDATED TASK, SKIPPING")
        return None
    r_output = machine.path(remote_folder) / "OUTPUT"
    result = await machine.run(f"tail -n15 {machine.quote(str(r_output))}")
    if result.returncode:
        print("OUTDATED TASK, SKIPPING")
    else:
        print(result.stdout)
    return machine, remote_folder


# START_CONTRACT: _print_status_view
#   PURPOSE: Display detailed view of running tasks with remote output and optional convergence info
#   INPUTS: { tasks: list[Task], config: Config, fetch_convergence: bool }
#   OUTPUTS: { Optional[Path] - Path to convergence snippet file, or None }
#   SIDE_EFFECTS: Connects to remote machines via SSH, writes temp file
#   LINKS: M-UTILS, M-DI, M-REMOTE
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
        machine, remote_folder = conn

        if fetch_convergence:
            local_calc_snippet = Path(config.local.data_dir, "local_calc_snippet.tmp")
            success = await _download_convergence_snippet(
                machine, remote_folder, local_calc_snippet
            )
            if success:
                output = _parse_convergence(local_calc_snippet)
                if output:
                    print(output)

    return local_calc_snippet


# START_CONTRACT: check_status
#   PURPOSE: Query and display task status, optionally with remote output and convergence info
#   INPUTS: { None - reads CLI args via argparse }
#   OUTPUTS: { None - prints status/output to stdout }
#   SIDE_EFFECTS: Connects to DB via UoW, optionally reads remote files via SSH/SFTP
#   LINKS: M-UTILS, M-DI, M-APPLICATION-UOW, M-REMOTE
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

    if local_calc_snippet and os.path.exists(local_calc_snippet):
        os.unlink(local_calc_snippet)


# START_CONTRACT: init
#   PURPOSE: Install systemd or sysv service and initialize the database schema
#   INPUTS: { None - reads config from CONFIG_FILE }
#   OUTPUTS: { None - no return value }
#   SIDE_EFFECTS: Writes service unit files, creates DB tables
#   LINKS: M-UTILS, M-DB
# END_CONTRACT: init
@to_sync
async def init() -> None:
    # service initialization
    install_path = Path(__file__).parent
    # check for systemd (exit status is 0 if there is a process)
    has_systemd = not os.system("pidof systemd")
    if has_systemd:
        _init_systemd(install_path)
    else:
        _init_sysv(install_path)
    await _init_db(install_path)


def _init_systemd(install_path: Path) -> None:
    print("Installing systemd service")
    src_unit_file = install_path / "data/yascheduler.service"
    unit_file = Path("/lib/systemd/system/yascheduler.service")
    if not unit_file.is_file():
        if not os.access(unit_file, os.W_OK):
            print(f"Error: cannot write to {unit_file}")
            return
        daemon_file = install_path / "daemon_systemd.py"
        systemd_script = src_unit_file.read_text("utf-8").replace(
            "%YASCHEDULER_DAEMON_FILE%", str(daemon_file)
        )
        unit_file.write_text(systemd_script, "utf-8")


def _init_sysv(install_path: Path) -> None:
    print("Installing SysV service")
    src_startup_file = install_path / "data/yascheduler.sh"
    startup_file = Path("/etc/init.d/yascheduler")
    if not startup_file.is_file():
        if not os.access(startup_file, os.W_OK):
            print(f"Error: cannot write to {startup_file}")
            return
        daemon_file = install_path / "daemon_sysv.py"
        sysv_script = src_startup_file.read_text("utf-8").replace(
            "%YASCHEDULER_DAEMON_FILE%", str(daemon_file)
        )
        startup_file.write_text(sysv_script, "utf-8")
        os.chmod(startup_file, 0o755)


async def _init_db(install_path: Path) -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    db = await DB.create(config.db, automigrate=False)
    schema = (
        install_path / "adapters" / "persistence" / "sql" / "schema.sql"
    ).read_text()
    try:
        await db.run(schema)
        await db.commit()
        await db.close()
    except ProgrammingError as e:
        if "already exists" in str(e.args[0]):
            print("Database already initialized!")
        raise


# START_CONTRACT: show_nodes
#   PURPOSE: Display all enabled nodes and their currently running tasks
#   INPUTS: { None - reads config from CONFIG_FILE }
#   OUTPUTS: { None - prints node info to stdout }
#   SIDE_EFFECTS: Connects to DB via UoW, reads node and task records
#   LINKS: M-UTILS, M-DI, M-APPLICATION-UOW
# END_CONTRACT: show_nodes
@to_sync
async def show_nodes() -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)

    async with deps.uow_factory() as uow:
        tasks = await uow.tasks.list_by_status(statuses={TaskStatus.RUNNING})
        nodes = await uow.nodes.list_all()
        for node in nodes:
            tmpl = "ip={ip}{port} ncpus={ncpus} enabled={enabled} occupied_by={occ} (task_id={tid}) {cloud}"
            node_tasks = [t for t in tasks if t.allocated_ip == node.ip]
            node_label = "-"
            task_id = "-"
            for x in node_tasks:
                node_label = x.label
                task_id = x.task_id
            msg = tmpl.format(
                ip=node.ip,
                port=f":{node.port}" if node.port != 22 else "",
                ncpus=node.ncpus or "MAX",
                enabled=node.enabled,
                occ=node_label,
                tid=task_id,
                cloud=node.cloud or "",
            )
            print(msg)


def _parse_node_args():
    parser = argparse.ArgumentParser(description="Add nodes to yascheduler daemon")
    parser.add_argument("host", help="[user@]IP[:port][~ncpus]")
    parser.add_argument(
        "--skip-setup",
        required=False,
        default=False,
        nargs="?",
        type=bool,
        const=True,
        help="Skip node setup",
    )
    parser.add_argument(
        "--remove-soft",
        required=False,
        default=None,
        nargs="?",
        type=bool,
        const=True,
        help="Remove IP delayed",
    )
    parser.add_argument(
        "--remove-hard",
        required=False,
        default=None,
        nargs="?",
        type=bool,
        const=True,
        help="Remove IP immediate",
    )
    return parser.parse_args()


async def _remove_node_hard(uow, host: str) -> bool:
    """Hard-remove a node: mark associated tasks DONE and remove node record."""
    task_ids = await uow.tasks.list_ids_by_ip_and_status(host, TaskStatus.RUNNING)
    for task_id in task_ids:
        await uow.tasks.update_status(task_id, TaskStatus.DONE)
        print(f"An associated task {task_id} at {host} is now marked done!")

    await uow.nodes.remove(host)
    await uow.commit()
    print(f"Removed host from yascheduler: {host}")
    return True


async def _remove_node_soft(uow, host: str) -> bool:
    """Soft-remove a node: disable if tasks exist, remove immediately otherwise."""
    task_ids = await uow.tasks.list_ids_by_ip_and_status(host, TaskStatus.RUNNING)
    if task_ids:
        print("A task associated, prevent from assigning the new tasks")
        await uow.nodes.disable(host)
        print(f"Prevented from assigning the new tasks: {host}")
    else:
        print("No tasks associated, remove node immediately")
        await uow.nodes.remove(host)
        print(f"Removed host from yascheduler: {host}")
    await uow.commit()
    return True


async def _add_node(
    uow,
    host: str,
    username: str,
    port: int,
    ncpus: Optional[int],
    config: Config,
    skip_setup: bool = False,
) -> None:
    """Add a new node: optionally run setup and create DB record."""
    machine = await RemoteMachine.create(
        host=host,
        username=username,
        client_keys=config.local.get_private_keys(),
        engines_dir=config.remote.engines_dir,
        port=port,
    )

    if not skip_setup:
        print("Setup host...")
        await machine.setup_node(config.engines)

    await uow.nodes.add(
        Node(
            ip=host,
            port=port,
            username=username,
            ncpus=ncpus or 0,
            enabled=True,
        )
    )
    await uow.commit()
    print(f"Added host to yascheduler: {host}:{port}")


# START_CONTRACT: manage_node
#   PURPOSE: Add, soft-remove, or hard-remove a node from the scheduler
#   INPUTS: { None - reads CLI args via argparse }
#   OUTPUTS: { bool | None - returns True on success, False/None on failure }
#   SIDE_EFFECTS: Modifies DB node records via UoW, optionally runs remote node setup via SSH
#   LINKS: M-UTILS, M-DI, M-APPLICATION-UOW, M-REMOTE
# END_CONTRACT: manage_node
@to_sync
async def manage_node():
    args = _parse_node_args()
    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)

    ncpus = None
    port = 22
    username = config.remote.username
    if "@" in args.host:
        username, args.host = args.host.split("@")
    if "~" in args.host:
        args.host, ncpus = args.host.split("~")
        ncpus = int(ncpus)
    if ":" in args.host:
        args.host, port_str = args.host.rsplit(":", 1)
        port = int(port_str)

    async with deps.uow_factory() as uow:
        already_there = await uow.nodes.get(args.host) is not None
        if already_there and not args.remove_hard and not args.remove_soft:
            print(f"Host already in DB: {args.host}")
            return False

        if not already_there and (args.remove_hard or args.remove_soft):
            print(f"Host NOT in DB: {args.host}")
            return False

        if args.remove_hard:
            return await _remove_node_hard(uow, args.host)

        elif args.remove_soft:
            return await _remove_node_soft(uow, args.host)

        await _add_node(uow, args.host, username, port, ncpus, config, args.skip_setup)


# START_CONTRACT: daemonize
#   PURPOSE: Start the yascheduler daemon with signal handling via make_daemon
#   INPUTS: { log_file: Optional[Union[str, Path]] - path to log file, or None }
#   OUTPUTS: { None - runs the event loop until stopped }
#   SIDE_EFFECTS: Creates Orchestrator via DI, sets up signal handlers, runs event loop
#   LINKS: M-UTILS, M-DI
# END_CONTRACT: daemonize
def daemonize(log_file: Optional[Union[str, Path]] = None) -> None:
    from .scheduler import get_logger

    parser = argparse.ArgumentParser(description="Start yascheduler daemon")
    parser.add_argument(
        "-l",
        "--log-level",
        default="INFO",
        help="set log level",
        choices=logging._levelToName.values(),
    )
    args = parser.parse_args()

    logger = get_logger(log_file, level=logging._nameToLevel[args.log_level])
    config = Config.from_config_parser(CONFIG_FILE)

    async def on_signal(
        orch, shield: Sequence[asyncio.Task], sig: signal.Signals
    ) -> None:
        signame = signal.strsignal(sig)
        logger.info(f"Received signal {signame}")
        if sig in [signal.SIGTERM, signal.SIGINT]:
            await orch.stop()
            shielded = [*shield, asyncio.current_task()]
            tasks = [t for t in asyncio.all_tasks() if t not in shielded]
            logger.info(f"Cancelling {len(tasks)} outstanding tasks")
            [task.cancel() for task in tasks]
            await asyncio.gather(*tasks, return_exceptions=True)
            # Wait 250 ms for the underlying SSL connections to close
            await asyncio.sleep(0.25)
            logger.info("Done")

    async def run() -> None:
        orch = await make_daemon(config, logger)

        loop = asyncio.get_running_loop()
        current_task = asyncio.current_task()

        shielded = [current_task] if current_task else []
        for sig in [signal.SIGTERM, signal.SIGINT]:

            def handler():
                task = on_signal(orch, shielded, sig)  # noqa: B023
                return asyncio.create_task(task)

            loop.add_signal_handler(sig, handler)

        await orch.start()

    to_sync(run)()
