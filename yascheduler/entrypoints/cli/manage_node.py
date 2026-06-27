# FILE: yascheduler/entrypoints/cli/manage_node.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: yasetnode CLI command — add, soft-remove, or hard-remove nodes via per-helper UoW (+ SSH gateway on the add path).
#   SCOPE: manage_node command + argparse + host-spec parser + node add/remove helpers (each helper owns its UoW).
#   DEPENDS: M-ENTRYPOINTS-CONFIG, M-DI, M-DOMAIN-MODEL, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS, M-SHARED, M-APPLICATION-UOW, M-ENTRYPOINTS-CLI-ARGS
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE, M-DI, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-APPLICATION-UOW, M-SSH-KEYS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   manage_node - Sync entry point: asyncio.run(_manage_node_async(argv))
#   _manage_node_async - Add/soft-remove/hard-remove a node; validation UoW read-only, dispatch to per-helper UoW; exit 0/1/2
#   HostSpec - Frozen parsed host spec (host, username, port, ncpus)
#   _parse_host_spec - argparse type: parse [user@]host[:port][~ncpus] grammar
#   _parse_node_args - argparse → Namespace (prog="yasetnode", flags, mutex group)
#   _remove_node_hard - Hard-remove: own UoW, mark RUNNING tasks DONE, remove node, commit, print
#   _remove_node_soft - Soft-remove: own UoW, disable (if tasks) or remove node, commit, print
#   _add_node - Add node: own UoW, connect, optional setup, insert, commit, print; try/finally disconnect
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - _add_node calls list_private_keys(config.local.keys_dir) from M-SSH-KEYS instead of config.local.get_private_keys() (ssh-keys-extraction-vastai-parser-fix).
#   PREVIOUS_CHANGE: v1.2.1 - post-review fix: added StreamHandler→stderr guard (`if not log.handlers:`) so --log-level DEBUG produces visible output (was relying on logging.lastResort at WARNING only).
#   PREVIOUS_CHANGE: v1.2.0 - consolidate-daemon-entrypoints: added --config (type=existing_path, default=CONFIG_FILE) and --log-level (default WARNING) via args.py helpers; Config.from_config_parser now reads args.config; root logger level from args.log_level via logging.getLevelName; converted @to_sync async def manage_node to def manage_node(argv): asyncio.run(_manage_node_async(argv)) + async def _manage_node_async(argv).
#   PREVIOUS_CHANGE: v1.1.0 - Per-helper UoW (design D18): validation read uses a short read-only UoW closed before dispatch; each mutate helper opens its OWN UoW via deps.uow_factory(), commits, and prints inside it. Eliminates the double-commit footgun of a single shared async-with UoW with commits scattered across helpers. Accepted TOCTOU window between validation and dispatch (single-operator CLI; benign non-corrupting failure modes).
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from yascheduler.domain import Node, TaskStatus
from yascheduler.entrypoints import CLIDeps, Config, make_cli_deps
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.infra import SSHMachineOperations, SSHMachineRepository
from yascheduler.infra.ssh.keys import list_private_keys

from .args import add_config_arg, add_log_level_arg


@dataclass(frozen=True)
class HostSpec:
    """Parsed host spec from the yasetnode positional argument.

    ``username`` and ``ncpus`` use ``None`` as the "unset / unlimited" sentinel;
    the caller resolves ``username`` from config and encodes ``ncpus`` as ``0``
    in the ``Node`` record when ``None``.
    """

    host: str
    username: str | None
    port: int
    ncpus: int | None


# START_CONTRACT: _parse_host_spec
#   PURPOSE: argparse type — parse [user@]host[:port][~ncpus] into a frozen HostSpec; validate grammar and ranges.
#   INPUTS: { s: str - raw host-spec string from argparse }
#   OUTPUTS: { HostSpec - parsed spec with parser-applied port=22 and ncpus=None defaults }
#   SIDE_EFFECTS: None — raises argparse.ArgumentTypeError on malformed input (argparse surfaces as exit 2).
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_CONTRACT: _parse_host_spec
def _parse_host_spec(s: str) -> HostSpec:
    raw = s

    # START_BLOCK_PARSE_USER
    at_count = s.count("@")
    if at_count > 1:
        raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
    username: str | None = None
    if at_count == 1:
        user_part, _, s = s.partition("@")
        if not user_part:
            raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
        username = user_part
    # END_BLOCK_PARSE_USER

    # START_BLOCK_PARSE_NCPUS
    tilde_count = s.count("~")
    if tilde_count > 1:
        raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
    ncpus: int | None = None
    if tilde_count == 1:
        host_part, _, ncpus_part = s.partition("~")
        if not ncpus_part:
            raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
        try:
            n = int(ncpus_part)
        except ValueError:
            raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}") from None
        if n < 0:
            raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
        s = host_part
        ncpus = None if n == 0 else n
    # END_BLOCK_PARSE_NCPUS

    # START_BLOCK_PARSE_HOST_AND_PORT
    if s.startswith("["):
        close = s.find("]")
        if close == -1:
            raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
        host = s[1:close]
        remainder = s[close + 1 :]
        if remainder == "":
            port = 22
        elif remainder.startswith(":") and ":" not in remainder[1:]:
            port_str = remainder[1:]
            try:
                port = int(port_str)
            except ValueError:
                raise argparse.ArgumentTypeError(
                    f"malformed host spec: {raw!r}"
                ) from None
        else:
            raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
    else:
        colon_count = s.count(":")
        if colon_count > 1:
            # Unbracketed IPv6 is ambiguous against :port — require brackets.
            raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
        if colon_count == 1:
            host, _, port_str = s.partition(":")
            try:
                port = int(port_str)
            except ValueError:
                raise argparse.ArgumentTypeError(
                    f"malformed host spec: {raw!r}"
                ) from None
        else:
            host = s
            port = 22

    if not host:
        raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError(f"malformed host spec: {raw!r}")
    # END_BLOCK_PARSE_HOST_AND_PORT

    return HostSpec(host=host, username=username, port=port, ncpus=ncpus)


