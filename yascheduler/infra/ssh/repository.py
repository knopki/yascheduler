# FILE: yascheduler/infra/ssh/repository.py
# VERSION: 2.4.0
# START_MODULE_CONTRACT
#   PURPOSE: SSHMachineRepository — connected-machine collection: registration, lifecycle, queries. True collection only — no state transitions, no accessor getters, no monitor mechanism (all moved to SSHMachineSession).
#   SCOPE: SSHMachineRepository: connected-machine collection lifecycle, keyed by NodeId; connection-building helpers.
#   DEPENDS: M-DOMAIN, M-DOMAIN-EXCEPTIONS, M-SSH-EXCEPTIONS, M-PLATFORM, M-SSH-SESSION
#   LINKS: M-SSH-REPOSITORY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MySSHClient - Insecure SSH client that trusts all host keys (connection-building bit; stays)
#   DEFAULT_CONN_OPTS - Default SSH connection options (connection-building bit; stays)
#   _build_tunnel_options - Build SSHClientConnectionOptions from node.jump_* , or None when node.jump_host is None
#   SSHMachineRepository - Concrete MachineRepository port implementation owning _sessions: dict[NodeId, SSHMachineSession] keyed by NodeId; connect(node)/disconnect(node_id)/get_session(node_id)/contains(node_id); delegates teardown to session._close()
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.4.0 - remove log parameter from __init__/signatures; bind module-local logger = get_logger("M-SSH-REPOSITORY") at module top
#   PREVIOUS_CHANGE: v2.7.0 - Split test-targeted CPUs info into log.trace("CPUS", ...) + log.info("connected to ...") per reform-grace-logging slice 6.11.
# END_CHANGE_SUMMARY

from __future__ import annotations

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
from yascheduler.shared import get_logger

from .platform import ADAPTERS, _detect_platform, _init_paths, make_run_fn
from .session import SSHMachineSession, my_backoff_exc

logger = get_logger("M-SSH-REPOSITORY")

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey


# ---- Connection-building bits (stay in repository.py — used by _open_connection) ----


class MySSHClient(SSHClient):
    def validate_host_public_key(
        self, host: str, addr: str, port: int, key: SSHKey
    ) -> bool:
        # NOTE: trust all host keys — insecure for MiM attacks
        return True


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


