# FILE: yascheduler/infra/ssh/repository.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: SSHMachineRepository — connected-machine collection: registration, lifecycle, queries. True collection only — no state transitions, no accessor getters, no monitor mechanism (all moved to SSHMachineSession).
#   SCOPE: SSHMachineRepository class (owns _sessions: dict[str, SSHMachineSession]) + MySSHClient + DEFAULT_CONN_OPTS + _resolve_tunnel connection-building helpers (used by _open_connection).
#   DEPENDS: M-DOMAIN, M-DOMAIN-EXCEPTIONS, M-SSH-EXCEPTIONS, M-PLATFORM, M-SSH-SESSION
#   LINKS: M-SSH-REPOSITORY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MySSHClient - Insecure SSH client that trusts all host keys (connection-building bit; stays)
#   DEFAULT_CONN_OPTS - Default SSH connection options (connection-building bit; stays)
#   _resolve_tunnel - Build SSH tunnel string from jump host/username (connection-building bit; stays)
#   SSHMachineRepository - Concrete MachineRepository port implementation owning _sessions: dict[str, SSHMachineSession]; delegates teardown to session._close()
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Session-based-machine-handle section 3. Replaced _machines: dict[str, _MachineState] + _monitors: dict[str, asyncio.Task[None]] with _sessions: dict[str, SSHMachineSession]. Deleted _MachineState dataclass, _get_machine_state, get_machine_state, occupy/release/update_machine, get_path/get_quote/get_hostname, install_monitor/cancel_monitor. connect now constructs SSHMachineSession and returns MachineSession. disconnect pops _sessions[ip] then delegates teardown to session._close() (pop-before-await ordering preserved; session._close sets is_closed synchronously before its first await). list_free/list_connected now return list[MachineSession]. get_session(ip) returns MachineSession | None. Monitor mechanism moved onto SSHMachineSession (reverses decompose-ssh-gateway D2). MySSHClient/DEFAULT_CONN_OPTS/_resolve_tunnel stay (connection-building bits used by _open_connection).
#   PREVIOUS_CHANGE: v1.1.0 - Removed nine zero-caller methods from SSHMachineRepository (get_conn, keys, items, register_machine, get_adapter, get_platforms, get_data_dir, get_engines_dir, get_tasks_dir) per cleanup-unused-repository-symbols.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import asyncssh
from asyncssh.client import SSHClient
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions

from yascheduler.domain import ConnectedMachine, MachineSession, MachineState

from .platform import ADAPTERS, _detect_platform, _init_paths, make_run_fn
from .session import SSHMachineSession, my_backoff_exc

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


def _resolve_tunnel(jump_host: str | None, jump_username: str | None) -> str | None:
    return jump_host and jump_username and f"{jump_username}@{jump_host}"


