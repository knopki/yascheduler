# FILE: yascheduler/infra/ssh/repository.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: SSHMachineRepository — connected-machine collection: registration, lifecycle, queries, state transitions, accessor getters, generic occupancy-monitor mechanism keyed by IP.
#   SCOPE: SSHMachineRepository class + _MachineState dataclass + MySSHClient + DEFAULT_CONN_OPTS + _resolve_tunnel connection-building helpers.
#   DEPENDS: M-DOMAIN, M-DOMAIN-EXCEPTIONS, M-SSH-EXCEPTIONS, M-PLATFORM, M-SSH-OPERATIONS-BASE
#   LINKS: M-SSH-REPOSITORY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _MachineState - Frozen internal state holder for a connected machine (conn, conn_opts, machine, adapter, platforms, data_dir, engines_dir, tasks_dir)
#   MySSHClient - Insecure SSH client that trusts all host keys
#   DEFAULT_CONN_OPTS - Default SSH connection options
#   _resolve_tunnel - Build SSH tunnel string from jump host/username
#   SSHMachineRepository - Concrete MachineRepository port implementation owning _machines and _monitors dicts
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Removed nine zero-caller methods from SSHMachineRepository (get_conn, keys, items, register_machine, get_adapter, get_platforms, get_data_dir, get_engines_dir, get_tasks_dir) per cleanup-unused-repository-symbols. Narrowing pure deletion; no behavior change, no caller migration. ItemsView/KeysView TYPE_CHECKING imports dropped (only used by removed keys()/items()).
#   PREVIOUS_CHANGE: v1.0.0 - Initial module created (decompose-ssh-gateway). SSHMachineRepository extracted from the dissolved SSHMachineGateway god-class; collection responsibility (lifecycle/queries/state transitions/accessors/monitor mechanism) lives here. _MachineState, MySSHClient, DEFAULT_CONN_OPTS, _resolve_tunnel moved verbatim from gateway.py/helpers.py. _bg_tasks renamed to _monitors; monitor mechanism generalized to install_monitor/cancel_monitor (Engine-agnostic). Operations responsibility moved to infra/ssh/operations/.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import asyncssh
from asyncssh.client import SSHClient
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions

from yascheduler.domain import ConnectedMachine, MachineState
from yascheduler.domain.exceptions import MachineConnectionError

from .operations.base import my_backoff_exc
from .platform import ADAPTERS, _detect_platform, _init_paths, make_run_fn

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey

    from .platform import (
        QuoteCallable,
        RemoteMachineAdapter,
    )


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


# START_CONTRACT: _MachineState
#   PURPOSE: Internal state holder: connection, adapter, paths, domain machine.
#   LINKS: M-SSH-REPOSITORY
# END_CONTRACT: _MachineState
@dataclass(frozen=True)
class _MachineState:
    """Internal state holder for a connected remote machine."""

    conn: SSHClientConnection
    conn_opts: SSHClientConnectionOptions
    machine: ConnectedMachine
    adapter: RemoteMachineAdapter
    platforms: Sequence[str]
    data_dir: PurePath
    engines_dir: PurePath
    tasks_dir: PurePath


