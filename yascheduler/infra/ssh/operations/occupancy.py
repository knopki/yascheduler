# FILE: yascheduler/infra/ssh/operations/occupancy.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: OccupancyChecker — pgrep/cmd-based occupancy check logic + monitor installer composing the repository's generic monitor mechanism.
#   SCOPE: OccupancyChecker class (_occupancy_by_pgrep, _occupancy_by_cmd, occupancy_check, start_occupancy_check).
#   DEPENDS: M-SSH-OPERATIONS-BASE, M-SSH-REPOSITORY, M-DOMAIN-ENGINE, M-SSH-EXCEPTIONS
#   LINKS: M-SSH-OPS-OCCUPANCY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   OccupancyChecker - Occupancy check via pgrep or check_cmd; start_occupancy_check composes repository.install_monitor
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial module created (decompose-ssh-gateway). Extracted from the dissolved SSHMachineGateway god-class; occupancy_check + _occupancy_by_pgrep + _occupancy_by_cmd moved verbatim. start_occupancy_check now calls repository.occupy(ip) + repository.install_monitor(...) instead of touching _bg_tasks directly; the check_factory wraps occupancy_check with asyncio.wait_for(timeout=config.sleep_interval) to preserve the original per-check timeout bound.
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from ..exceptions import SSHRetryExc

if TYPE_CHECKING:
    import logging

    from yascheduler.domain import Engine

    from ..repository import SSHMachineRepository
    from .base import SSHMachineOperations