# START_CONTRACT: SSHMachineRepository
#   PURPOSE: Concrete MachineRepository — connected-machine collection. Owns _sessions: dict[str, SSHMachineSession] keyed by IP. True collection only: lifecycle + queries. Delegates per-session teardown to session._close(). No state transitions, no accessor getters, no monitor mechanism — all on SSHMachineSession.
#   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS, M-SSH-SESSION
# END_CONTRACT: SSHMachineRepository
class SSHMachineRepository:
    """SSHMachineRepository implementing the MachineRepository Protocol.

    Owns a single dict keyed by IP: _sessions. disconnect(ip) pops the
    session and delegates teardown to session._close() (which cancels the
    session's own monitor task and closes the connection). The repository
    does not know about monitors.
    """

    def __init__(self, log: logging.Logger | None = None) -> None:
        self._sessions: dict[str, SSHMachineSession] = {}
        self._log = log or logging.getLogger("SSHMachineRepository")

    # ---- Connection lifecycle ----

    # START_CONTRACT: SSHMachineRepository._open_connection
    #   PURPOSE: Build SSH options and open connection.
    #   SIDE_EFFECTS: Opens SSH connection.
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository._open_connection
    async def _open_connection(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> tuple[SSHClientConnection, SSHClientConnectionOptions]:
        # START_BLOCK_BUILD_OPTS
        conn_opts = SSHClientConnectionOptions(
            options=DEFAULT_CONN_OPTS,
            host=ip,
            port=port,
            username=username,
            tunnel=_resolve_tunnel(jump_host, jump_username),
            client_keys=client_keys or (),
            ignore_encrypted=True,
            connect_timeout=connect_timeout,
        )
        # END_BLOCK_BUILD_OPTS
        # START_BLOCK_CONNECT
        self._log.debug("[SSHRepository][_open_connection][CONNECT] ip=%s", ip)
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
    #   PURPOSE: Public API — translates transport errors into domain MachineConnectionError. Returns the newly constructed MachineSession.
    #   INPUTS: { ip, username, client_keys, *, port, connect_timeout, data_dir, engines_dir, tasks_dir, jump_host, jump_username }
    #   OUTPUTS: { MachineSession - the newly constructed and registered session }
    #   SIDE_EFFECTS: Opens SSH connection, detects platform, constructs SSHMachineSession, stores in _sessions[ip].
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-EXCEPTIONS, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.connect
    async def connect(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> MachineSession:
        """Open SSH connection, detect platform, construct and register a session.

        Translates (asyncssh.misc.Error, OSError) into MachineConnectionError
        after _connect_impl's backoff exhausts retries.
        """
        try:
            return await self._connect_impl(
                ip,
                username,
                client_keys,
                port=port,
                connect_timeout=connect_timeout,
                data_dir=data_dir,
                engines_dir=engines_dir,
                tasks_dir=tasks_dir,
                jump_host=jump_host,
                jump_username=jump_username,
            )
        except (asyncssh.misc.Error, OSError) as err:
            from yascheduler.domain.exceptions import MachineConnectionError

            raise MachineConnectionError(ip, str(err)) from err

    # START_CONTRACT: SSHMachineRepository._connect_impl
    #   PURPOSE: Inner connection implementation with backoff retry on SSHRetryExc. Constructs SSHMachineSession and registers it in _sessions.
    #   INPUTS: { same as connect }
    #   OUTPUTS: { SSHMachineSession - the newly constructed and registered session }
    #   SIDE_EFFECTS: Opens SSH, detects platform, constructs SSHMachineSession, stores in _sessions[ip].
    #   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository._connect_impl
    @my_backoff_exc()
    async def _connect_impl(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> MachineSession:
        """Open SSH connection, detect platform, construct SSHMachineSession (inner impl with backoff)."""
        conn, conn_opts = await self._open_connection(
            ip,
            username,
            client_keys,
            port=port,
            connect_timeout=connect_timeout,
            jump_host=jump_host,
            jump_username=jump_username,
        )
        # START_BLOCK_DETECT
        adapter, platforms = await _detect_platform(conn, ADAPTERS)
        self._log.debug(
            "[SSHRepository][connect][DETECT] platform=%s ip=%s", adapter.platform, ip
        )
        # END_BLOCK_DETECT
        # START_BLOCK_PATHS
        rd, re, rt = _init_paths(adapter, data_dir, engines_dir, tasks_dir)
        # END_BLOCK_PATHS
        # START_BLOCK_CREATE_MACHINE
        ncpus = await adapter.get_cpu_cores(make_run_fn(conn, adapter))
        machine = ConnectedMachine(
            ip=ip,
            platform=adapter.platform,
            ncpus=ncpus,
            state=MachineState.FREE,
            free_since=time.monotonic(),
        )
        # END_BLOCK_CREATE_MACHINE
        # START_BLOCK_CREATE_SESSION
        session = SSHMachineSession(
            ip=ip,
            conn=conn,
            conn_opts=conn_opts,
            machine=machine,
            adapter=adapter,
            platforms=platforms,
            data_dir=rd,
            engines_dir=re,
            tasks_dir=rt,
            log=self._log,
        )
        self._sessions[ip] = session
        # END_BLOCK_CREATE_SESSION
        return session

    # START_CONTRACT: SSHMachineRepository.disconnect
    #   PURPOSE: Close SSH for ip and tear down its session. Pops _sessions[ip] BEFORE awaiting session._close() (pop-before-await ordering preserves the disconnect-scope isolation invariant: a re-entry race cannot re-insert the cancelled task because the session is no longer reachable via the collection).
    #   INPUTS: { ip: str - IP of the machine to disconnect }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Pops _sessions[ip] (early return if absent), then awaits session._close() which marks the session closed synchronously, cancels the session's own monitor task, awaits the cancellation, and closes the SSH connection. SHALL NOT touch any other session's monitor.
    #   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.disconnect
    async def disconnect(self, ip: str) -> None:
        """Pop the session for ip and delegate teardown to session._close()."""
        # START_BLOCK_POP_SESSION
        # Pop BEFORE await so a re-entry race cannot re-insert the cancelled task.
        session = self._sessions.pop(ip, None)
        if session is None:
            return
        # END_BLOCK_POP_SESSION
        # START_BLOCK_DELEGATE_CLOSE
        # session._close() sets is_closed=True synchronously before its first await.
        await session._close()
        # END_BLOCK_DELEGATE_CLOSE

    # START_CONTRACT: SSHMachineRepository.disconnect_all
    #   PURPOSE: Disconnect all sessions.
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository.disconnect_all
    async def disconnect_all(self) -> None:
        """Close all sessions."""
        for ip in list(self._sessions):
            await self.disconnect(ip)

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
    #   PURPOSE: Return the live session for ip, or None (port contract). Callers use this per-tick to resolve a session before calling an operations method.
    #   INPUTS: { ip: str }
    #   OUTPUTS: { MachineSession | None }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS, M-SSH-SESSION
    # END_CONTRACT: SSHMachineRepository.get_session
    def get_session(self, ip: str) -> MachineSession | None:
        """Return the live session for ip, or None (after disconnect)."""
        return self._sessions.get(ip)

    def contains(self, ip: str) -> bool:
        return ip in self._sessions

    def __contains__(self, ip: str) -> bool:
        return ip in self._sessions

    def __len__(self) -> int:
        return len(self._sessions)
