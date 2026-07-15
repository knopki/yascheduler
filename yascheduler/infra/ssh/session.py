# FILE: yascheduler/infra/ssh/session.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Connected-machine entity handle owning SSH connection, machine state, and per-session monitor lifecycle.
#   SCOPE: SSHMachineSession class (owns _conn, _adapter, _machine, _closed, _monitor_task) + my_backoff_exc canonical partial.
#   DEPENDS: M-DOMAIN, M-SSH-EXCEPTIONS, M-PLATFORM
#   LINKS: M-SSH-SESSION
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   my_backoff_exc - Partial backoff decorator for SSHRetryExc (canonical copy)
#   SSHMachineSession - Concrete MachineSession implementation owning connection, adapter, machine snapshot, monitor task, per-session CPU cache, and teardown
#   _prime_ncpus_cache - Private method to seed the per-session CPU cache (called by SSHMachineRepository.connect)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.3.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v1.2.0 - remove log parameter from __init__/signatures; bind module-local logger = get_logger("M-SSH-SESSION") at module top
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING

import backoff

from yascheduler.domain import ConnectedMachine, ProcessResult

from .exceptions import AllSSHRetryExc, SSHRetryExc
from .platform import make_run_fn

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Sequence,
    )
    from pathlib import Path, PurePath
    from re import Pattern

    from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions
    from asyncssh.process import SSHCompletedProcess
    from asyncssh.sftp import SFTPClient

    from yascheduler.domain import EngineRepository

    from .platform import (
        ProcessInfo,
        QuoteCallable,
        RemoteMachineAdapter,
    )

my_backoff_exc = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SSHRetryExc,
)