# START_CONTRACT: OccupancyChecker
#   PURPOSE: pgrep/cmd-based occupancy check logic + monitor installer composing the repository's generic monitor mechanism.
#   LINKS: M-SSH-OPS-OCCUPANCY, M-SSH-OPERATIONS, M-SSH-REPOSITORY
# END_CONTRACT: OccupancyChecker
class OccupancyChecker:
    """pgrep/cmd-based occupancy check + monitor installer.

    The check logic (dispatch on engine.check_pname / engine.check_cmd)
    lives here; the monitor MECHANISM (asyncio.Task, sleep/cancel, keyed
    by IP) lives on the repository. start_occupancy_check composes them:
    it calls repository.occupy(ip), then repository.install_monitor(ip,
    interval=..., check_factory=..., on_free=repository.release(ip)).
    """

    def __init__(
        self,
        operations: SSHMachineOperations,
        repository: SSHMachineRepository,
        log: logging.Logger,
    ) -> None:
        self._operations = operations
        self._repository = repository
        self._log = log

    # START_CONTRACT: OccupancyChecker._occupancy_by_pgrep
    #   PURPOSE: Occupancy check via pgrep on check_pname. Returns True (busy)
    #     when at least one process matches OR when SSH fails (safe default).
    #     Returns False (free) only when pgrep succeeds and yields no process.
    #   INPUTS: { ip: str, pattern: str - process name pattern to match }
    #   OUTPUTS: { bool - True if busy or SSH failed, False if confirmed free }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-OPS-OCCUPANCY
    # END_CONTRACT: OccupancyChecker._occupancy_by_pgrep
    async def _occupancy_by_pgrep(self, ip: str, pattern: str) -> bool:
        # START_BLOCK_OCCUPANCY_PGREP
        try:
            async for proc in self._operations.pgrep(ip, pattern):
                self._log.debug(
                    "[OccupancyChecker][occupancy_check][PGREP] ip=%s pid=%s name=%s cmd=%s",
                    ip,
                    proc.pid,
                    proc.name,
                    proc.command,
                )
                return True
            self._log.debug(
                "[OccupancyChecker][occupancy_check][PGREP_FREE] ip=%s pattern=%s",
                ip,
                pattern,
            )
            return False
        except SSHRetryExc as exc:
            self._log.warning("Machine %s pgrep failed, assuming busy: %s", ip, exc)
            return True
        # END_BLOCK_OCCUPANCY_PGREP

    # START_CONTRACT: OccupancyChecker._occupancy_by_cmd
    #   PURPOSE: Occupancy check via check_cmd exit code. Returns True (busy)
    #     when exit code matches expected_code OR when SSH fails (safe default).
    #     Returns False only when the check succeeds with a non-matching exit code.
    #   INPUTS: { ip: str, cmd: str - check command to run, expected_code: int - busy exit code }
    #   OUTPUTS: { bool - True if busy or SSH failed, False if confirmed free }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-OPS-OCCUPANCY
    # END_CONTRACT: OccupancyChecker._occupancy_by_cmd
    async def _occupancy_by_cmd(self, ip: str, cmd: str, expected_code: int) -> bool:
        # START_BLOCK_OCCUPANCY_CMD
        try:
            machine = self._repository.get_machine_state(ip)
            if machine is None:
                return True
            proc = await self._operations.run_full(machine, cmd)
            self._log.debug(
                "[OccupancyChecker][occupancy_check][CHECK_CMD] ip=%s cmd=%s exit=%d expected=%d",
                ip,
                cmd,
                proc.returncode,
                expected_code,
            )
            return proc.returncode == expected_code
        except SSHRetryExc as exc:
            self._log.warning("Machine %s check_cmd failed, assuming busy: %s", ip, exc)
            return True
        # END_BLOCK_OCCUPANCY_CMD

    # START_CONTRACT: OccupancyChecker.occupancy_check
    #   PURPOSE: Check if engine process is still running via pgrep or check_cmd.
    #     Returns True (busy) when process found OR when SSH fails (safe default).
    #     Returns False (free) only when check succeeds and finds no process.
    #   INPUTS: { ip: str, config: Engine - engine metadata for checks }
    #   LINKS: M-SSH-OPS-OCCUPANCY
    # END_CONTRACT: OccupancyChecker.occupancy_check
    async def occupancy_check(self, ip: str, config: Engine) -> bool:
        """Check if engine process is still running.

        Returns True (busy) when the engine process is found OR when the SSH
        check fails — the machine is presumed busy to avoid releasing a machine
        that still has a running task.
        Returns False (free) only when the check succeeds and finds no process.
        """
        # START_BLOCK_OCCUPANCY_DISPATCH
        if config.check_pname:
            return await self._occupancy_by_pgrep(ip, config.check_pname)
        if config.check_cmd:
            return await self._occupancy_by_cmd(
                ip, config.check_cmd, config.check_cmd_code
            )
        self._log.debug("[OccupancyChecker][occupancy_check][NO_CHECK] ip=%s", ip)
        return False
        # END_BLOCK_OCCUPANCY_DISPATCH

    # START_CONTRACT: OccupancyChecker.start_occupancy_check
    #   PURPOSE: Background task periodically checks occupancy, releases machine when done.
    #   INPUTS: { ip: str, config: Engine - engine metadata for occupancy checks }
    #   SIDE_EFFECTS: Calls repository.occupy(ip) then repository.install_monitor(ip, interval=config.sleep_interval,
    #     check_factory=..., on_free=partial(repository.release, ip)). The repository owns the asyncio.Task
    #     and the _monitors dict; this method does NOT touch _monitors directly.
    #   LINKS: M-SSH-OPS-OCCUPANCY, M-SSH-REPOSITORY
    # END_CONTRACT: OccupancyChecker.start_occupancy_check
    def start_occupancy_check(self, ip: str, config: Engine) -> None:
        """Start background occupancy monitoring.

        Occupies the ConnectedMachine at the repository level ONLY if it is
        currently FREE (idempotent — start_task_on_machine already occupied
        it on the deploy path). Re-registering for an already-monitored IP
        cancels the prior monitor (the repository's install_monitor handles
        the replacement).
        """
        from yascheduler.domain import MachineState

        state = self._repository._get_machine_state(ip)
        if state is not None and state.machine.state == MachineState.FREE:
            self._repository.occupy(ip)

        async def _check_factory() -> bool:
            # Wrap each check with the engine's sleep_interval as a per-check
            # timeout bound (preserves the original start_occupancy_check behavior
            # where asyncio.wait_for bounded each check to config.sleep_interval).
            try:
                return await asyncio.wait_for(
                    self.occupancy_check(ip, config),
                    timeout=config.sleep_interval,
                )
            except asyncio.TimeoutError:
                self._log.warning(
                    "Engine %s busy check timed out on %s",
                    config.name,
                    ip,
                )
                return True
            except Exception:  # noqa: BLE001
                self._log.exception(
                    "Occupancy check failed for %s on %s",
                    config.name,
                    ip,
                )
                return True

        self._repository.install_monitor(
            ip,
            interval=config.sleep_interval,
            check_factory=_check_factory,
            on_free=partial(self._repository.release, ip),
        )
