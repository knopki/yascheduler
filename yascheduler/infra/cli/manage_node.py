# FILE: yascheduler/infra/cli/manage_node.py
# VERSION: 1.0.2
# START_MODULE_CONTRACT
#   PURPOSE: yasetnode CLI command — add, soft-remove, or hard-remove nodes.
#   SCOPE: manage_node command + arg parser, node add/remove helpers.
#   DEPENDS: M-DI, M-CONFIG, M-SSH-GATEWAY, M-DOMAIN-MODEL, M-SHARED, M-APPLICATION-UOW
#   LINKS: M-CLI-COMMANDS, M-DI, M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   manage_node - Add/remove nodes from daemon
#   _parse_node_args - Parse yasetnode CLI arguments
#   _remove_node_hard - Hard-remove: mark tasks DONE, delete node
#   _remove_node_soft - Soft-remove: disable or delete node
#   _add_node - Add new node via SSH setup + DB insert
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.2 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.0.1 - Import to_sync/CONFIG_FILE from yascheduler.shared facade (shared-kernel-extraction).
# END_CHANGE_SUMMARY
# FIXME: split adapter and application layer (business logic)

import argparse
from typing import Optional

from yascheduler.application import AbstractUnitOfWork
from yascheduler.config import Config
from yascheduler.di import make_cli_deps
from yascheduler.domain import Node, TaskStatus
from yascheduler.infra import SSHMachineGateway
from yascheduler.shared import CONFIG_FILE, to_sync


def _parse_node_args() -> argparse.Namespace:
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


async def _remove_node_hard(uow: AbstractUnitOfWork, host: str) -> bool:
    """Hard-remove a node: mark associated tasks DONE and remove node record."""
    task_ids = await uow.tasks.list_ids_by_ip_and_status(host, TaskStatus.RUNNING)
    for task_id in task_ids:
        await uow.tasks.update_status(task_id, TaskStatus.DONE)
        print(f"An associated task {task_id} at {host} is now marked done!")

    await uow.nodes.remove(host)
    await uow.commit()
    print(f"Removed host from yascheduler: {host}")
    return True


async def _remove_node_soft(uow: AbstractUnitOfWork, host: str) -> bool:
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
    uow: AbstractUnitOfWork,
    host: str,
    username: str,
    port: int,
    ncpus: Optional[int],
    config: Config,
    skip_setup: bool = False,
) -> None:
    """Add a new node: optionally run setup and create DB record."""
    gateway = SSHMachineGateway()
    await gateway.connect(
        ip=host,
        username=username,
        client_keys=config.local.get_private_keys(),
        engines_dir=config.remote.engines_dir,
        port=port,
    )

    if not skip_setup:
        print("Setup host...")
        await gateway.setup_node(host, config.engines)

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
    await gateway.disconnect(host)
    print(f"Added host to yascheduler: {host}:{port}")


# START_CONTRACT: manage_node
#   PURPOSE: Add, soft-remove, or hard-remove a node from the scheduler
#   INPUTS: { None - reads CLI args via argparse }
#   OUTPUTS: { bool | None - returns True on success, False/None on failure }
#   SIDE_EFFECTS: Modifies DB node records via UoW, optionally runs remote node setup via SSH
#   LINKS: M-CLI-COMMANDS, M-DI, M-APPLICATION-UOW, M-SSH-GATEWAY
# END_CONTRACT: manage_node
@to_sync
async def manage_node() -> Optional[bool]:
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