# START_CONTRACT: SSHMachineRepository
#   PURPOSE: Concrete MachineRepository — connected-machine collection. Owns _sessions: dict[NodeId, SSHMachineSession] keyed by NodeId. True collection only: lifecycle + queries. Delegates per-session teardown to session._close(). No state transitions, no accessor getters, no monitor mechanism — all on SSHMachineSession.
#   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS, M-SSH-SESSION
# END_CONTRACT: SSHMachineRepository
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

    # START_CONTRACT: SSHMachineRepository._open_connection
    #   PURPOSE: Build SSH options and open connection..
    #   INPUTS: { hostname, username, client_keys, *, port, connect_timeout, tunnel_opts: SSHClientConnectionOptions | None - pre-built tunnel options from _build_tunnel_options }
    #   SIDE_EFFECTS: Opens SSH connection.
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository._open_connection
    async def _open_connection(
        self,
        hostname: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        tunnel_opts: SSHClientConnectionOptions | None = None,
    ) -> tuple[SSHClientConnection, SSHClientConnectionOptions]:
        # START_BLOCK_BUILD_OPTS
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
        # END_BLOCK_BUILD_OPTS
        # START_BLOCK_CONNECT
        logger.trace(
            "CONNECT",
            hostname=hostname,
            tunnel=tunnel_opts.host if tunnel_opts else None,
        )
        conn = await asyncssh.connection.connect(
            options=conn_opts,
            host=conn_opts.host,
            port=conn_opts.port,
            tunnel=conn_opts.tunnel,
            config=[],
            known_hosts=None,
        )
        # END_BLOCK_CONNECT
        return conn, conn_opts

    # START_CONTRACT: SSHMachineRepository.connect
    #   PURPOSE: Open an SSH connection and register a MachineSession under node.node_id; translates transport errors into MachineConnectionError.
    #   INPUTS: { node: Node, client_keys, *, connect_timeout, data_dir, engines_dir, tasks_dir }
    #   OUTPUTS: { MachineSession - the newly constructed and registered session }
    #   SIDE_EFFECTS: Opens an SSH connection to node.hostname; registers a MachineSession in _sessions[node.node_id].
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-EXCEPTIONS, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.connect
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
        after _connect_impl's backoff exhausts retries. ``hostname`` is read
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
        except (asyncssh.misc.Error, OSError) as err:
            from yascheduler.domain.exceptions import MachineConnectionError

            raise MachineConnectionError(node.node_id, node.hostname, str(err)) from err

    # START_CONTRACT: SSHMachineRepository._connect_impl
    #   PURPOSE: Inner connection implementation with backoff retry on SSHRetryExc; constructs and registers the MachineSession.
    #   INPUTS: { node: Node, client_keys, *, connect_timeout, data_dir, engines_dir, tasks_dir }
    #   OUTPUTS: { SSHMachineSession - the newly constructed and registered session }
    #   SIDE_EFFECTS: Opens an SSH connection to node.hostname (login user node.username, port node.port); reads ncpus via adapter.get_cpu_cores and logs it; primes session._cached_ncpus with the discovered value; registers a MachineSession in _sessions[node.node_id].
    #   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository._connect_impl
    @my_backoff_exc()
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
        """Open SSH connection, detect platform, construct SSHMachineSession (inner impl with backoff)."""
        # START_BLOCK_BUILD_TUNNEL
        tunnel_opts = _build_tunnel_options(node, client_keys, connect_timeout)
        # END_BLOCK_BUILD_TUNNEL
        conn, conn_opts = await self._open_connection(
            node.hostname,
            node.username,
            client_keys,
            port=node.port,
            connect_timeout=connect_timeout,
            tunnel_opts=tunnel_opts,
        )
        # START_BLOCK_DETECT
        adapter, platforms = await _detect_platform(conn, ADAPTERS)
        logger.trace("DETECT", platform=adapter.platform, hostname=node.hostname)
        # END_BLOCK_DETECT
        # START_BLOCK_PATHS
        rd, re, rt = _init_paths(adapter, data_dir, engines_dir, tasks_dir)
        # END_BLOCK_PATHS
        # START_BLOCK_CREATE_MACHINE
        ncpus = await adapter.get_cpu_cores(make_run_fn(conn, adapter))
        logger.trace("CPUS", hostname=node.hostname, ncpus=ncpus)
        logger.info("connected to %s (%d CPUs)", node.hostname, ncpus)
        machine = ConnectedMachine(
            node_id=node.node_id,
            platform=adapter.platform,
            state=MachineState.FREE,
            free_since=time.monotonic(),
        )
        # END_BLOCK_CREATE_MACHINE
        # START_BLOCK_CREATE_SESSION
        session = SSHMachineSession(
            hostname=node.hostname,
            conn=conn,
            conn_opts=conn_opts,
            machine=machine,
            adapter=adapter,
            platforms=platforms,
            data_dir=rd,
            engines_dir=re,
            tasks_dir=rt,
        )
        session._prime_ncpus_cache(ncpus)
        self._sessions[node.node_id] = session
        # END_BLOCK_CREATE_SESSION
        return session

    # START_CONTRACT: SSHMachineRepository.disconnect
    #   PURPOSE: Close SSH for node_id and tear down its session. Pops _sessions[node_id] BEFORE awaiting session._close() (pop-before-await ordering preserves the disconnect-scope isolation invariant: a re-entry race cannot re-insert the cancelled task because the session is no longer reachable via the collection).
    #   INPUTS: { node_id: NodeId - the node whose session to disconnect }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Pops _sessions[node_id] (early return if absent), then awaits session._close() which marks the session closed synchronously, cancels the session's own monitor task, awaits the cancellation, and closes the SSH connection. SHALL NOT touch any other session's monitor.
    #   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.disconnect
    async def disconnect(self, node_id: NodeId) -> None:
        """Pop the session for node_id and delegate teardown to session._close()."""
        # START_BLOCK_POP_SESSION
        # Pop BEFORE await so a re-entry race cannot re-insert the cancelled task.
        session = self._sessions.pop(node_id, None)
        if session is None:
            return
        # END_BLOCK_POP_SESSION
        # START_BLOCK_DELEGATE_CLOSE
        # session._close() sets is_closed=True synchronously before its first await.
        await session._close()
        # END_BLOCK_DELEGATE_CLOSE

    # START_CONTRACT: SSHMachineRepository.disconnect_all
    #   PURPOSE: Disconnect all sessions (iterates a snapshot of NodeId keys).
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository.disconnect_all
    async def disconnect_all(self) -> None:
        """Close all sessions."""
        for node_id in list(self._sessions):
            await self.disconnect(node_id)

    # ---- Queries ----

    # START_CONTRACT: SSHMachineRepository.list_free
    #   PURPOSE: Return FREE sessions filtered by platform, oldest first by session.machine.free_since.
    #   INPUTS: { platforms: list[str] | None - optional platform filter }
    #   OUTPUTS: { list[MachineSession] - FREE sessions, oldest-first }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.list_free
    def list_free(self, platforms: list[str] | None) -> list[MachineSession]:
        """Return FREE sessions, optionally filtered by platform."""
        result: list[MachineSession] = []
        for session in self._sessions.values():
            m = session.machine
            if m.state != MachineState.FREE:
                continue
            if platforms is not None and m.platform not in platforms:
                continue
            result.append(session)
        result.sort(key=lambda s: s.machine.free_since or 0.0)
        return result

    # START_CONTRACT: SSHMachineRepository.list_connected
    #   PURPOSE: Return all registered sessions (port contract).
    #   INPUTS: { None }
    #   OUTPUTS: { list[MachineSession] }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.list_connected
    def list_connected(self) -> list[MachineSession]:
        """Return all registered sessions."""
        return list(self._sessions.values())

    # START_CONTRACT: SSHMachineRepository.get_session
    #   PURPOSE: Return the live session for node_id, or None (port contract). Callers use this per-tick to resolve a session before calling an operations method.
    #   INPUTS: { node_id: NodeId }
    #   OUTPUTS: { MachineSession | None }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.get_session
    def get_session(self, node_id: NodeId) -> MachineSession | None:
        """Return the live session for node_id, or None (after disconnect)."""
        return self._sessions.get(node_id)

    def contains(self, node_id: NodeId) -> bool:
        return node_id in self._sessions

    def __contains__(self, node_id: NodeId) -> bool:
        return node_id in self._sessions

    def __len__(self) -> int:
        return len(self._sessions)
