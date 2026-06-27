# FILE: yascheduler/infra/ssh/operations/base.py
# VERSION: 2.1.0
# START_MODULE_CONTRACT
#   PURPOSE: SSHMachineOperations — facade over MachineSession. Use-case methods forward to stateless collaborators (TaskDeployer/OutputDownloader/OccupancyChecker); facade pass-throughs delegate to session.*. No base primitives declared on the facade (moved to SSHMachineSession).
#   SCOPE: SSHMachineOperations class only. Narrow local Protocols (CommandExecutor/SftpProvider/StateAccessors) deleted — collaborators take sessions directly. my_backoff_exc canonical copy lives in ../session.py (consumers import from there directly).
#   DEPENDS: M-SSH-SESSION, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
#   LINKS: M-SSH-OPERATIONS-BASE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SSHMachineOperations - Facade over MachineSession; composes stateless deploy/download/occupancy collaborators; facade pass-throughs delegate to session.*
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.0 - Drop the back-compat re-import of my_backoff_exc (no consumer imports it from operations.base; canonical copy lives in ../session.py and is imported directly by its users).
#   PREVIOUS_CHANGE: v2.0.0 - Session-based-machine-handle section 4. SSHMachineOperations becomes a facade: base primitives (run/run_full/run_bg/upload/get_sftp/pgrep/list_processes/get_cpu_cores/setup_node) deleted (moved to SSHMachineSession). Narrow local Protocols (CommandExecutor/SftpProvider/StateAccessors) deleted — collaborators take sessions directly. __init__ now composes TaskDeployer(log)/OutputDownloader(log)/OccupancyChecker(log) (stateless; no repository/operations refs). Facade pass-throughs (run/run_full/run_bg/get_cpu_cores/setup_node) delegate to session.*. Use-case methods (start_task_on_machine/download_outputs/occupancy_check/start_occupancy_check) forward to collaborators with session.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path, PurePath

    from yascheduler.domain import (
        Engine,
        EngineRepository,
        MachineSession,
        ProcessResult,
        Task,
    )


# START_CONTRACT: SSHMachineOperations
#   PURPOSE: Facade over MachineSession. Composes three stateless collaborators (deploy/download/occupancy) exposed as attributes. Use-case methods forward to collaborators with the session; facade pass-throughs delegate to session.*. Constructor signature preserved (repository, log) for orchestrator composition-root stability.
#   INPUTS: { repository: SSHMachineRepository, log: logging.Logger | None }
#   OUTPUTS: { None - instance methods return operation results }
#   SIDE_EFFECTS: None directly; delegates all side effects to collaborators and session.
#   LINKS: M-SSH-OPERATIONS-BASE, M-SSH-SESSION, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
# END_CONTRACT: SSHMachineOperations
class SSHMachineOperations:
    """Facade over MachineSession.

    Composes three stateless collaborators (deploy/download/occupancy)
    exposed as the `deploy`, `download`, `occupancy` attributes. Use-case
    methods forward to the collaborators, passing the session through.
    Facade pass-throughs delegate to `session.*`. The repository reference
    is retained for the constructor signature (composition-root stability)
    but collaborators no longer need it — they operate via the session
    parameter.
    """

    def __init__(
        self,
        repository: Any,  # noqa: ANN401 - kept for signature compatibility; collaborators no longer use it
        log: logging.Logger | None = None,
    ) -> None:
        self._repo = repository
        self._log = log or logging.getLogger("SSHMachineOperations")
        from .deployment import TaskDeployer
        from .download import OutputDownloader
        from .occupancy import OccupancyChecker

        self.deploy = TaskDeployer(self._log)
        self.download = OutputDownloader(self._log)
        self.occupancy = OccupancyChecker(self._log)

    # ---- Facade pass-throughs (delegate to session.*) ----

    async def run(self, session: MachineSession, cmd: str) -> ProcessResult:
        return await session.run(cmd)

    async def run_full(self, session: MachineSession, cmd: str) -> Any:  # noqa: ANN401 - infra SSHCompletedProcess returned through facade
        return await session.run_full(cmd)

    async def run_bg(
        self, session: MachineSession, cmd: str, *, cwd: str | None = None
    ) -> None:
        await session.run_bg(cmd, cwd=cwd)

    async def get_cpu_cores(self, session: MachineSession) -> int:
        return await session.get_cpu_cores()

    async def setup_node(
        self, session: MachineSession, engines: EngineRepository
    ) -> None:
        await session.setup_node(engines)

    # ---- Use-case methods (forward to collaborators with session) ----

    async def start_task_on_machine(
        self,
        session: MachineSession,
        engine: Engine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        return await self.deploy.start_task_on_machine(
            session, engine, task, ncpus, engines_dir
        )

    async def download_outputs(
        self,
        session: MachineSession,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: int | None = None,
    ) -> tuple[
        list[tuple[str, Any]],
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]:
        return await self.download.download_outputs(
            session, remote_dir, local_dir, files, task_id
        )

    async def occupancy_check(self, session: MachineSession, config: Engine) -> bool:
        return await self.occupancy.occupancy_check(session, config)

    def start_occupancy_check(self, session: MachineSession, config: Engine) -> None:
        self.occupancy.start_occupancy_check(session, config)
