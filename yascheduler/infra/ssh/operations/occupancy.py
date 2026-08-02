"""OccupancyChecker — pgrep/cmd-based occupancy check logic + monitor installer composing the session's generic monitor mechanism. Stateless: takes (log) at construction, (session, ...) per call."""
# region MODULE_CONTRACT
# PURPOSE: Occupancy probing via pgrep or shell command on a remote session; composes with session.install_monitor for background monitoring.
# SCOPE: OccupancyChecker class.
# KEYWORDS: occupancy, pgrep, monitor, check, OccupancyChecker
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from yascheduler.domain import MachineState
from yascheduler.infra.ssh.platform.types import SSHRetryExc

if TYPE_CHECKING:
    from yascheduler.domain import Engine, MachineSession

__all__ = ["OccupancyChecker"]
logger = logging.getLogger(__name__)


# region CLASS_OccupancyChecker
# PURPOSE: pgrep/cmd-based occupancy check logic + monitor installer composing the session's generic monitor mechanism.
class OccupancyChecker:
    """pgrep/cmd-based occupancy check + monitor installer.

    Stateless: takes (log) at construction, (session, ...) per call. The
    monitor mechanism (asyncio.Task, sleep/cancel) lives on the session.
    start_occupancy_check composes: session.occupy(), then
    session.install_monitor(interval=..., check_factory=...,
    on_free=session.release).
    """

    # region METHOD__occupancy_by_pgrep
    # PURPOSE: Check occupancy via pgrep on check_pname. Returns True (busy) when at least one process matches OR when SSH fails (safe default).
    async def _occupancy_by_pgrep(self, session: MachineSession, pattern: str) -> bool:
        # region BLOCK_occupancy_pgrep
        try:
            async for proc in session.pgrep(pattern):
                logger.debug(
                    "PGREP",
                    extra={
                        "hostname": session.hostname,
                        "pid": proc.pid,
                        "proc_name": proc.name,
                        "cmd": proc.command,
                    },
                )
                return True
            logger.debug(
                "PGREP_FREE",
                extra={"hostname": session.hostname, "pattern": pattern},
            )
        except SSHRetryExc as exc:
            logger.warning(
                "Machine %s pgrep failed, assuming busy: %s",
                session.hostname,
                exc,
            )
            return True
        else:
            return False
        # endregion BLOCK_occupancy_pgrep

    # endregion METHOD__occupancy_by_pgrep

    # region METHOD__occupancy_by_cmd
    # PURPOSE: Check occupancy via check_cmd exit code. Returns True (busy) when exit code matches expected_code OR when SSH fails (safe default).
    async def _occupancy_by_cmd(
        self,
        session: MachineSession,
        cmd: str,
        expected_code: int,
    ) -> bool:
        # region BLOCK_occupancy_cmd
        try:
            proc = await session.run_full(cmd)
            logger.debug(
                "CHECK_CMD",
                extra={
                    "hostname": session.hostname,
                    "cmd": cmd,
                    "exit_code": proc.returncode,
                    "expected": expected_code,
                },
            )
        except SSHRetryExc as exc:
            logger.warning(
                "Machine %s check_cmd failed, assuming busy: %s",
                session.hostname,
                exc,
            )
            return True
        else:
            return proc.returncode == expected_code
        # endregion BLOCK_occupancy_cmd

    # endregion METHOD__occupancy_by_cmd

    # region METHOD_occupancy_check
    # PURPOSE: Check if engine process is still running via pgrep or check_cmd. Returns True (busy) when process found OR SSH fails (safe default).
    async def occupancy_check(self, session: MachineSession, config: Engine) -> bool:
        """Check if engine process is still running.

        Returns True (busy) when the engine process is found or when SSH
        check fails — the machine is presumed busy to avoid releasing a machine
        that still has a running task.
        Returns False (free) only when the check succeeds and finds no process.
        """
        # region BLOCK_occupancy_dispatch
        if config.check_pname:
            return await self._occupancy_by_pgrep(session, config.check_pname)
        if config.check_cmd:
            return await self._occupancy_by_cmd(
                session,
                config.check_cmd,
                config.check_cmd_code,
            )
        logger.debug("NO_CHECK", extra={"hostname": session.hostname})
        return False
        # endregion BLOCK_occupancy_dispatch

    # endregion METHOD_occupancy_check

    # region METHOD_start_occupancy_check
    # PURPOSE: Background task periodically checks occupancy, releases machine when done.
    # REQUIRES: session.machine.state is FREE or BUSY — occupy() is called ONLY if FREE (idempotent — start_task_on_machine already occupied it on the deploy path).
    def start_occupancy_check(self, session: MachineSession, config: Engine) -> None:
        """Start background occupancy monitoring.

        Occupies the session ONLY if it is currently FREE (idempotent —
        start_task_on_machine already occupied it on the deploy path).
        Re-registering for an already-monitored session cancels the prior
        monitor (session.install_monitor handles the replacement).
        """
        if session.machine.state == MachineState.FREE:
            session.occupy()

        async def _check_factory() -> bool:
            # No asyncio.wait_for: on Python <3.12 it swallows the monitor task's
            # cancellation, so SSHMachineSession._close() hangs on task.cancel().
            try:
                return await self.occupancy_check(session, config)
            except Exception:
                logger.exception(
                    "Occupancy check failed for %s on %s",
                    config.name,
                    session.hostname,
                )
                return True

        session.install_monitor(
            interval=config.sleep_interval,
            check_factory=_check_factory,
            on_free=session.release,
        )

    # endregion METHOD_start_occupancy_check


# endregion CLASS_OccupancyChecker
