# FILE: yascheduler/di.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Dependency injection composition root — factories per entry point (daemon, CLI, AiiDA).
#   SCOPE: make_daemon, make_cli_deps, make_aiida, CLIDeps dataclass.
#   DEPENDS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-SUBMIT, M-APPLICATION-UOW, M-PERSISTENCE-UOW, M-CONFIG, M-DB, M-SSH-GATEWAY
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-CLIENT, M-UTILS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_daemon - Async factory creating Orchestrator with all daemon dependencies
#   make_cli_deps - Sync factory creating lightweight CLIDeps for CLI commands
#   make_aiida - Stub for future AiiDA integration
#   CLIDeps - Lightweight dependency container for CLI submit and query operations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Add SSHMachineGateway creation and injection into Orchestrator.
#   PREVIOUS_CHANGE: v1.0.0 - Create DI composition root with daemon and CLI factories.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .adapters.persistence.postgres_uow import PostgresUnitOfWork
from .adapters.ssh.gateway import SSHMachineGateway
from .application.orchestrator import Orchestrator
from .application.submit_task import submit_task
from .clouds import CloudAPIManager
from .db import DB
from .remote_machine import RemoteMachineRepository

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import PurePath

    from .application.uow import AbstractUnitOfWork
    from .config import Config, EngineRepository


# START_CONTRACT: CLIDeps
#   PURPOSE: Lightweight dependency container for CLI submit and query operations.
#   INPUTS: { engines, uow_factory, remote_tasks_dir }
#   OUTPUTS: { CLIDeps instance }
#   SIDE_EFFECTS: None
#   LINKS: M-APPLICATION-SUBMIT, M-APPLICATION-UOW
# END_CONTRACT: CLIDeps
@dataclass
class CLIDeps:
    engines: EngineRepository
    uow_factory: Callable[[], AbstractUnitOfWork]
    remote_tasks_dir: PurePath

    # START_CONTRACT: CLIDeps.submit
    #   PURPOSE: Submit a new task via the submit_task use case.
    #   INPUTS: { label, metadata, engine_name }
    #   OUTPUTS: { int - task_id }
    #   SIDE_EFFECTS: Creates task in database.
    #   LINKS: M-APPLICATION-SUBMIT
    # END_CONTRACT: CLIDeps.submit
    async def submit(
        self,
        label: str,
        metadata: dict[str, object],
        engine_name: str,
    ) -> int:
        return await submit_task(
            label,
            metadata,
            engine_name,
            self.engines,
            self.uow_factory,
            self.remote_tasks_dir,
        )

    # START_CONTRACT: CLIDeps.query
    #   PURPOSE: Get a single task by ID via UoW.
    #   INPUTS: { task_id: int }
    #   OUTPUTS: { Task | None }
    #   SIDE_EFFECTS: Opens a DB connection via UoW.
    #   LINKS: M-APPLICATION-UOW
    # END_CONTRACT: CLIDeps.query
    async def query(self, task_id: int) -> object | None:

        async with self.uow_factory() as uow:
            return await uow.tasks.get(task_id)


# START_CONTRACT: make_daemon
#   PURPOSE: Async factory creating Orchestrator with all daemon dependencies.
#   INPUTS: { config: Config, log: Optional[Logger] }
#   OUTPUTS: { Orchestrator - ready to await start() }
#   SIDE_EFFECTS: Creates DB connection, CloudAPIManager, SSHMachineGateway, RemoteMachineRepository.
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-DB, M-CLOUD-MANAGER, M-SSH-GATEWAY
# END_CONTRACT: make_daemon
async def make_daemon(
    config: Config,
    log: logging.Logger | None = None,
    *,
    db: DB | None = None,
    clouds: CloudAPIManager | None = None,
) -> Orchestrator:
    if log is None:
        log = logging.getLogger("Orchestrator")

    if db is None:
        db = await DB.create(config.db)
    if clouds is None:
        clouds = await CloudAPIManager.create(
            db=db,
            local_config=config.local,
            remote_config=config.remote,
            cloud_configs=config.clouds,
            engines=config.engines,
            log=log,
        )
    gateway = SSHMachineGateway(log=log)
    remote_machines = RemoteMachineRepository(log=log)

    return Orchestrator(
        config=config,
        db=db,
        clouds=clouds,
        remote_machines=remote_machines,
        gateway=gateway,
        engines=config.engines,
        log=log,
        config_clouds=config.clouds,
        local_tasks_dir=config.local.tasks_dir,
    )


# START_CONTRACT: make_cli_deps
#   PURPOSE: Sync factory creating lightweight CLIDeps for CLI commands (no SSH/cloud).
#   INPUTS: { config: Config }
#   OUTPUTS: { CLIDeps }
#   SIDE_EFFECTS: None — no connections created until use.
#   LINKS: M-APPLICATION-SUBMIT, M-PERSISTENCE-UOW
# END_CONTRACT: make_cli_deps
def make_cli_deps(config: Config) -> CLIDeps:

    def _uow_factory() -> AbstractUnitOfWork:
        return PostgresUnitOfWork(config.db)

    return CLIDeps(
        engines=config.engines,
        uow_factory=_uow_factory,
        remote_tasks_dir=config.remote.tasks_dir,
    )


# START_CONTRACT: make_aiida
#   PURPOSE: Stub for future AiiDA scheduler plugin integration.
#   INPUTS: { config: Config }
#   OUTPUTS: { None - raises NotImplementedError }
#   SIDE_EFFECTS: None
#   LINKS: M-AIIDA
# END_CONTRACT: make_aiida
def make_aiida(config: Config) -> None:
    raise NotImplementedError("make_aiida will be implemented in a future phase")
