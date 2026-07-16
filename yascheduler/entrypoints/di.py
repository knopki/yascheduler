"""Dependency injection composition root — factories per entry point (daemon, CLI)."""
# region MODULE_CONTRACT
# PURPOSE: Assemble all domain, application, and infrastructure collaborators into ready-to-use entry point objects (daemon Orchestrator, CLI dependencies).
# SCOPE: Daemon orchestrator factory (make_daemon), CLI dependency container (CLIDeps + make_cli_deps), and domain event bus setup with webhook registration.
# KEYWORDS: di, composition-root, factories, daemon, cli, dependency-injection
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import aiohttp

from yascheduler.application import (
    AbstractUnitOfWork,
    AllocationTracker,
    MessageBus,
    Orchestrator,
    submit_task,
)
from yascheduler.domain import (
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
    TaskId,
)
from yascheduler.infra import (
    CloudAdapter,
    CloudProvisionerImpl,
    OccupancyChecker,
    OutputDownloader,
    PostgresUnitOfWork,
    SSHMachineRepository,
    TaskDeployer,
    list_private_keys,
    resolve_adapter,
    webhook_handler,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.domain import EngineRepository
    from yascheduler.infra.cloud import ConfigCloud

    from .config import Config


# region CLASS_CLIDeps
# PURPOSE: Lightweight dependency container for CLI submit operations — holds engines and a UoW factory.
@dataclass
class CLIDeps:
    """Lightweight dependency container for CLI submit operations."""

    engines: EngineRepository
    uow_factory: Callable[[], AbstractUnitOfWork]

    # region METHOD_submit
    # PURPOSE: Submit a new task via the submit_task use case, returning the generated TaskId.
    async def submit(
        self,
        label: str,
        metadata: dict[str, object],
        engine_name: str,
    ) -> TaskId:
        """Submit a new task via the submit_task use case."""
        return await submit_task(
            label,
            metadata,
            engine_name,
            self.engines,
            self.uow_factory,
        )

    # endregion METHOD_submit


# endregion CLASS_CLIDeps


# region FUNC__setup_domain_events
# PURPOSE: Create a MessageBus, an aiohttp client session, and register webhook handlers for all domain event types.
def _setup_domain_events() -> tuple[MessageBus, aiohttp.ClientSession]:
    bus = MessageBus()
    http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    for event_type in (
        TaskCreated,
        TaskAllocated,
        TaskCompleted,
        TaskFailed,
        TaskAbandoned,
    ):
        bus.register(event_type, partial(webhook_handler, http=http))
    return bus, http


# endregion FUNC__setup_domain_events


# region FUNC_make_daemon
# PURPOSE: Async factory creating a fully-wired Orchestrator with all daemon dependencies (UoW, SSH, cloud, event bus).
async def make_daemon(
    config: Config,
    *,
    clouds: CloudProvisionerImpl | None = None,
) -> Orchestrator:
    """Async factory creating Orchestrator with all daemon dependencies."""
    bus, http = _setup_domain_events()
    try:

        def uow_factory() -> AbstractUnitOfWork:
            return PostgresUnitOfWork(config.db, bus)

        allocation_tracker = AllocationTracker()
        allocation_lock = asyncio.Lock()

        # Single SSHMachineRepository for the production path (clouds is None):
        # shared between CloudProvisionerImpl (machine_repository only — setup
        # calls session pass-throughs directly) and Orchestrator (repository)
        # so _setup_vm connections are visible to the orchestrator (no
        # double-connect) and reaped at shutdown. The three stateless
        # collaborators (TaskDeployer/OutputDownloader/OccupancyChecker) are
        # constructed once each and passed to the orchestrator only.
        # The pre-built-clouds branch still wires a fresh repository to the
        # orchestrator; caller-supplied clouds keep their own.
        repository = SSHMachineRepository()
        task_deployer = TaskDeployer()
        output_downloader = OutputDownloader()
        occupancy_checker = OccupancyChecker()

        if clouds is None:
            active_clouds: list[ConfigCloud] = []
            _adapters: dict[str, CloudAdapter] = {}
            _configs: dict[str, ConfigCloud] = {}
            for cfg in config.clouds:
                if cfg.max_nodes <= 0:
                    logger.warning(
                        "Cloud %s skipped: max_nodes=%d <= 0",
                        cfg.prefix,
                        cfg.max_nodes,
                    )
                    continue
                adapter = resolve_adapter(cfg)
                if adapter is None:
                    continue
                _adapters[adapter.name] = adapter
                _configs[adapter.name] = cfg
                active_clouds.append(cfg)

            logger.info("Active cloud APIs: %s", ", ".join(_adapters.keys()) or "-")
            clouds = CloudProvisionerImpl(
                adapters=_adapters,
                configs=_configs,
                machine_repository=repository,
                local_config=config.local,
                remote_config=config.remote,
                engines=config.engines,
            )
        else:
            # Caller-supplied clouds: filter by max_nodes > 0 AND adapter
            # actually resolved. configs is keyed by adapter.name == cfg.prefix for
            # every successfully resolved cloud, so its keys are the resolved
            # set. Without this, a pre-built-clouds caller would over-count
            # max_nodes in _clouds_get_capacity for any provider whose
            # optional deps are missing.
            resolved_prefixes = set(clouds.configs.keys())
            active_clouds = [
                cfg
                for cfg in config.clouds
                if cfg.max_nodes > 0 and cfg.prefix in resolved_prefixes
            ]

        # The concrete ConfigCloud* DTOs explicitly inherit the domain
        # CloudConfig Protocol (D1), so list[ConfigCloud] is assignable to
        # Sequence[CloudConfig] (covariance + inheritance) without a cast.
        return Orchestrator(
            local_settings=config.local,
            remote_defaults=config.remote,
            uow_factory=uow_factory,
            clouds=clouds,
            repository=repository,
            task_deployer=task_deployer,
            output_downloader=output_downloader,
            occupancy_checker=occupancy_checker,
            engines=config.engines,
            config_clouds=config.clouds,
            local_tasks_dir=config.local.tasks_dir,
            http_session=http,
            allocation_tracker=allocation_tracker,
            active_clouds=active_clouds,
            allocation_lock=allocation_lock,
            list_private_keys_fn=list_private_keys,
        )
    except Exception:
        await http.close()
        raise


# endregion FUNC_make_daemon


# region FUNC_make_cli_deps
# PURPOSE: Sync factory creating lightweight CLIDeps for CLI commands (no SSH/cloud dependencies).
def make_cli_deps(config: Config) -> CLIDeps:
    """Sync factory creating lightweight CLIDeps for CLI commands (no SSH/cloud)."""
    bus = MessageBus()

    def _uow_factory() -> AbstractUnitOfWork:
        return PostgresUnitOfWork(config.db, bus)

    return CLIDeps(
        engines=config.engines,
        uow_factory=_uow_factory,
    )


# endregion FUNC_make_cli_deps