# START_CONTRACT: SSHMachineRepository
#   PURPOSE: Concrete MachineRepository — owns connected-machine collection and generic occupancy-monitor mechanism.
#   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS
# END_CONTRACT: SSHMachineRepository
class SSHMachineRepository:
    """SSHMachineRepository implementing the MachineRepository Protocol.

    Owns two dicts keyed by IP: _machines (connected-machine registry) and
    _monitors (occupancy monitors). disconnect(ip) cleans both atomically.
    The monitor mechanism is generic (Engine-agnostic): callers pass an
    opaque check_factory and on_free callback.
    """

    def __init__(self, log: logging.Logger | None = None) -> None:
        self._machines: dict[str, _MachineState] = {}
        self._log = log or logging.getLogger("SSHMachineRepository")
        # One occupancy monitor per connected IP; keyed identically to
        # _machines so disconnect(ip) cancels only that machine's monitor.
        self._monitors: dict[str, asyncio.Task[None]] = {}

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
    #   PURPOSE: Public API — translates transport errors into domain MachineConnectionError.
    #   INPUTS: { ip, username, client_keys, *, port, connect_timeout, data_dir, engines_dir, tasks_dir, jump_host, jump_username }
    #   OUTPUTS: { ConnectedMachine - the newly registered machine }
    #   SIDE_EFFECTS: Opens SSH connection, detects platform, stores _MachineState.
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-EXCEPTIONS
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
    ) -> ConnectedMachine:
        """Open SSH connection, detect platform, return domain machine.

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
            raise MachineConnectionError(ip, str(err)) from err

    # START_CONTRACT: SSHMachineRepository._connect_impl
    #   PURPOSE: Inner connection implementation with backoff retry on SSHRetryExc.
    #   INPUTS: { same as connect }
    #   OUTPUTS: { ConnectedMachine }
    #   SIDE_EFFECTS: Opens SSH, detects platform, stores _MachineState.
    #   LINKS: M-SSH-REPOSITORY
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
    ) -> ConnectedMachine:
        """Open SSH connection, detect platform, return domain machine (inner impl with backoff)."""
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
        self._machines[ip] = _MachineState(
            conn=conn,
            conn_opts=conn_opts,
            machine=machine,
            adapter=adapter,
            platforms=platforms,
            data_dir=rd,
            engines_dir=re,
            tasks_dir=rt,
        )
        return machine

    # START_CONTRACT: SSHMachineRepository.disconnect
    #   PURPOSE: Close SSH for ip, cancel only that machine's occupancy monitor, remove state.
    #   INPUTS: { ip: str - IP of the machine to disconnect }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Cancels and awaits the occupancy monitor registered for ip (if any);
    #     closes the SSH connection; removes ip from _machines and _monitors.
    #     SHALL NOT cancel monitors registered for any other IP.
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository.disconnect
    async def disconnect(self, ip: str) -> None:
        """Close connection for a machine and cancel only that machine's monitor."""
        # START_BLOCK_POP_MACHINE
        state = self._machines.pop(ip, None)
        if state is None:
            return
        # END_BLOCK_POP_MACHINE
        # START_BLOCK_CANCEL_MONITOR
        # Pop before await so a re-entry race cannot re-insert the cancelled task.
        task = self._monitors.pop(ip, None)
        if task is not None:
            self._log.debug("[SSHRepository][disconnect][CANCEL_MONITOR] ip=%s", ip)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # END_BLOCK_CANCEL_MONITOR
        # START_BLOCK_CLOSE_CONN
        if state.conn._transport:
            self._log.debug("[SSHRepository][disconnect] ip=%s", ip)
            state.conn.close()
            await state.conn.wait_closed()
        # END_BLOCK_CLOSE_CONN

    # START_CONTRACT: SSHMachineRepository.disconnect_all
    #   PURPOSE: Disconnect all machines.
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository.disconnect_all
    async def disconnect_all(self) -> None:
        """Close all connections."""
        for ip in list(self._machines):
            await self.disconnect(ip)

    # ---- Queries ----

    # START_CONTRACT: SSHMachineRepository.list_free
    #   PURPOSE: Return FREE machines filtered by platform, oldest first.
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineRepository.list_free
    def list_free(self, platforms: list[str] | None) -> list[ConnectedMachine]:
        """Return FREE machines, optionally filtered by platform."""
        result: list[ConnectedMachine] = []
        for state in self._machines.values():
            m = state.machine
            if m.state != MachineState.FREE:
                continue
            if platforms is not None and m.platform not in platforms:
                continue
            result.append(m)
        result.sort(key=lambda m: m.free_since or 0.0)
        return result

    # START_CONTRACT: SSHMachineRepository.list_connected
    #   PURPOSE: Return all registered ConnectedMachine objects (port contract).
    #   INPUTS: { None }
    #   OUTPUTS: { list[ConnectedMachine] }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineRepository.list_connected
    def list_connected(self) -> list[ConnectedMachine]:
        """Return all registered ConnectedMachine objects."""
        return [s.machine for s in self._machines.values()]

    def contains(self, ip: str) -> bool:
        return ip in self._machines

    def __contains__(self, ip: str) -> bool:
        return ip in self._machines

    def __len__(self) -> int:
        return len(self._machines)

    def _get_machine_state(self, ip: str) -> _MachineState | None:
        """Return adapter-internal state for ip, or None."""
        return self._machines.get(ip)

    # START_CONTRACT: SSHMachineRepository.get_machine_state
    #   PURPOSE: Return ConnectedMachine registered for ip, or None (port contract).
    #   INPUTS: { ip: str }
    #   OUTPUTS: { ConnectedMachine | None }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-REPOSITORY, M-DOMAIN-PORTS
    # END_CONTRACT: SSHMachineRepository.get_machine_state
    def get_machine_state(self, ip: str) -> ConnectedMachine | None:
        """Return ConnectedMachine for ip (port contract), or None."""
        state = self._machines.get(ip)
        return state.machine if state is not None else None

    # ---- State transitions ----

    def update_machine(self, machine: ConnectedMachine) -> None:
        """Replace ConnectedMachine in state (occupy/release transitions)."""
        state = self._machines.get(machine.ip)
        if state is not None:
            self._machines[machine.ip] = replace(state, machine=machine)

    def occupy(self, ip: str) -> None:
        """Read-modify-write transitioning the stored machine to BUSY."""
        state = self._machines.get(ip)
        if state is not None:
            self._machines[ip] = replace(state, machine=state.machine.occupy())

    def release(self, ip: str) -> None:
        """Read-modify-write transitioning the stored machine to FREE with free_since=now."""
        state = self._machines.get(ip)
        if state is not None:
            self._machines[ip] = replace(state, machine=state.machine.release())

    # ---- Accessor getters ----

    def get_path(self, ip: str) -> type[PurePath]:
        return self._machines[ip].adapter.path

    def get_quote(self, ip: str) -> QuoteCallable:
        return self._machines[ip].adapter.quote

    def get_hostname(self, ip: str) -> str:
        return self._machines[ip].conn_opts.host

    # ---- Monitor mechanism (generic, Engine-agnostic) ----

    # START_CONTRACT: SSHMachineRepository.install_monitor
    #   PURPOSE: Generic occupancy-monitor installer keyed by IP.
    #   INPUTS: { ip: str, *, interval: float, check_factory: Callable[[], Awaitable[bool]], on_free: Callable[[], None] }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates an asyncio.Task keyed by ip in _monitors. If a monitor is
    #     already registered for ip, cancels it (fire-and-forget; this method is
    #     synchronous and cannot await) before installing the new one. The
    #     done-callback pops ip only when the registering task still owns the slot
    #     (identity check protects re-registrations).
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository.install_monitor
    def install_monitor(
        self,
        ip: str,
        *,
        interval: float,
        check_factory: Callable[[], Awaitable[bool]],
        on_free: Callable[[], None],
    ) -> None:
        """Install a generic occupancy monitor for ip.

        The monitor sleeps `interval`, awaits `check_factory()`, and calls
        `on_free()` then breaks when the check returns False. Re-installing
        for an already-monitored IP cancels the prior monitor first.
        """

        async def _checker() -> None:
            try:
                while True:
                    await asyncio.sleep(interval)
                    busy = await check_factory()
                    if not busy:
                        on_free()
                        break
            except asyncio.CancelledError:
                pass

        # START_BLOCK_REPLACE_PRIOR
        prior = self._monitors.get(ip)
        if prior is not None and not prior.done():
            prior.cancel()
        # END_BLOCK_REPLACE_PRIOR
        task = asyncio.create_task(_checker())

        # START_BLOCK_INSTALL_DONE_CB
        def _on_done(_t: asyncio.Task[None]) -> None:
            # Only evict if the slot still points at us; a re-registered
            # replacement must survive the prior task's completion.
            if self._monitors.get(ip) is _t:
                self._monitors.pop(ip, None)

        task.add_done_callback(_on_done)
        self._monitors[ip] = task
        # END_BLOCK_INSTALL_DONE_CB

    # START_CONTRACT: SSHMachineRepository.cancel_monitor
    #   PURPOSE: Pop + cancel monitor for ip (no await).
    #   INPUTS: { ip: str }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Pops _monitors[ip] (if any) and cancels the task; does NOT await.
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineRepository.cancel_monitor
    def cancel_monitor(self, ip: str) -> None:
        """Pop and cancel the monitor for ip (no await)."""
        task = self._monitors.pop(ip, None)
        if task is not None:
            task.cancel()