# START_CONTRACT: _parse_node_args
#   PURPOSE: Parse yasetnode argparse — one positional host (type=_parse_host_spec) + three store_true flags.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv }
#   OUTPUTS: { argparse.Namespace - parsed args with .host as HostSpec }
#   SIDE_EFFECTS: argparse may call sys.exit on --help/error (exit 0/2); body-level parser.error for --skip-setup × remove.
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_CONTRACT: _parse_node_args
def _parse_node_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yasetnode",
        description="Add or remove nodes from the yascheduler daemon",
    )
    parser.add_argument(
        "host",
        type=_parse_host_spec,
        help="[user@]host[:port][~ncpus] (IPv6 must be bracketed, e.g. [::1])",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip remote node setup (valid only on the add path)",
    )
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument(
        "--remove-soft",
        action="store_true",
        help="Disable the node if it has running tasks, else remove it",
    )
    mutex.add_argument(
        "--remove-hard",
        action="store_true",
        help="Mark associated RUNNING tasks DONE and remove the node",
    )
    add_config_arg(parser)
    add_log_level_arg(parser, default="WARNING")

    # START_BLOCK_PARSE_ARGS
    args = parser.parse_args(argv)
    if args.skip_setup and (args.remove_soft or args.remove_hard):
        parser.error("--skip-setup cannot be combined with --remove-soft/--remove-hard")
    # END_BLOCK_PARSE_ARGS
    return args


# START_CONTRACT: _remove_node_hard
#   PURPOSE: Hard-remove a node — in its own UoW, mark RUNNING tasks DONE, remove the node, commit, then announce.
#   INPUTS: { deps: CLIDeps - DI holder providing uow_factory, spec: HostSpec - parsed host }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens its own UoW; updates task statuses and removes the node; commits; prints success messages to stdout AFTER commit.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DI
# END_CONTRACT: _remove_node_hard
async def _remove_node_hard(deps: CLIDeps, spec: HostSpec) -> None:
    # START_BLOCK_MARK_AND_REMOVE
    async with deps.uow_factory() as uow:
        task_ids = await uow.tasks.list_ids_by_ip_and_status(
            spec.host, TaskStatus.RUNNING
        )
        for task_id in task_ids:
            await uow.tasks.update_status(task_id, TaskStatus.DONE)
        await uow.nodes.remove(spec.host)
        await uow.commit()
    # END_BLOCK_MARK_AND_REMOVE
    # START_BLOCK_ANNOUNCE
    for task_id in task_ids:
        print(f"An associated task {task_id} at {spec.host} is now marked done!")
    print(f"Removed host from yascheduler: {spec.host}")
    # END_BLOCK_ANNOUNCE


# START_CONTRACT: _remove_node_soft
#   PURPOSE: Soft-remove a node — in its own UoW, disable if RUNNING tasks exist, else remove; commit, then announce.
#   INPUTS: { deps: CLIDeps - DI holder providing uow_factory, spec: HostSpec - parsed host }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens its own UoW; disables or removes the node; commits; prints success messages to stdout AFTER commit.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DI
# END_CONTRACT: _remove_node_soft
async def _remove_node_soft(deps: CLIDeps, spec: HostSpec) -> None:
    # START_BLOCK_DISABLE_OR_REMOVE
    async with deps.uow_factory() as uow:
        task_ids = await uow.tasks.list_ids_by_ip_and_status(
            spec.host, TaskStatus.RUNNING
        )
        if task_ids:
            await uow.nodes.disable(spec.host)
            await uow.commit()
            print("A task associated, prevent from assigning the new tasks")
            print(f"Prevented from assigning the new tasks: {spec.host}")
        else:
            await uow.nodes.remove(spec.host)
            await uow.commit()
            print("No tasks associated, remove node immediately")
            print(f"Removed host from yascheduler: {spec.host}")
    # END_BLOCK_DISABLE_OR_REMOVE