# START_CONTRACT: SSHMachineSession
#   PURPOSE: Concrete MachineSession — connected-machine entity handle owning connection, adapter, mutable machine snapshot, and per-session monitor task. Implements the MachineSession Protocol.
#   INPUTS: { hostname: str, conn: SSHClientConnection, conn_opts: SSHClientConnectionOptions, machine: ConnectedMachine, adapter: RemoteMachineAdapter, platforms: Sequence[str], data_dir: PurePath, engines_dir: PurePath, tasks_dir: PurePath }
#   OUTPUTS: { None - instance methods return operation results }
#   SIDE_EFFECTS: Owns an open SSH connection and at most one asyncio.Task (the monitor). _close() cancels the monitor, awaits its cancellation, and closes the connection. Idempotent on _closed.
#   LINKS: M-SSH-SESSION, M-DOMAIN-PORTS, M-PLATFORM
# END_CONTRACT: SSHMachineSession
class SSHMachineSession:
    """SSHMachineSession — concrete connected-machine entity handle.

    Owns the connection, adapter, mutable machine snapshot, and the per-
    session monitor task. Constructed by SSHMachineRepository.connect at
    connect time; torn down by SSHMachineRepository.disconnect via _close().

    Base primitives read self._conn and self._adapter directly — NO hostname-keyed
    lookup, NO call into the repository, NO private state reach-through.
    """

    def __init__(
        self,
        hostname: str,
        conn: SSHClientConnection,
        conn_opts: SSHClientConnectionOptions,
        machine: ConnectedMachine,
        adapter: RemoteMachineAdapter,
        platforms: Sequence[str],
        data_dir: PurePath,
        engines_dir: PurePath,
        tasks_dir: PurePath,
    ) -> None:
        self._hostname = hostname
        self._conn = conn
        self._conn_opts = conn_opts
        self._machine = machine
        self._adapter = adapter
        self._platforms = platforms
        self._data_dir = data_dir
        self._engines_dir = engines_dir
        self._tasks_dir = tasks_dir
        self._closed = False
        self._monitor_task: asyncio.Task[None] | None = None
        self._cached_ncpus: int | None = None

    # ---- Domain face ----

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def machine(self) -> ConnectedMachine:
        return self._machine

    @property
    def is_closed(self) -> bool:
        return self._closed

    # START_CONTRACT: SSHMachineSession.occupy
    #   PURPOSE: Read-modify-write transitioning the snapshot to BUSY.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None — internal state only.
    #   LINKS: M-SSH-SESSION, M-DOMAIN-MODEL
    # END_CONTRACT: SSHMachineSession.occupy
    def occupy(self) -> None:
        self._machine = self._machine.occupy()

    # START_CONTRACT: SSHMachineSession.release
    #   PURPOSE: Read-modify-write transitioning the snapshot to FREE with free_since = time.monotonic().
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None — internal state only.
    #   LINKS: M-SSH-SESSION, M-DOMAIN-MODEL
    # END_CONTRACT: SSHMachineSession.release
    def release(self) -> None:
        self._machine = self._machine.release()

    # START_CONTRACT: SSHMachineSession.update
    #   PURPOSE: Replace the internal machine snapshot (used by rollback paths).
    #   INPUTS: { machine: ConnectedMachine - the new snapshot }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None — internal state only.
    #   LINKS: M-SSH-SESSION, M-DOMAIN-MODEL
    # END_CONTRACT: SSHMachineSession.update
    def update(self, machine: ConnectedMachine) -> None:
        self._machine = machine

    # ---- Connect-time config (read-only) ----

    @property
    def adapter(self) -> RemoteMachineAdapter:
        return self._adapter

    @property
    def platforms(self) -> Sequence[str]:
        return self._platforms

    @property
    def data_dir(self) -> PurePath:
        return self._data_dir

    @property
    def engines_dir(self) -> PurePath:
        return self._engines_dir

    @property
    def tasks_dir(self) -> PurePath:
        return self._tasks_dir

    # ---- Cache priming (repository only) ----

    def _prime_ncpus_cache(self, ncpus: int) -> None:
        """Prime the CPU-core cache with an already-discovered value (called by SSHMachineRepository.connect)."""
        self._cached_ncpus = ncpus

    # ---- Adapter-derived accessors (read-only) ----

    @property
    def path(self) -> type[PurePath]:
        return self._adapter.path

    @property
    def quote(self) -> QuoteCallable:
        return self._adapter.quote

    # ---- Base primitives ----

    async def run(self, cmd: str) -> ProcessResult:
        """Run command and return structured result."""
        proc = await self.run_full(cmd)
        return ProcessResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=proc.stdout
            if isinstance(proc.stdout, str)
            else str(proc.stdout or ""),
            stderr=proc.stderr
            if isinstance(proc.stderr, str)
            else str(proc.stderr or ""),
        )

    # START_CONTRACT: SSHMachineSession.run_full
    #   PURPOSE: Run command via self._adapter and return raw SSHCompletedProcess; retries on SSHRetryExc.
    #   INPUTS: { cmd: str - command to run }
    #   OUTPUTS: { SSHCompletedProcess - raw asyncssh result }
    #   SIDE_EFFECTS: Runs command on remote machine via SSH.
    #   LINKS: M-SSH-SESSION, M-PLATFORM
    # END_CONTRACT: SSHMachineSession.run_full
    @my_backoff_exc()
    async def run_full(self, cmd: str) -> SSHCompletedProcess:
        """Run command via self._conn + self._adapter directly (no repository call)."""
        return await self._adapter.run(self._conn, self._adapter.quote, cmd)

    async def run_bg(self, cmd: str, *, cwd: str | None = None) -> None:
        """Start background process on remote machine (single attempt — spawn is non-idempotent)."""
        await self._adapter.run_bg(self._conn, self._adapter.quote, cmd, cwd=cwd)

    async def upload(self, local: Path, remote: str) -> None:
        """Upload file to remote machine via SFTP (single attempt — put is non-idempotent)."""
        async with self._conn.start_sftp_client() as sftp:
            await sftp.put(str(local), remote)

    @asynccontextmanager
    async def open_sftp(self) -> AsyncIterator[SFTPClient]:
        """Open SFTP client (async context manager)."""
        async with self._conn.start_sftp_client() as sftp:
            yield sftp

    # START_CONTRACT: SSHMachineSession.get_cpu_cores
    #   PURPOSE: Return CPU core count, memoized per session.
    #   INPUTS: { None }
    #   OUTPUTS: { int - positive CPU core count }
    #   SIDE_EFFECTS: On cache miss, runs remote command via SSH; stores result in per-session cache so subsequent calls return without SSH exec.
    #   LINKS: M-PLATFORM-ADAPTERS, M-PLATFORM-RUN-FN
    # END_CONTRACT: SSHMachineSession.get_cpu_cores
    @my_backoff_exc()
    async def get_cpu_cores(self) -> int:
        """Return CPU core count, memoized per session (cache miss invokes adapter with retry; cache hit returns without adapter invocation)."""
        # START_BLOCK_CHECK_CACHE
        if self._cached_ncpus is not None:
            return self._cached_ncpus
        # END_BLOCK_CHECK_CACHE
        # START_BLOCK_DISCOVER
        ncpus = await self._adapter.get_cpu_cores(
            make_run_fn(self._conn, self._adapter)
        )
        self._cached_ncpus = ncpus
        # END_BLOCK_DISCOVER
        return ncpus

    # START_CONTRACT: SSHMachineSession.setup_node
    #   PURPOSE: Install engine dependencies on the remote node via self._adapter.setup_node with make_run_fn(conn, adapter).
    #   INPUTS: { engines: EngineRepository - engines to install (filtered to self._platforms) }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Runs setup commands on the remote machine via self._conn; retries on AllSSHRetryExc.
    #   LINKS: M-SSH-SESSION, M-PLATFORM, M-DOMAIN-ENGINE
    # END_CONTRACT: SSHMachineSession.setup_node
    async def setup_node(self, engines: EngineRepository) -> None:
        """Install engine dependencies on remote node."""
        retry = my_backoff_exc(exception=AllSSHRetryExc)
        await retry(self._adapter.setup_node)(
            conn=self._conn,
            run=make_run_fn(self._conn, self._adapter),
            quote=self._adapter.quote,
            engines=engines.filter_platforms(self._platforms),
            engines_dir=self._engines_dir,
        )

    async def pgrep(
        self,
        pattern: str | Pattern[str],
        full: bool = True,
    ) -> AsyncGenerator[ProcessInfo, None]:
        """Yield remote processes matching pattern."""
        async for proc in self._adapter.pgrep(
            self._conn, self._adapter.quote, pattern, full
        ):
            yield proc

    async def list_processes(self) -> AsyncGenerator[ProcessInfo, None]:
        """Yield all running processes on remote machine."""
        async for proc in self._adapter.list_processes(self._conn, None):
            yield proc

    # ---- Monitor mechanism (generic, Engine-agnostic) ----

    # START_CONTRACT: SSHMachineSession.install_monitor
    #   PURPOSE: Generic occupancy-monitor installer on this session. Re-installing cancels the prior monitor before installing the new one. Idempotent on a closed session: returns immediately without installing.
    #   INPUTS: { *, interval: float, check_factory: Callable[[], Awaitable[bool]], on_free: Callable[[], None] }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates an asyncio.Task stored in self._monitor_task. If a monitor is already installed and live, cancels it (fire-and-forget; this method is synchronous and cannot await) before installing the new one. The done-callback clears self._monitor_task only when the slot still points at the same task (identity check protects re-registrations).
    #   LINKS: M-SSH-SESSION
    # END_CONTRACT: SSHMachineSession.install_monitor
    def install_monitor(
        self,
        *,
        interval: float,
        check_factory: Callable[[], Awaitable[bool]],
        on_free: Callable[[], None],
    ) -> None:
        """Install a generic occupancy monitor on this session.

        The monitor sleeps `interval`, awaits `check_factory()`, and calls
        `on_free()` then breaks when the check returns False. Re-installing
        on a session that already has a live monitor cancels the prior
        monitor first. No-ops on a closed session.
        """
        # START_BLOCK_GUARD_CLOSED
        if self._closed:
            return
        # END_BLOCK_GUARD_CLOSED

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
        prior = self._monitor_task
        if prior is not None and not prior.done():
            prior.cancel()
        # END_BLOCK_REPLACE_PRIOR
        task = asyncio.create_task(_checker())

        # START_BLOCK_INSTALL_DONE_CB
        def _on_done(_t: asyncio.Task[None]) -> None:
            # Only clear if the slot still points at us; a re-registered
            # replacement must survive the prior task's completion.
            if self._monitor_task is _t:
                self._monitor_task = None

        task.add_done_callback(_on_done)
        self._monitor_task = task
        # END_BLOCK_INSTALL_DONE_CB

    # START_CONTRACT: SSHMachineSession.cancel_monitor
    #   PURPOSE: Cancel this session's monitor (if any); does NOT await.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Pops self._monitor_task (if any) and cancels the task; does NOT await.
    #   LINKS: M-SSH-SESSION
    # END_CONTRACT: SSHMachineSession.cancel_monitor
    def cancel_monitor(self) -> None:
        """Pop and cancel this session's monitor (no await)."""
        task = self._monitor_task
        if task is not None:
            self._monitor_task = None
            task.cancel()

    # ---- Lifecycle (called only by SSHMachineRepository.disconnect) ----

    # START_CONTRACT: SSHMachineSession._close
    #   PURPOSE: Idempotent teardown — mark closed, cancel monitor, await monitor cancellation, close SSH connection. Called only by SSHMachineRepository.disconnect.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Sets self._closed = True synchronously BEFORE any await (preserves disconnect-scope isolation invariant: a re-entry race cannot re-insert a cancelled task because the session reports closed before yielding control). Cancels self._monitor_task (if any) and awaits it suppressing asyncio.CancelledError. Closes self._conn if its transport is open and awaits wait_closed().
    #   LINKS: M-SSH-SESSION, M-SSH-REPOSITORY
    # END_CONTRACT: SSHMachineSession._close
    async def _close(self) -> None:
        """Idempotent teardown: mark closed → cancel monitor → await monitor → close conn."""
        # START_BLOCK_GUARD_ALREADY_CLOSED
        if self._closed:
            return
        # END_BLOCK_GUARD_ALREADY_CLOSED
        # START_BLOCK_MARK_CLOSED
        # Set synchronously BEFORE any await — disconnect-scope isolation invariant.
        self._closed = True
        # END_BLOCK_MARK_CLOSED
        # START_BLOCK_CANCEL_MONITOR
        task = self._monitor_task
        if task is not None:
            self._monitor_task = None
            logger.debug("CANCEL_MONITOR", extra={"hostname": self._hostname})
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # END_BLOCK_CANCEL_MONITOR
        # START_BLOCK_CLOSE_CONN
        if self._conn._transport:
            logger.debug("CLOSE", extra={"hostname": self._hostname})
            self._conn.close()
            await self._conn.wait_closed()
        # END_BLOCK_CLOSE_CONN
