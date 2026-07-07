# FILE: yascheduler/entrypoints/cli/manage_node.py
# VERSION: 1.9.0
# START_MODULE_CONTRACT
#   PURPOSE: yasetnode CLI command — add, soft-remove, or hard-remove nodes via per-helper UoW (+ SSH gateway on the add path). Positional accepts either a node_id (purely-digit) or a host spec.
#   SCOPE: manage_node command — add, soft-remove, or hard-remove nodes.
#   DEPENDS: M-ENTRYPOINTS-CONFIG, M-DI, M-DOMAIN-MODEL, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS, M-SHARED, M-APPLICATION-UOW, M-ENTRYPOINTS-CLI-ARGS
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE, M-DI, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-APPLICATION-UOW, M-SSH-KEYS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   manage_node - Sync entry point: asyncio.run(_manage_node_async(argv))
#   _manage_node_async - Add/soft-remove/hard-remove a node; validation UoW read-only, dispatch to per-helper UoW; exit 0/1/2
#   HostSpec - Frozen parsed host spec (host, username, port, ncpus)
#   NodeTarget - Frozen parsed node target (node_id: NodeId | None, host_spec: HostSpec | None; exactly one set)
#   _parse_host_spec - argparse type: parse [user@]host[:port][~ncpus] grammar (UNCHANGED)
#   _parse_node_target - argparse type: digit → NodeTarget(node_id=NodeId(n)); else delegate to _parse_host_spec
#   _parse_node_args - argparse → Namespace (prog="yasetnode", flags, mutex group); add-by-id rejected via parser.error
#   _remove_node_hard - Hard-remove: own UoW, mark RUNNING tasks DONE, remove node (by node_id), commit, print (takes Node; node.node_id keys the task lookup, node.ip for print)
#   _remove_node_soft - Soft-remove: own UoW, disable (if tasks) or remove node (by node_id), commit, print (takes Node; node.node_id keys the task lookup, node.ip for print)
#   _add_node - Add node: own UoW, connect, optional setup, insert NewNode, commit, print; try/finally disconnect
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - _remove_node_hard/_remove_node_soft call list_ids_by_node_id_and_status(node.node_id, ...); filter key changes from ip to node_id.
#   PREVIOUS_CHANGE: v1.8.0 - _add_node stops passing username and port to repository.connect (connect reads them from node internally).
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, replace

from yascheduler.domain import NewNode, Node, NodeId, TaskStatus
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


@dataclass(frozen=True)
class NodeTarget:
    """Parsed node target — EITHER a node_id OR a host spec (exactly one set).

    Produced by :func:`_parse_node_target`. On the node_id path
    (``node_id is not None``), ``host_spec`` is ``None`` and the node is
    resolved via :meth:`NodeRepository.get_by_id` to obtain the ``Node``
    (carrying both ``node_id`` and ``ip``) for the node_id-keyed mutators.
    On the host_spec path, ``node_id`` is ``None`` and the node is resolved
    via :meth:`NodeRepository.get(ip)`.
    """

    node_id: NodeId | None
    host_spec: HostSpec | None


# START_CONTRACT: _parse_host_spec
#   PURPOSE: argparse type — parse [user@]host[:port][~ncpus] into a frozen HostSpec; validate grammar and ranges.
#   INPUTS: { s: str - raw host-spec string from argparse }
#   OUTPUTS: { HostSpec - parsed spec with parser-applied port=22 and ncpus=None defaults }
#   SIDE_EFFECTS: None
#   RAISES: argparse.ArgumentTypeError - on malformed input (argparse surfaces as exit 2)
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


def _parse_node_target(s: str) -> NodeTarget:
    if s.isdigit():
        return NodeTarget(node_id=NodeId(int(s)), host_spec=None)
    return NodeTarget(node_id=None, host_spec=_parse_host_spec(s))