# START_CONTRACT: _add_node
#   PURPOSE: Add a node — in its own UoW, connect gateway, optional setup, insert Node, commit, announce; disconnect in finally.
#   INPUTS: {
#     deps: CLIDeps - DI holder providing uow_factory,
#     repository: SSHMachineRepository, operations: SSHMachineOperations - gateway constructed by manage_node (mockable),
#     spec: HostSpec - parsed host,
#     config: Config - for username default + private keys + engines,
#     skip_setup: bool - skip gateway.setup_node when True
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens its own UoW; opens SSH, optionally sets up the remote node, inserts a Node, commits, prints to stdout;
#                ALWAYS calls repository.disconnect(host) via try/finally (resource-leak fix).
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-APPLICATION-UOW, M-DOMAIN-MODEL, M-ENTRYPOINTS-CONFIG, M-DI
# END_CONTRACT: _add_node
async def _add_node(
    deps: CLIDeps,
    repository: SSHMachineRepository,
    operations: SSHMachineOperations,
    spec: HostSpec,
    config: Config,
    skip_setup: bool,
) -> None:
    # HostSpec is frozen and the parser cannot resolve config defaults, so resolve here.
    username = spec.username or config.remote.username
    # START_BLOCK_CONNECT_SETUP_ADD
    try:
        await repository.connect(
            ip=spec.host,
            username=username,
            client_keys=list_private_keys(config.local.keys_dir),
            engines_dir=config.remote.engines_dir,
            port=spec.port,
        )
        if not skip_setup:
            print("Setup host...")
            await operations.setup_node(spec.host, config.engines)
        async with deps.uow_factory() as uow:
            await uow.nodes.add(
                Node(
                    ip=spec.host,
                    port=spec.port,
                    username=username,
                    ncpus=(spec.ncpus if spec.ncpus is not None else 0),
                    enabled=True,
                )
            )
            await uow.commit()
        print(f"Added host to yascheduler: {spec.host}:{spec.port}")
    finally:
        await repository.disconnect(spec.host)
    # END_BLOCK_CONNECT_SETUP_ADD


# START_CONTRACT: _manage_node_async
#   PURPOSE: Add, soft-remove, or hard-remove a node; exit 0 on success, 1 on runtime error, 2 on argparse error.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - prints success messages to stdout, Error: ... to stderr on failure, calls sys.exit(1) on failure }
#   SIDE_EFFECTS: Reads config, opens a read-only validation UoW, dispatches to a per-helper UoW that mutates+commits, optionally opens SSH; may call sys.exit.
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE, M-DI, M-APPLICATION-UOW, M-SSH-REPOSITORY, M-SSH-OPERATIONS
# END_CONTRACT: _manage_node_async
async def _manage_node_async(argv: list[str] | None) -> None:
    args = _parse_node_args(argv)
    spec: HostSpec = args.host
    # START_BLOCK_HANDLE_FAILURE
    try:
        logging.captureWarnings(True)
        log = logging.getLogger()
        log.setLevel(logging.getLevelName(args.log_level))
        if not log.handlers:
            log.addHandler(logging.StreamHandler(sys.stderr))

        # START_BLOCK_CONFIGURE
        config = parse_config(args.config)
        deps = make_cli_deps(config)
        repository = SSHMachineRepository()
        operations = SSHMachineOperations(repository=repository)
        # END_BLOCK_CONFIGURE

        # START_BLOCK_VALIDATE
        # Read-only validation UoW: closed without commit (nothing mutated).
        # A TOCTOU window exists between this close and the helper's own UoW open;
        # accepted for a single-operator CLI (design D18).
        async with deps.uow_factory() as uow:
            already_there = await uow.nodes.get(spec.host) is not None
        if already_there and not args.remove_soft and not args.remove_hard:
            raise ValueError(f"Host already in DB: {spec.host}")
        if not already_there and (args.remove_soft or args.remove_hard):
            raise ValueError(f"Host NOT in DB: {spec.host}")
        # END_BLOCK_VALIDATE

        # START_BLOCK_DISPATCH
        # Exactly one helper runs; each opens its own UoW, commits, and prints.
        if args.remove_hard:
            await _remove_node_hard(deps, spec)
        elif args.remove_soft:
            await _remove_node_soft(deps, spec)
        else:
            await _add_node(deps, repository, operations, spec, config, args.skip_setup)
        # END_BLOCK_DISPATCH
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


# START_CONTRACT: manage_node
#   PURPOSE: Sync entry point — run _manage_node_async via asyncio.run (no @to_sync; CLI entry points have no async caller).
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - delegates to asyncio.run }
#   SIDE_EFFECTS: Starts a fresh event loop via asyncio.run.
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_CONTRACT: manage_node
def manage_node(argv: list[str] | None = None) -> None:
    asyncio.run(_manage_node_async(argv))


if __name__ == "__main__":
    manage_node()
