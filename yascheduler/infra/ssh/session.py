"""Connected-machine entity handle owning SSH connection, machine state, and per-session monitor lifecycle."""
# region MODULE_CONTRACT
# PURPOSE: SSHMachineSession — concrete MachineSession entity handle owning an SSH connection, adapter, mutable machine snapshot, and per-session monitor task.
# SCOPE: SSHMachineSession class and my_retry canonical partial.
# DEPENDENCIES: USES API: asyncssh (SSHClientConnection, SFTPClient)
# KEYWORDS: session, ssh, machine, monitor, lifecycle, SSHMachineSession
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from functools import partial
from subprocess import DEVNULL
from typing import TYPE_CHECKING

from yascheduler.domain import ConnectedMachine, ProcessResult
from yascheduler.shared import retry

from .platform import AllSSHRetryExc, SSHRetryExc, make_run_fn

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

__all__ = ["SSHMachineSession", "my_retry"]
logger = logging.getLogger(__name__)
my_retry = partial(retry, on=SSHRetryExc, max_time=60)

# Grace window (seconds) for best-effort early-exit detection in run_bg.
# A process still running past this is considered a normal spawn; a process
# that dies with non-zero exit within it triggers a user-visible WARNING.
_SPAWN_GRACE_SECONDS = 1.0


