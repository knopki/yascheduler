"""SSHMachineRepository — connected-machine collection: registration, lifecycle, queries."""
# region MODULE_CONTRACT
# PURPOSE: SSHMachineRepository — connected-machine collection keyed by NodeId. True collection only: lifecycle + queries. No state transitions, no accessor getters, no monitor mechanism (all moved to SSHMachineSession).
# SCOPE:
# - SSHMachineRepository: connected-machine collection lifecycle, connection-building helpers.
# - MySSHClient, DEFAULT_CONN_OPTS, _build_tunnel_options connection-building bits.
# DEPENDENCIES: USES API: asyncssh (SSHClient, connection, options)
# KEYWORDS: repository, ssh, machine, collection, lifecycle, SSHMachineRepository
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import asyncssh
from asyncssh.client import SSHClient
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions

from yascheduler.domain import (
    ConnectedMachine,
    MachineSession,
    MachineState,
    Node,
    NodeId,
)
from yascheduler.domain.exceptions import MachineConnectionError

from .platform import ADAPTERS, _detect_platform, _init_paths, make_run_fn
from .session import SSHMachineSession, my_retry

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey

__all__ = ["DEFAULT_CONN_OPTS", "MySSHClient", "SSHMachineRepository"]
logger = logging.getLogger(__name__)


# region CLASS_MySSHClient
# PURPOSE: Accept any SSH host public key at connect time so first-contact to freshly-provisioned VMs succeeds without an out-of-band fingerprint exchange — the cloud-provisioned hosts we connect to are trusted by construction.
# RATIONALE:
# - Q: why trust all host keys instead of pinning?
#   A: yascheduler connects to VMs it just created via cloud APIs and to operator-managed static nodes from yascheduler_nodes; either path implies the operator already trusts the host. Pinning would require an out-of-band fingerprint channel that does not exist in this deployment shape.
class MySSHClient(SSHClient):
    """SSH client that trusts all host keys (insecure — accept for dev/staging)."""

    def validate_host_public_key(
        self,
        host: str,  # noqa: ARG002
        addr: str,  # noqa: ARG002
        port: int,  # noqa: ARG002
        key: SSHKey,  # noqa: ARG002
    ) -> bool:
        """Trust all host keys — accept connection."""
        # NOTE: trust all host keys — insecure for MiM attacks
        return True


# endregion CLASS_MySSHClient


DEFAULT_CONN_OPTS = SSHClientConnectionOptions(
    client_factory=MySSHClient,
    preferred_auth="publickey",
    keepalive_interval=10,
    keepalive_count_max=10,
    compression_algs=[],
    agent_path="",
    config=[],
    known_hosts=None,
    username="root",
)


# region FUNC__build_tunnel_options
# PURPOSE: Build the asyncssh bastion-leg options from node.jump_* fields so connect can pass a single tunnel= argument (or None) without re-deriving the bastion identity at every call site.
def _build_tunnel_options(
    node: Node,
    client_keys: Sequence[PurePath] | None,
    connect_timeout: int | None,
) -> SSHClientConnectionOptions | None:
    if not node.jump_host:
        return None
    return SSHClientConnectionOptions(
        options=DEFAULT_CONN_OPTS,
        host=node.jump_host,
        port=node.jump_port,
        username=node.jump_username,
        client_keys=client_keys or (),
        known_hosts=None,
        connect_timeout=connect_timeout,
    )


# endregion FUNC__build_tunnel_options


