# FILE: yascheduler/infra/ssh/operations/occupancy.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: OccupancyChecker — pgrep/cmd-based occupancy check logic + monitor installer composing the session's generic monitor mechanism. Stateless: takes (log) at construction, (session, ...) per call.
#   SCOPE: OccupancyChecker class (_occupancy_by_pgrep, _occupancy_by_cmd, occupancy_check, start_occupancy_check).
#   DEPENDS: M-SSH-SESSION, M-DOMAIN-ENGINE, M-SSH-EXCEPTIONS
#   LINKS: M-SSH-OPS-OCCUPANCY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   OccupancyChecker - Occupancy check via pgrep or check_cmd; stateless (log)-only constructor; start_occupancy_check composes session.install_monitor
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - fix-occupancy-monitor-cancel-hang: drop asyncio.wait_for wrapper from _check_factory. On Python <3.12 wait_for swallowed the outer monitor Task's cancellation, so SSHMachineSession._close()'s task.cancel()+await task hung forever (manifested as test_ssh_gateway_bg_tasks.py infinite hang on <=3.11). occupancy_check's underlying SSH primitives already self-bound via my_backoff_exc; failed checks still fall back to busy. Removed now-unused asyncio import.
#   PREVIOUS_CHANGE: v1.2.0 - session-based-machine-handle sections 5.6-5.9: All four method bodies rewritten to operate via MachineSession parameter. _occupancy_by_pgrep uses session.pgrep(), _occupancy_by_cmd uses session.run_full(), occupancy_check/start_occupancy_check dispatch on session. install_monitor/occupy/release called on session instead of repository.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

from ..exceptions import SSHRetryExc

if TYPE_CHECKING:
    import logging

    from yascheduler.domain import Engine, MachineSession


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

    def __init__(
        self,
        log: logging.Logger,
    ) -> None:
        self._log = log

    # START_CONTRACT: OccupancyChecker._occupancy_by_pgrep
    #   PURPOSE: Occupancy check via pgrep on check_pname. Returns True (busy)
    #     when at least one process matches OR when SSH fails (safe default).
    #     Returns False (free) only when pgrep succeeds and yields no process.
    #   INPUTS: { session: MachineSession, pattern: str - process name pattern to match }
    #   OUTPUTS: { bool - True if busy or SSH failed, False if confirmed free }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-OPS-OCCUPANCY
    # END_CONTRACT: OccupancyChecker._occupancy_by_pgrep
    async def _occupancy_by_pgrep(self, session: MachineSession, pattern: str) -> bool:
        # START_BLOCK_OCCUPANCY_PGREP
        try:
            async for proc in session.pgrep(pattern):
                self._log.debug(
                    "[OccupancyChecker][occupancy_check][PGREP] ip=%s pid=%s name=%s cmd=%s",
                    session.ip,
                    proc.pid,
                    proc.name,
                    proc.command,
                )
                return True
            self._log.debug(
                "[OccupancyChecker][occupancy_check][PGREP_FREE] ip=%s pattern=%s",
                session.ip,
                pattern,
            )
            return False
        except SSHRetryExc as exc:
            self._log.warning(
                "Machine %s pgrep failed, assuming busy: %s", session.ip, exc
            )
            return True
        # END_BLOCK_OCCUPANCY_PGREP

    # START_CONTRACT: OccupancyChecker._occupancy_by_cmd
    #   PURPOSE: Occupancy check via check_cmd exit code. Returns True (busy)
    #     when exit code matches expected_code OR when SSH fails (safe default).
    #     Returns False only when the check succeeds with a non-matching exit code.
    #   INPUTS: { session: MachineSession, cmd: str - check command to run, expected_code: int - busy exit code }
    #   OUTPUTS: { bool - True if busy or SSH failed, False if confirmed free }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-OPS-OCCUPANCY
    # END_CONTRACT: OccupancyChecker._occupancy_by_cmd
    async def _occupancy_by_cmd(
        self, session: MachineSession, cmd: str, expected_code: int
    ) -> bool:
        # START_BLOCK_OCCUPANCY_CMD
        try:
            proc = await session.run_full(cmd)
            self._log.debug(
                "[OccupancyChecker][occupancy_check][CHECK_CMD] ip=%s cmd=%s exit=%d expected=%d",
                session.ip,
                cmd,
                proc.returncode,
                expected_code,
            )
            return proc.returncode == expected_code
        except SSHRetryExc as exc:
            self._log.warning(
                "Machine %s check_cmd failed, assuming busy: %s", session.ip, exc
            )
            return True
        # END_BLOCK_OCCUPANCY_CMD

    # START_CONTRACT: OccupancyChecker.occupancy_check
    #   PURPOSE: Check if engine process is still running via pgrep or check_cmd.
    #     Returns True (busy) when process found OR when SSH fails (safe default).
    #     Returns False (free) only when check succeeds and finds no process.
    #   INPUTS: { session: MachineSession, config: Engine - engine metadata for checks }
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
        self._log.debug(
            "[OccupancyChecker][occupancy_check][NO_CHECK] ip=%s", session.ip
        )
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
                self._log.exception(
                    "Occupancy check failed for %s on %s",
                    config.name,
                    session.ip,
                )
                return True

        session.install_monitor(
            interval=config.sleep_interval,
            check_factory=_check_factory,
            on_free=session.release,
        )
