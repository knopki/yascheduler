# FILE: yascheduler/infra/ssh/operations/occupancy.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: OccupancyChecker — pgrep/cmd-based occupancy check logic + monitor installer composing the session's generic monitor mechanism. Stateless: takes (log) at construction, (session, ...) per call.
#   SCOPE: OccupancyChecker: occupancy probing via pgrep or shell command on a remote session.
#   DEPENDS: M-SSH-SESSION, M-DOMAIN-ENGINE, M-SSH-EXCEPTIONS
#   LINKS: M-SSH-OPS-OCCUPANCY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   OccupancyChecker - Occupancy check via pgrep or check_cmd; stateless (log)-only constructor; start_occupancy_check composes session.install_monitor
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - remove log parameter from __init__/signatures; bind module-local logger = get_logger("M-SSH-OPS-OCCUPANCY") at module top
#   PREVIOUS_CHANGE: v1.4.0 - Node-rename-and-fields: session.ip→session.hostname in all log lines (7 sites); hostname=%s→hostname=%s format labels.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

from yascheduler.shared import get_logger

from ..exceptions import SSHRetryExc

if TYPE_CHECKING:
    from yascheduler.domain import Engine, MachineSession

logger = get_logger("M-SSH-OPS-OCCUPANCY")


# START_CONTRACT: OccupancyChecker
#   PURPOSE: pgrep/cmd-based occupancy check logic + monitor installer composing the session's generic monitor mechanism.
#   LINKS: M-SSH-OPS-OCCUPANCY, M-SSH-SESSION
# END_CONTRACT: OccupancyChecker
class OccupancyChecker:
    """pgrep/cmd-based occupancy check + monitor installer.

    Stateless: takes (log) at construction, (session, ...) per call. The
    monitor mechanism (asyncio.Task, sleep/cancel) lives on the session.
    start_occupancy_check composes: session.occupy(), then
    session.install_monitor(interval=..., check_factory=...,
    on_free=session.release).
    """

    def __init__(self) -> None:
        """Initialize OccupancyChecker (stateless)."""

    # START_CONTRACT: OccupancyChecker._occupancy_by_pgrep
    #   PURPOSE: Occupancy check via pgrep on check_pname. Returns True (busy)
    #     when at least one process matches OR when SSH fails (safe default).
    #     Returns False (free) only when pgrep succeeds and yields no process.
    #   INPUTS: { session: MachineSession, pattern: str - process name pattern to match }
    #   OUTPUTS: { bool - True if busy or SSH failed, False if confirmed free }
    #   SIDE_EFFECTS: Runs pgrep command on remote machine.
    async def _occupancy_by_pgrep(self, session: MachineSession, pattern: str) -> bool:
        # START_BLOCK_OCCUPANCY_PGREP
        try:
            async for proc in session.pgrep(pattern):
                logger.trace(
                    "PGREP",
                    hostname=session.hostname,
                    pid=proc.pid,
                    name=proc.name,
                    cmd=proc.command,
                )
                return True
            logger.trace(
                "PGREP_FREE",
                hostname=session.hostname,
                pattern=pattern,
            )
            return False
        except SSHRetryExc as exc:
            logger.warning(
                "Machine %s pgrep failed, assuming busy: %s", session.hostname, exc
            )
            return True
        # END_BLOCK_OCCUPANCY_PGREP

    # START_CONTRACT: OccupancyChecker._occupancy_by_cmd
    #   PURPOSE: Occupancy check via check_cmd exit code. Returns True (busy)
    #     when exit code matches expected_code OR when SSH fails (safe default).
    #     Returns False only when the check succeeds with a non-matching exit code.
    #   INPUTS: { session: MachineSession, cmd: str - check command to run, expected_code: int - busy exit code }
    #   OUTPUTS: { bool - True if busy or SSH failed, False if confirmed free }
    #   SIDE_EFFECTS: Runs check command on remote machine.
    async def _occupancy_by_cmd(
        self, session: MachineSession, cmd: str, expected_code: int
    ) -> bool:
        # START_BLOCK_OCCUPANCY_CMD
        try:
            proc = await session.run_full(cmd)
            logger.trace(
                "CHECK_CMD",
                hostname=session.hostname,
                cmd=cmd,
                exit_code=proc.returncode,
                expected=expected_code,
            )
            return proc.returncode == expected_code
        except SSHRetryExc as exc:
            logger.warning(
                "Machine %s check_cmd failed, assuming busy: %s", session.hostname, exc
            )
            return True
        # END_BLOCK_OCCUPANCY_CMD

    # START_CONTRACT: OccupancyChecker.occupancy_check
    #   PURPOSE: Check if engine process is still running via pgrep or check_cmd.
    #     Returns True (busy) when process found OR when SSH fails (safe default).
    #     Returns False (free) only when check succeeds and finds no process.
    #   INPUTS: { session: MachineSession, config: Engine - engine metadata for checks }
    #   SIDE_EFFECTS: Runs pgrep or check_cmd on remote machine.
    #   LINKS: M-SSH-OPS-OCCUPANCY
    # END_CONTRACT: OccupancyChecker.occupancy_check
    async def occupancy_check(self, session: MachineSession, config: Engine) -> bool:
        """Check if engine process is still running.

        Returns True (busy) when the engine process is found OR when the SSH
        check fails — the machine is presumed busy to avoid releasing a machine
        that still has a running task.
        Returns False (free) only when the check succeeds and finds no process.
        """
        # START_BLOCK_OCCUPANCY_DISPATCH
        if config.check_pname:
            return await self._occupancy_by_pgrep(session, config.check_pname)
        if config.check_cmd:
            return await self._occupancy_by_cmd(
                session, config.check_cmd, config.check_cmd_code
            )
        logger.trace("NO_CHECK", hostname=session.hostname)
        return False
        # END_BLOCK_OCCUPANCY_DISPATCH

    # START_CONTRACT: OccupancyChecker.start_occupancy_check
    #   PURPOSE: Background task periodically checks occupancy, releases machine when done.
    #   INPUTS: { session: MachineSession, config: Engine - engine metadata for occupancy checks }
    #   SIDE_EFFECTS: Calls session.occupy() then session.install_monitor(interval=config.sleep_interval,
    #     check_factory=..., on_free=session.release). The session owns the asyncio.Task and
    #     the _monitor_task; this method does NOT touch _monitor_task directly.
    #   LINKS: M-SSH-OPS-OCCUPANCY, M-SSH-SESSION
    # END_CONTRACT: OccupancyChecker.start_occupancy_check
    def start_occupancy_check(self, session: MachineSession, config: Engine) -> None:
        """Start background occupancy monitoring.

        Occupies the session ONLY if it is currently FREE (idempotent —
        start_task_on_machine already occupied it on the deploy path).
        Re-registering for an already-monitored session cancels the prior
        monitor (session.install_monitor handles the replacement).
        """
        from yascheduler.domain import MachineState

        if session.machine.state == MachineState.FREE:
            session.occupy()

        async def _check_factory() -> bool:
            # No asyncio.wait_for: on Python <3.12 it swallows the monitor task's
            # cancellation, so SSHMachineSession._close() hangs on task.cancel().
            try:
                return await self.occupancy_check(session, config)
            except Exception:  # noqa: BLE001
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