# region CLASS_SSHMachineRepository
# PURPOSE: Concrete MachineRepository — connected-machine collection keyed by NodeId.
# SCOPE: Connected-machine collection lifecycle and queries. NOT: single-machine operations, accessor getters, state-transition wrappers, monitor mechanism — those are SSHMachineSession.
# RATIONALE:
# - Q: why does connect read username/port/jump_* from node instead of taking them as parameters?
#   A: the caller (cloud allocator or static-node loader) is the sole authority for those fields — they are stamped onto the Node once and read many times; threading them as separate parameters would create a second source of truth that drifts the moment a caller forgets to pass one.
class SSHMachineRepository:
    """SSHMachineRepository implementing the MachineRepository Protocol.

    Owns a single dict keyed by ``NodeId``: ``_sessions``. The
    identity-taking methods (``connect``, ``disconnect``, ``get_session``,
    ``contains``, ``__contains__``) take ``node_id`` or ``Node``; ``hostname``
    is read from ``node.hostname`` inside ``connect`` for the asyncssh
    transport address. ``disconnect(node_id)`` pops the session and delegates
    teardown to ``session._close()`` (which cancels the session's own monitor
    task and closes the connection). The repository does not know about
    monitors.
    """

    def __init__(self) -> None:
        self._sessions: dict[NodeId, SSHMachineSession] = {}

    # ---- Connection lifecycle ----

    # region METHOD__open_connection
    # PURPOSE: Build SSH options and open connection via asyncssh with retry on SSHRetryExc.
    @my_retry()
    async def _open_connection(
        self,
        hostname: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        tunnel_opts: SSHClientConnectionOptions | None = None,
    ) -> SSHClientConnection:
        # region BLOCK_build_opts
        conn_opts = SSHClientConnectionOptions(
            options=DEFAULT_CONN_OPTS,
            host=hostname,
            port=port,
            username=username,
            tunnel=tunnel_opts,
            client_keys=client_keys or (),
            ignore_encrypted=True,
            connect_timeout=connect_timeout,
        )
        # endregion BLOCK_build_opts
        # region BLOCK_connect
        logger.debug(
            "CONNECT",
            extra={
                "hostname": hostname,
                "tunnel": tunnel_opts.host if tunnel_opts else None,
            },
        )
        return await asyncssh.connection.connect(
            options=conn_opts,
            host=conn_opts.host,
            port=conn_opts.port,
            tunnel=conn_opts.tunnel,
            config=[],
            known_hosts=None,
        )
        # endregion BLOCK_connect

    # endregion METHOD__open_connection

    # region METHOD_connect
    # PURPOSE: Open an SSH connection and register a MachineSession under node.node_id; translates transport errors into MachineConnectionError.
    # REQUIRES: The caller has stamped transport identity onto node — node.hostname, node.username, node.port, and (optionally) node.jump_host / node.jump_port / node.jump_username.
    async def connect(
        self,
        node: Node,
        client_keys: Sequence[PurePath] | None,
        *,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
    ) -> MachineSession:
        """Open SSH connection, detect platform, construct and register a session.

        Translates (asyncssh.misc.Error, OSError) into MachineConnectionError
        after _connect_impl's retry exhausts. ``hostname`` is read
        from ``node.hostname`` (the asyncssh host) and threaded into
        ``MachineConnectionError`` at the raise site (transport-level error —
        the address is what the operator recognizes).
        """
        try:
            return await self._connect_impl(
                node,
                client_keys,
                connect_timeout=connect_timeout,
                data_dir=data_dir,
                engines_dir=engines_dir,
                tasks_dir=tasks_dir,
            )
        except (asyncssh.misc.Error, OSError, ValueError) as err:
            # ValueError covers asyncssh.public_key.KeyImportError (its base), raised
            # by load_keypairs when client_keys contains a non-private-key file.
            raise MachineConnectionError(node.node_id, node.hostname, str(err)) from err

    # endregion METHOD_connect

    # region METHOD__connect_impl
    # PURPOSE: Inner connection implementation with retry on SSHRetryExc; constructs and registers the MachineSession.
    @my_retry()
    async def _connect_impl(
        self,
        node: Node,
        client_keys: Sequence[PurePath] | None,
        *,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
    ) -> MachineSession:
        """Open SSH connection, detect platform, construct SSHMachineSession (inner impl with retry)."""
        # region BLOCK_build_tunnel
        tunnel_opts = _build_tunnel_options(node, client_keys, connect_timeout)
        # endregion BLOCK_build_tunnel
        conn = await self._open_connection(
            node.hostname,
            node.username,
            client_keys,
            port=node.port,
            connect_timeout=connect_timeout,
            tunnel_opts=tunnel_opts,
        )
        # region BLOCK_detect
        adapter, platforms = await _detect_platform(conn, ADAPTERS)
        logger.debug(
            "DETECT",
            extra={"platform": adapter.platform, "hostname": node.hostname},
        )
        # endregion BLOCK_detect
        # region BLOCK_paths
        rd, re, rt = _init_paths(adapter, data_dir, engines_dir, tasks_dir)
        # endregion BLOCK_paths
        # region BLOCK_create_machine
        ncpus = await adapter.get_cpu_cores(make_run_fn(conn, adapter))
        logger.debug("CPUS", extra={"hostname": node.hostname, "ncpus": ncpus})
        logger.info("connected to %s (%d CPUs)", node.hostname, ncpus)
        machine = ConnectedMachine(
            node_id=node.node_id,
            platforms=tuple(platforms),
            state=MachineState.FREE,
            free_since=time.monotonic(),
        )
        # endregion BLOCK_create_machine
        # region BLOCK_create_session
        session = SSHMachineSession(
            hostname=node.hostname,
            conn=conn,
            machine=machine,
            adapter=adapter,
            platforms=platforms,
            data_dir=rd,
            engines_dir=re,
            tasks_dir=rt,
        )
        session._prime_ncpus_cache(ncpus)  # noqa: SLF001
        self._sessions[node.node_id] = session
        # endregion BLOCK_create_session
        return session

    # endregion METHOD__connect_impl

    # region METHOD_disconnect
    # PURPOSE: Close SSH for node_id and tear down its session. Pops _sessions[node_id] BEFORE awaiting session._close() (pop-before-await ordering preserves disconnect-scope isolation invariant).
    async def disconnect(self, node_id: NodeId) -> None:
        """Pop the session for node_id and delegate teardown to session._close()."""
        # region BLOCK_pop_session
        # Pop BEFORE await so a re-entry race cannot re-insert the cancelled task.
        session = self._sessions.pop(node_id, None)
        if session is None:
            return
        # endregion BLOCK_pop_session
        # region BLOCK_delegate_close
        # session._close() sets is_closed=True synchronously before its first await.
        await session._close()  # noqa: SLF001
        # endregion BLOCK_delegate_close

    # endregion METHOD_disconnect

    # region METHOD_disconnect_all
    # PURPOSE: Disconnect all sessions (iterates a snapshot of NodeId keys).
    async def disconnect_all(self) -> None:
        """Close all sessions."""
        for node_id in list(self._sessions):
            await self.disconnect(node_id)

    # endregion METHOD_disconnect_all

    # region METHOD_list_free
    # PURPOSE: Return FREE sessions filtered by platform intersection, oldest first by session.machine.free_since.
    def list_free(self, platforms: list[str] | None) -> list[MachineSession]:
        """Return FREE sessions, optionally filtered by platform intersection."""
        result: list[MachineSession] = []
        wanted = set(platforms) if platforms is not None else None
        for session in self._sessions.values():
            m = session.machine
            if m.state != MachineState.FREE:
                continue
            if wanted is not None and not set(m.platforms) & wanted:
                continue
            result.append(session)
        result.sort(key=lambda s: s.machine.free_since or 0.0)
        return result

    # endregion METHOD_list_free

    # region METHOD_list_connected
    # PURPOSE: Return all registered sessions (port contract).
    def list_connected(self) -> list[MachineSession]:
        """Return all registered sessions."""
        return list(self._sessions.values())

    # endregion METHOD_list_connected

    # region METHOD_get_session
    # PURPOSE: Return the live session for node_id, or None (port contract).
    def get_session(self, node_id: NodeId) -> MachineSession | None:
        """Return the live session for node_id, or None (after disconnect)."""
        return self._sessions.get(node_id)

    # endregion METHOD_get_session

    def contains(self, node_id: NodeId) -> bool:
        """Return True if node_id has an active session."""
        return node_id in self._sessions

    def __contains__(self, node_id: NodeId) -> bool:
        return node_id in self._sessions

    def __len__(self) -> int:
        return len(self._sessions)


# endregion CLASS_SSHMachineRepository