# START_CONTRACT: _parse_node_args
#   PURPOSE: Parse yasetnode argparse — one positional host (type=_parse_node_target → NodeTarget) + three store_true flags.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv }
#   OUTPUTS: { argparse.Namespace - parsed args with .host as NodeTarget }
#   SIDE_EFFECTS: argparse may call sys.exit on --help/error (exit 0/2).
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_CONTRACT: _parse_node_args
def _parse_node_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yasetnode",
        description="Add or remove nodes from the yascheduler daemon",
    )
    parser.add_argument(
        "host",
        type=_parse_node_target,
        help="node_id (purely-digit) OR [user@]host[:port][~ncpus] (IPv6 must be bracketed, e.g. [::1])",
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
    # A node cannot be added by id (adding requires a real host). The node_id
    # positional is valid ONLY on a remove path; reject the add-by-id
    # combination here (exit 2, consistent with the --skip-setup × remove check).
    if args.host.node_id is not None and not (args.remove_soft or args.remove_hard):
        parser.error(
            "a node cannot be added by id; provide a host like user@host[:port][~ncpus]"
        )
    # END_BLOCK_PARSE_ARGS
    return args


# START_CONTRACT: _remove_node_hard
#   PURPOSE: Hard-remove a node — in its own UoW, mark RUNNING tasks DONE, remove the node (by node_id), commit, then announce.
#   INPUTS: { deps: CLIDeps - DI holder providing uow_factory, node: Node - the resolved node (node.node_id keys the mutator + task lookup) }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens its own UoW; updates task statuses and removes the node (by node_id); commits; prints success messages to stdout AFTER commit.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DI
# END_CONTRACT: _remove_node_hard
async def _remove_node_hard(deps: CLIDeps, node: Node) -> None:
    # START_BLOCK_MARK_AND_REMOVE
    async with deps.uow_factory() as uow:
        task_ids = await uow.tasks.list_ids_by_node_id_and_status(
            node.node_id, TaskStatus.RUNNING
        )
        for task_id in task_ids:
            await uow.tasks.update_status(task_id, TaskStatus.DONE)
        await uow.nodes.remove(node.node_id)
        await uow.commit()
    # END_BLOCK_MARK_AND_REMOVE
    # START_BLOCK_ANNOUNCE
    for task_id in task_ids:
        print(f"An associated task {task_id} at {node.ip} is now marked done!")
    print(f"Removed host from yascheduler: {node.ip}")
    # END_BLOCK_ANNOUNCE


# START_CONTRACT: _remove_node_soft
#   PURPOSE: Soft-remove a node — in its own UoW, disable (by node_id) if RUNNING tasks exist, else remove (by node_id); commit, then announce.
#   INPUTS: { deps: CLIDeps - DI holder providing uow_factory, node: Node - the resolved node (node.node_id keys the mutator + task lookup) }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens its own UoW; disables or removes the node (by node_id); commits; prints success messages to stdout AFTER commit.
#   LINKS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DI
# END_CONTRACT: _remove_node_soft
async def _remove_node_soft(deps: CLIDeps, node: Node) -> None:
    # START_BLOCK_DISABLE_OR_REMOVE
    async with deps.uow_factory() as uow:
        task_ids = await uow.tasks.list_ids_by_node_id_and_status(
            node.node_id, TaskStatus.RUNNING
        )
        if task_ids:
            await uow.nodes.disable(node.node_id)
            await uow.commit()
            print("A task associated, prevent from assigning the new tasks")
            print(f"Prevented from assigning the new tasks: {node.ip}")
        else:
            await uow.nodes.remove(node.node_id)
            await uow.commit()
            print("No tasks associated, remove node immediately")
            print(f"Removed host from yascheduler: {node.ip}")
    # END_BLOCK_DISABLE_OR_REMOVE


# START_CONTRACT: _add_node
#   PURPOSE: Add a node — V1 single-row lifecycle: insert enabled=False tmp row (UoW#1) to obtain node_id, connect+setup under that node_id, flip to enabled=True via update (UoW#2); always disconnect(T.node_id) in finally; on connect-failure best-effort remove(T.node_id) then re-raise.
#   INPUTS: {
#     deps: CLIDeps - DI holder providing uow_factory,
#     repository: SSHMachineRepository, operations: SSHMachineOperations - gateway constructed by manage_node (mockable),
#     spec: HostSpec - parsed host spec (the add path is host-only; add-by-id is rejected in _parse_node_args),
#     config: Config - for username default + private keys + engines,
#     skip_setup: bool - skip gateway.setup_node when True
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Opens UoW#1 (insert enabled=False → Node(T), commit), opens SSH under T.node_id, optionally sets up the remote node, opens UoW#2 (update enabled=True, commit), prints to stdout; ALWAYS calls repository.disconnect(T.node_id) via try/finally (resource-leak fix). On connect-failure opens a UoW to remove+commit T.node_id (best-effort) then re-raises so the operator sees the real error.
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
    # START_BLOCK_INSERT_TMP
    # Insert an enabled=False tmp row first to obtain a node_id — the SSH
    # session must register under a node_id (connect takes a Node). This
    # mirrors the cloud-allocation V1 lifecycle: insert tmp → connect/setup →
    # flip enabled via update (single row per add lifecycle, not two).
    async with deps.uow_factory() as uow:
        tmp = await uow.nodes.insert(
            NewNode(
                ip=spec.host,
                port=spec.port,
                username=username,
                ncpus=(spec.ncpus if spec.ncpus is not None else 0),
                enabled=False,
            )
        )
        await uow.commit()
    # END_BLOCK_INSERT_TMP
    # START_BLOCK_CONNECT_SETUP_ADD
    try:
        try:
            session = await repository.connect(
                node=tmp,
                client_keys=list_private_keys(config.local.keys_dir),
                engines_dir=config.remote.engines_dir,
            )
        except Exception:
            # Connect failed — the tmp row is orphaned; best-effort remove it
            # so an unreachable host does not leave a disabled row behind.
            # Failure here is logged but does not mask the connect error.
            try:
                async with deps.uow_factory() as uow:
                    await uow.nodes.remove(tmp.node_id)
                    await uow.commit()
            except Exception:
                logging.getLogger(__name__).warning(
                    "[manage_node][_add_node][CLEANUP_FAILED] node_id=%s",
                    tmp.node_id,
                )
            raise
        if not skip_setup:
            print("Setup host...")
            await operations.setup_node(session, config.engines)
        # Flip the tmp row to enabled=True (single UPDATE on the same node_id).
        async with deps.uow_factory() as uow:
            await uow.nodes.update(replace(tmp, enabled=True))
            await uow.commit()
        print(f"Added host to yascheduler: {spec.host}:{spec.port}")
    finally:
        await repository.disconnect(tmp.node_id)
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
    target: NodeTarget = args.host
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
        # Resolve the Node early on both paths: get_by_id on the node_id path,
        # list_all + filter by ip on the host_spec path (the ip-keyed get(ip)
        # lookup is removed — node_id is the sole identity; resolving a host_spec
        # to a Node requires listing because ip is no longer a unique key). The
        # resolved Node (carrying node_id) is passed to the remove helpers —
        # node.node_id keys the node_id-keyed mutators; node.ip keys the
        # ip-keyed task lookup + print.
        resolved_node: Node | None = None
        if target.node_id is not None:
            async with deps.uow_factory() as uow:
                resolved_node = await uow.nodes.get_by_id(target.node_id)
            already_there = resolved_node is not None
        else:
            assert target.host_spec is not None  # exactly one of the two is set
            async with deps.uow_factory() as uow:
                all_nodes = await uow.nodes.list_all()
            resolved_node = next(
                (n for n in all_nodes if n.ip == target.host_spec.host), None
            )
            already_there = resolved_node is not None
        # On the node_id path the "already in DB" check is meaningless (add-by-id
        # is already rejected in _parse_node_args), so only the remove-path
        # "NOT in DB" check applies.
        if (
            target.host_spec is not None
            and already_there
            and not (args.remove_soft or args.remove_hard)
        ):
            raise ValueError(f"Host already in DB: {target.host_spec.host}")
        if not already_there and (args.remove_soft or args.remove_hard):
            # Distinguish the two not-in-DB paths: node_id (no HostSpec parsed)
            # vs host_spec (current behavior). The spec lists "node_id NOT in DB"
            # as a separate exit-1 scenario from "host NOT in DB".
            if target.node_id is not None:
                raise ValueError(f"Node ID not in DB: {target.node_id}")
            assert target.host_spec is not None
            raise ValueError(f"Host NOT in DB: {target.host_spec.host}")
        # END_BLOCK_VALIDATE

        # START_BLOCK_DISPATCH
        # Exactly one helper runs; each opens its own UoW, commits, and prints.
        # The remove helpers take the resolved Node (carrying both node_id and ip):
        # node.node_id keys the node_id-keyed mutators; node.ip keys the
        # ip-keyed task lookup (Surface C) and user-facing stdout.
        if args.remove_hard:
            assert resolved_node is not None  # validated present before dispatch
            await _remove_node_hard(deps, resolved_node)
        elif args.remove_soft:
            assert resolved_node is not None  # validated present before dispatch
            await _remove_node_soft(deps, resolved_node)
        else:
            assert target.host_spec is not None  # add path is host-only
            await _add_node(
                deps, repository, operations, target.host_spec, config, args.skip_setup
            )
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
