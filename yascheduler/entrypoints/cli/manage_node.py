"""yasetnode CLI command — add, soft-remove, or hard-remove nodes via per-helper UoW (+ SSH gateway on the add path). Positional accepts either a node_id (purely-digit) or a host spec."""
# region MODULE_CONTRACT
# PURPOSE: yasetnode CLI command — add, soft-remove, or hard-remove nodes via per-helper UoW (+ SSH gateway on the add path). Positional accepts either a node_id (purely-digit) or a host spec.
# SCOPE: manage_node command — add, soft-remove, or hard-remove nodes.
# KEYWORDS: node, manage, add, remove, cli, ssh
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, replace

from yascheduler.domain import NewNode, Node, NodeId, TaskStatus
from yascheduler.entrypoints import CLIDeps, Config, make_cli_deps
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.infra import SSHMachineRepository
from yascheduler.infra.ssh.keys import list_private_keys

from .args import add_config_arg, add_log_level_arg

logger = logging.getLogger(__name__)

MAX_PORT = 65535


class MalformedHostSpecError(argparse.ArgumentTypeError):
    """Raised when the host spec argument fails validation."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__(f"malformed host spec: {raw!r}")


class NodeAlreadyInDBError(ValueError):
    """Raised when attempting to add a host that is already in the database."""

    def __init__(self, host: str) -> None:
        self.host = host
        super().__init__(f"Host already in DB: {host}")


class NodeIdNotInDBError(ValueError):
    """Raised when a node_id is not found in the database on a remove path."""

    def __init__(self, node_id: NodeId) -> None:
        self.node_id = node_id
        super().__init__(f"Node ID not in DB: {node_id}")


class HostNotInDBError(ValueError):
    """Raised when a host name is not found in the database on a remove path."""

    def __init__(self, host: str) -> None:
        self.host = host
        super().__init__(f"Host NOT in DB: {host}")


@dataclass(frozen=True)
class HostSpec:
    """Parsed host spec from the yasetnode positional argument."""

    host: str
    username: str | None
    port: int
    ncpus: int | None


@dataclass(frozen=True)
class NodeTarget:
    """Parsed node target — EITHER a node_id OR a host spec (exactly one set)."""

    node_id: NodeId | None
    host_spec: HostSpec | None


# region FUNC__parse_host_spec
# PURPOSE: turn the yasetnode positional string into a validated HostSpec so the add path can consume it without re-parsing
def _parse_host_spec(s: str) -> HostSpec:
    raw = s

    # region BLOCK_parse_user
    at_count = s.count("@")
    if at_count > 1:
        raise MalformedHostSpecError(raw)
    username: str | None = None
    if at_count == 1:
        user_part, _, s = s.partition("@")
        if not user_part:
            raise MalformedHostSpecError(raw)
        username = user_part
    # endregion BLOCK_parse_user

    # region BLOCK_parse_ncpus
    tilde_count = s.count("~")
    if tilde_count > 1:
        raise MalformedHostSpecError(raw)
    ncpus: int | None = None
    if tilde_count == 1:
        host_part, _, ncpus_part = s.partition("~")
        if not ncpus_part:
            raise MalformedHostSpecError(raw)
        try:
            n = int(ncpus_part)
        except ValueError:
            raise MalformedHostSpecError(raw) from None
        if n < 0:
            raise MalformedHostSpecError(raw)
        s = host_part
        ncpus = None if n == 0 else n
    # endregion BLOCK_parse_ncpus

    # region BLOCK_parse_host_and_port
    if s.startswith("["):
        close = s.find("]")
        if close == -1:
            raise MalformedHostSpecError(raw)
        host = s[1:close]
        remainder = s[close + 1 :]
        if remainder == "":
            port = 22
        elif remainder.startswith(":") and ":" not in remainder[1:]:
            port_str = remainder[1:]
            try:
                port = int(port_str)
            except ValueError:
                raise MalformedHostSpecError(raw) from None
        else:
            raise MalformedHostSpecError(raw)
    else:
        colon_count = s.count(":")
        if colon_count > 1:
            # Unbracketed IPv6 is ambiguous against :port — require brackets.
            raise MalformedHostSpecError(raw)
        if colon_count == 1:
            host, _, port_str = s.partition(":")
            try:
                port = int(port_str)
            except ValueError:
                raise MalformedHostSpecError(raw) from None
        else:
            host = s
            port = 22

    if not host:
        raise MalformedHostSpecError(raw)
    if port < 1 or port > MAX_PORT:
        raise MalformedHostSpecError(raw)
    # endregion BLOCK_parse_host_and_port

    return HostSpec(host=host, username=username, port=port, ncpus=ncpus)


# endregion FUNC__parse_host_spec


def _parse_node_target(s: str) -> NodeTarget:
    if s.isdigit():
        return NodeTarget(node_id=NodeId(int(s)), host_spec=None)
    return NodeTarget(node_id=None, host_spec=_parse_host_spec(s))


# region FUNC__parse_node_args
# PURPOSE: build and parse the yasetnode argument parser, rejecting illegal flag combinations at exit 2 before any I/O
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

    # region BLOCK_parse_args
    args = parser.parse_args(argv)
    if args.skip_setup and (args.remove_soft or args.remove_hard):
        parser.error("--skip-setup cannot be combined with --remove-soft/--remove-hard")
    # A node cannot be added by id (adding requires a real host). The node_id
    # positional is valid ONLY on a remove path; reject the add-by-id
    # combination here (exit 2, consistent with the --skip-setup x remove check).
    if args.host.node_id is not None and not (args.remove_soft or args.remove_hard):
        parser.error(
            "a node cannot be added by id; provide a host like user@host[:port][~ncpus]",
        )
    # endregion BLOCK_parse_args
    return args


# endregion FUNC__parse_node_args


# region FUNC__remove_node_hard
# PURPOSE: permanently erase a node and its RUNNING tasks from the DB in a single transaction so an operator can force-clean a dead node
async def _remove_node_hard(deps: CLIDeps, node: Node) -> None:
    # region BLOCK_mark_and_remove
    async with deps.uow_factory() as uow:
        task_ids = await uow.tasks.list_ids_by_node_id_and_status(
            node.node_id,
            TaskStatus.RUNNING,
        )
        for task_id in task_ids:
            await uow.tasks.update_status(task_id, TaskStatus.DONE)
        await uow.nodes.remove(node.node_id)
        await uow.commit()
    # endregion BLOCK_mark_and_remove
    # region BLOCK_announce
    for task_id in task_ids:
        sys.stdout.write(
            f"An associated task {task_id} at {node.hostname} is now marked done!\n",
        )
    sys.stdout.write(f"Removed host from yascheduler: {node.hostname}\n")
    # endregion BLOCK_announce


# endregion FUNC__remove_node_hard


# region FUNC__remove_node_soft
# PURPOSE: gracefully retire a node without destroying evidence of running work — disable if busy, erase if idle
async def _remove_node_soft(deps: CLIDeps, node: Node) -> None:
    # region BLOCK_disable_or_remove
    async with deps.uow_factory() as uow:
        task_ids = await uow.tasks.list_ids_by_node_id_and_status(
            node.node_id,
            TaskStatus.RUNNING,
        )
        if task_ids:
            await uow.nodes.disable(node.node_id)
            await uow.commit()
            sys.stdout.write(
                "A task associated, prevent from assigning the new tasks\n",
            )
            sys.stdout.write(
                f"Prevented from assigning the new tasks: {node.hostname}\n",
            )
        else:
            await uow.nodes.remove(node.node_id)
            await uow.commit()
            sys.stdout.write("No tasks associated, remove node immediately\n")
            sys.stdout.write(f"Removed host from yascheduler: {node.hostname}\n")
    # endregion BLOCK_disable_or_remove


# endregion FUNC__remove_node_soft


# region FUNC__add_node
# PURPOSE: register a new SSH-accessible host in the scheduler, verifying reachability before marking it active
async def _add_node(
    deps: CLIDeps,
    repository: SSHMachineRepository,
    spec: HostSpec,
    config: Config,
    *,
    skip_setup: bool,
) -> None:
    # HostSpec is frozen and the parser cannot resolve config defaults, so resolve here.
    username = spec.username or config.remote.username
    # region BLOCK_insert_tmp
    # Insert an enabled=False tmp row first to obtain a node_id — the SSH
    # session must register under a node_id (connect takes a Node). This
    # mirrors the cloud-allocation V1 lifecycle: insert tmp → connect/setup →
    # flip enabled via update (single row per add lifecycle, not two).
    async with deps.uow_factory() as uow:
        tmp = await uow.nodes.insert(
            NewNode(
                hostname=spec.host,
                port=spec.port,
                username=username,
                ncpus=spec.ncpus,
                enabled=False,
                jump_host=config.remote.jump_host,
                jump_username=config.remote.jump_username or "root",
                jump_port=config.remote.jump_port,
            ),
        )
        await uow.commit()
    # endregion BLOCK_insert_tmp
    # region BLOCK_connect_setup_add
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
                logger.warning(
                    "add_node cleanup failed: node_id=%s",
                    tmp.node_id,
                )
            raise
        if not skip_setup:
            sys.stdout.write("Setup host...\n")
            await session.setup_node(config.engines)
        # Flip the tmp row to enabled=True (single UPDATE on the same node_id).
        async with deps.uow_factory() as uow:
            await uow.nodes.update(replace(tmp, enabled=True))
            await uow.commit()
        sys.stdout.write(f"Added host to yascheduler: {spec.host}:{spec.port}\n")
    finally:
        await repository.disconnect(tmp.node_id)
    # endregion BLOCK_connect_setup_add


# endregion FUNC__add_node


# region FUNC__resolve_and_validate_node
# PURPOSE: resolve a yasetnode target to a DB Node and enforce presence rules so the operator gets a clear error before any mutation
async def _resolve_and_validate_node(
    target: NodeTarget,
    deps: CLIDeps,
    *,
    remove_soft: bool,
    remove_hard: bool,
) -> Node | None:
    # region BLOCK_resolve
    if target.node_id is not None:
        async with deps.uow_factory() as uow:
            resolved_node = await uow.nodes.get_by_id(target.node_id)
    else:
        assert target.host_spec is not None  # exactly one of the two is set
        async with deps.uow_factory() as uow:
            all_nodes = await uow.nodes.list_all()
        resolved_node = next(
            (n for n in all_nodes if n.hostname == target.host_spec.host),
            None,
        )
    already_there = resolved_node is not None
    # endregion BLOCK_resolve

    # region BLOCK_enforce_presence
    # On the node_id path the "already in DB" check is meaningless (add-by-id
    # is already rejected in _parse_node_args), so only the remove-path
    # "NOT in DB" check applies.
    if (
        target.host_spec is not None
        and already_there
        and not (remove_soft or remove_hard)
    ):
        raise NodeAlreadyInDBError(target.host_spec.host)
    if not already_there and (remove_soft or remove_hard):
        # Distinguish the two not-in-DB paths: node_id (no HostSpec parsed)
        # vs host_spec (current behavior). The spec lists "node_id NOT in DB"
        # as a separate exit-1 scenario from "host NOT in DB".
        if target.node_id is not None:
            raise NodeIdNotInDBError(target.node_id)
        assert target.host_spec is not None
        raise HostNotInDBError(target.host_spec.host)
    # endregion BLOCK_enforce_presence
    return resolved_node


# endregion FUNC__resolve_and_validate_node


# region FUNC__manage_node_async
# PURPOSE: orchestrate the full yasetnode lifecycle — parse, validate, dispatch, and surface errors to the operator with the right exit code
async def _manage_node_async(argv: list[str] | None) -> None:
    args = _parse_node_args(argv)
    target: NodeTarget = args.host
    # region BLOCK_handle_failure
    try:
        logging.captureWarnings(True)
        log = logging.getLogger()
        log.setLevel(logging.getLevelName(args.log_level))
        if not log.handlers:
            log.addHandler(logging.StreamHandler(sys.stderr))

        # region BLOCK_configure
        config = parse_config(args.config)
        deps = make_cli_deps(config)
        repository = SSHMachineRepository()
        # endregion BLOCK_configure

        # region BLOCK_validate
        resolved_node = await _resolve_and_validate_node(
            target,
            deps,
            remove_soft=args.remove_soft,
            remove_hard=args.remove_hard,
        )
        # endregion BLOCK_validate

        # region BLOCK_dispatch
        # Exactly one helper runs; each opens its own UoW, commits, and prints.
        if args.remove_hard:
            assert resolved_node is not None  # validated present before dispatch
            await _remove_node_hard(deps, resolved_node)
        elif args.remove_soft:
            assert resolved_node is not None  # validated present before dispatch
            await _remove_node_soft(deps, resolved_node)
        else:
            assert target.host_spec is not None  # add path is host-only
            await _add_node(
                deps,
                repository,
                target.host_spec,
                config,
                skip_setup=args.skip_setup,
            )
        # endregion BLOCK_dispatch
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    # endregion BLOCK_handle_failure


# endregion FUNC__manage_node_async


# region FUNC_manage_node
# PURPOSE: bridge the async manage_node coroutine to a sync CLI entry point that asyncio.run can call
def manage_node(argv: list[str] | None = None) -> None:
    """Sync entry point — run _manage_node_async via asyncio."""
    asyncio.run(_manage_node_async(argv))


# endregion FUNC_manage_node

if __name__ == "__main__":
    manage_node()