# region CLASS_SSHMachineSession
# PURPOSE: Concrete MachineSession — connected-machine entity handle owning connection, adapter, mutable machine snapshot, and per-session monitor task.
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
        """Remote machine hostname (immutable after construction)."""
        return self._hostname

    @property
    def machine(self) -> ConnectedMachine:
        """Connected machine runtime state."""
        return self._machine

    @property
    def is_closed(self) -> bool:
        """``True`` when the underlying connection is closed."""
        return self._closed

    # region METHOD_occupy
    # PURPOSE: Read-modify-write transitioning the snapshot to BUSY.
    # REQUIRES: session.machine.state == FREE — the read-modify-write transitions FREE to BUSY; calling on a BUSY machine is a programmer error.
    def occupy(self) -> None:
        """Read-modify-write transitioning the snapshot to BUSY."""
        self._machine = self._machine.occupy()

    # endregion METHOD_occupy

    # region METHOD_release
    # PURPOSE: Read-modify-write transitioning the snapshot to FREE with free_since = time.monotonic().
    # ENSURES: session.machine.state == FREE with free_since = time.monotonic().
    def release(self) -> None:
        """Read-modify-write transitioning the snapshot to FREE with free_since = time."""
        self._machine = self._machine.release()

    # endregion METHOD_release

    # region METHOD_update
    # PURPOSE: Replace the internal machine snapshot (used by rollback paths).
    # ENSURES: session.machine is replaced wholesale with the passed ConnectedMachine — used by rollback paths that need to restore a prior snapshot.
    def update(self, machine: ConnectedMachine) -> None:
        """Replace the internal machine snapshot (used by rollback paths)."""
        self._machine = machine

    # endregion METHOD_update

    # ---- Connect-time config (read-only) ----

    @property
    def adapter(self) -> RemoteMachineAdapter:
        """Platform-specific remote machine adapter (resolved at connect time)."""
        return self._adapter

    @property
    def platforms(self) -> Sequence[str]:
        """Platform tags resolved at connect time."""
        return self._platforms

    @property
    def data_dir(self) -> PurePath:
        """Remote data directory path configured at connect time."""
        return self._data_dir

    @property
    def engines_dir(self) -> PurePath:
        """Remote engines directory path configured at connect time."""
        return self._engines_dir

    @property
    def tasks_dir(self) -> PurePath:
        """Remote tasks directory path configured at connect time."""
        return self._tasks_dir

    # ---- Cache priming (repository only) ----

    # region METHOD__prime_ncpus_cache
    # PURPOSE: Let SSHMachineRepository.connect seed the session's CPU-core cache with the value it already discovered, so the first get_cpu_cores() call on the new session returns without re-invoking the adapter.
    def _prime_ncpus_cache(self, ncpus: int) -> None:
        """Prime the CPU-core cache with an already-discovered value (called by SSHMachineRepository.connect)."""
        self._cached_ncpus = ncpus

    # endregion METHOD__prime_ncpus_cache
    # ---- Adapter-derived accessors (read-only) ----

    @property
    def path(self) -> type[PurePath]:
        """``PurePath`` subclass matching the remote OS path semantics."""
        return self._adapter.path

    @property
    def quote(self) -> QuoteCallable:
        """Shell-quoting callable matching the remote OS syntax."""
        return self._adapter.quote

    # ---- Base primitives ----

    # region METHOD_run
    # PURPOSE: Run a command and return a structured ProcessResult so callers branching on exit_code/stdout/stderr do not touch the raw asyncssh process object.
    # ENSURES: Returns a ProcessResult with exit_code derived from proc.returncode (-1 when None), stdout/stderr coerced to str.
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

    # endregion METHOD_run
    # region METHOD_run_full
    # PURPOSE: Run command via self._adapter and return raw SSHCompletedProcess; retries on SSHRetryExc. Callers branching on exit_code/stdout/stderr should prefer run() for the structured ProcessResult.
    @my_retry()
    async def run_full(self, cmd: str) -> SSHCompletedProcess:
        """Run command via self._conn + self._adapter directly (no repository call)."""
        return await self._adapter.run(self._conn, self._adapter.quote, cmd)

    # endregion METHOD_run_full

    # region METHOD_run_bg
    # PURPOSE: Spawn a background process on the remote machine — single attempt, no retry — so daemon-style processes stay running after the SSH call returns.
    # INVARIANTS: Single attempt — spawn is non-idempotent; a successful remote side-effect followed by a lost client confirmation would produce a duplicate on retry; delegates to self._adapter.run_bg(self._conn, self._adapter.quote, cmd, cwd=cwd) — no hostname-keyed lookup, no call into the repository.
    # ENSURES: Best-effort early-exit detection — awaits proc.wait() with a short grace window; a process that dies with non-zero exit within that window emits a user-visible WARNING with returncode and stderr so a missing/broken binary is diagnosed at spawn time, not later as missing output files.
    async def run_bg(self, cmd: str, *, cwd: str | None = None) -> None:
        """Start background process on remote machine (single attempt — spawn is non-idempotent)."""
        proc = await self._adapter.run_bg(self._conn, self._adapter.quote, cmd, cwd=cwd)
        # region BLOCK_run_bg_early_exit
        # PURPOSE: detect a process that dies on startup (missing binary,
        # crash, permission denied).
        # A short grace window distinguishes "never started" from "running". proc.wait()
        # does not kill the process on timeout — it keeps running on the remote. stderr
        # is captured via PIPE so the early-exit path can surface the remote shell's
        # error text (e.g. "No such file or directory"). Only a non-zero exit is
        # reported — a clean exit within the window is a legitimately short task, not an
        # early-exit failure.
        try:
            completed = await proc.wait(timeout=_SPAWN_GRACE_SECONDS)
        except asyncio.TimeoutError:
            # Process still running past the grace window — normal spawn.
            # Drop the stderr PIPE so it does not accumulate indefinitely and
            # back-pressure the remote process once the SSH channel window
            # fills. redirect_stderr(DEVNULL) tells the remote to stop sending
            # stderr over the channel; the process keeps running.
            await proc.redirect_stderr(DEVNULL)
            return
        if completed.returncode == 0:
            # Clean exit within grace — short task, not a failure.
            return
        stderr = (
            completed.stderr
            if isinstance(completed.stderr, str)
            else str(
                completed.stderr or "",
            )
        )
        logger.warning(
            "Spawn on %s exited immediately with code %s (cmd=%s): %s",
            self._hostname,
            completed.returncode,
            cmd,
            stderr.strip() or "<no stderr>",
        )
        logger.debug(
            "SPAWN_EARLY_EXIT",
            extra={
                "hostname": self._hostname,
                "cmd": cmd,
                "cwd": cwd,
                "returncode": completed.returncode,
                "exit_signal": completed.exit_signal,
                "stderr": stderr,
            },
        )
        # endregion BLOCK_run_bg_early_exit

    # endregion METHOD_run_bg
    # region METHOD_upload
    # PURPOSE: Upload a local file to a remote path via SFTP — single attempt, no retry — so a partial upload followed by a retry does not produce a corrupt-or-duplicate remote file.
    # INVARIANTS: Single attempt — sftp.put is non-idempotent; opens a fresh SFTP client via self._conn.start_sftp_client() per call.
    async def upload(self, local: Path, remote: str) -> None:
        """Upload file to remote machine via SFTP (single attempt — put is non-idempotent)."""
        async with self._conn.start_sftp_client() as sftp:
            await sftp.put(str(local), remote)

    # endregion METHOD_upload
    # region METHOD_open_sftp
    # PURPOSE: Hand callers an async-context-manager SFTP client bound to this session's connection so per-file operations can be batched without each re-opening a channel.
    @asynccontextmanager
    async def open_sftp(self) -> AsyncIterator[SFTPClient]:
        """Open SFTP client (async context manager)."""
        async with self._conn.start_sftp_client() as sftp:
            yield sftp

    # endregion METHOD_open_sftp
    # region METHOD_get_cpu_cores
    # PURPOSE: Return CPU core count, memoized per session. Cache miss invokes adapter with retry; cache hit returns without adapter invocation.
    @my_retry()
    async def get_cpu_cores(self) -> int:
        """Return CPU core count, memoized per session (cache miss invokes adapter with retry; cache hit returns without adapter invocation)."""
        # region BLOCK_check_cache
        if self._cached_ncpus is not None:
            return self._cached_ncpus
        # endregion BLOCK_check_cache
        # region BLOCK_discover
        ncpus = await self._adapter.get_cpu_cores(
            make_run_fn(self._conn, self._adapter),
        )
        self._cached_ncpus = ncpus
        # endregion BLOCK_discover
        return ncpus

    # endregion METHOD_get_cpu_cores

    # region METHOD_setup_node
    # PURPOSE: Install engine dependencies on the remote node via self._adapter.setup_node with make_run_fn(conn, adapter).
    async def setup_node(self, engines: EngineRepository) -> None:
        """Install engine dependencies on remote node."""
        retry = my_retry(on=AllSSHRetryExc)
        await retry(self._adapter.setup_node)(
            conn=self._conn,
            run=make_run_fn(self._conn, self._adapter),
            quote=self._adapter.quote,
            engines=engines.filter_platforms(self._platforms),
            engines_dir=self._engines_dir,
        )

    # endregion METHOD_setup_node

    # region METHOD_pgrep
    # PURPOSE: Yield remote processes whose name or command line matches a pattern so occupancy checks can detect if a calculation is still running.
    async def pgrep(
        self,
        pattern: str | Pattern[str],
        full: bool = True,
    ) -> AsyncGenerator[ProcessInfo, None]:
        """Yield remote processes matching pattern."""
        async for proc in self._adapter.pgrep(
            self._conn,
            self._adapter.quote,
            pattern,
            full=full,
        ):
            yield proc

    # endregion METHOD_pgrep
    # region METHOD_list_processes
    # PURPOSE: Yield every running process on the remote machine so an operator can inspect what is consuming a node.
    async def list_processes(self) -> AsyncGenerator[ProcessInfo, None]:
        """Yield all running processes on remote machine."""
        async for proc in self._adapter.list_processes(self._conn, None):
            yield proc

    # endregion METHOD_list_processes

    # region METHOD_install_monitor
    # PURPOSE: Generic occupancy-monitor installer on this session. Re-installing cancels the prior monitor before installing the new one. Idempotent on a closed session.
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
        # region BLOCK_guard_closed
        if self._closed:
            return
        # endregion BLOCK_guard_closed

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

        # region BLOCK_replace_prior
        prior = self._monitor_task
        if prior is not None and not prior.done():
            prior.cancel()
        # endregion BLOCK_replace_prior
        task = asyncio.create_task(_checker())

        # region BLOCK_install_done_cb
        def _on_done(_t: asyncio.Task[None]) -> None:
            # Only clear if the slot still points at us; a re-registered
            # replacement must survive the prior task's completion.
            if self._monitor_task is _t:
                self._monitor_task = None

        task.add_done_callback(_on_done)
        self._monitor_task = task
        # endregion BLOCK_install_done_cb

    # endregion METHOD_install_monitor

    # region METHOD_cancel_monitor
    # PURPOSE: Cancel this session's monitor (if any); does NOT await.
    def cancel_monitor(self) -> None:
        """Pop and cancel this session's monitor (no await)."""
        task = self._monitor_task
        if task is not None:
            self._monitor_task = None
            task.cancel()

    # endregion METHOD_cancel_monitor

    # ---- Lifecycle (called only by SSHMachineRepository.disconnect) ----

    # region METHOD__close
    # PURPOSE: Idempotent teardown — mark closed, cancel monitor, await monitor cancellation, close SSH connection. Called only by SSHMachineRepository.disconnect.
    # ENSURES: self._closed set True synchronously BEFORE any await (disconnect-scope isolation invariant).
    async def _close(self) -> None:
        """Idempotent teardown: mark closed → cancel monitor → await monitor → close conn."""
        # region BLOCK_guard_already_closed
        if self._closed:
            return
        # endregion BLOCK_guard_already_closed
        # region BLOCK_mark_closed
        # Set synchronously BEFORE any await — disconnect-scope isolation invariant.
        self._closed = True
        # endregion BLOCK_mark_closed
        # region BLOCK_cancel_monitor
        task = self._monitor_task
        if task is not None:
            self._monitor_task = None
            logger.debug("CANCEL_MONITOR", extra={"hostname": self._hostname})
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        # endregion BLOCK_cancel_monitor
        # region BLOCK_close_conn
        if self._conn._transport:  # noqa: SLF001
            logger.debug("CLOSE", extra={"hostname": self._hostname})
            self._conn.close()
            await self._conn.wait_closed()
        # endregion BLOCK_close_conn

    # endregion METHOD__close


# endregion CLASS_SSHMachineSession
