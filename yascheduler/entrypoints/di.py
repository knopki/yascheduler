# FILE: yascheduler/entrypoints/di.py
# VERSION: 5.12.1
# START_MODULE_CONTRACT
#   PURPOSE: Dependency injection composition root — factories per entry point (daemon, CLI).
#   SCOPE: Factories per entry point (daemon, CLI).
#   DEPENDS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-SUBMIT, M-APPLICATION-UOW, M-PERSISTENCE-UOW, M-ENTRYPOINTS-CONFIG, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS, M-CLOUD-PROVISIONER, M-APPLICATION-MESSAGE-BUS, M-NOTIFIER-WEBHOOK, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE, M-DOMAIN-PORTS, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-ENTRYPOINTS-CLIENT, M-CLI-COMMANDS, M-APPLICATION-MESSAGE-BUS, M-APPLICATION-ALLOCATION-TRACKER, M-SSH-KEYS, M-DOMAIN-ENGINE, M-DOMAIN-PORTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_daemon - Async factory creating Orchestrator with all daemon dependencies including MessageBus
#   make_cli_deps - Sync factory creating lightweight CLIDeps for CLI commands
#   _setup_domain_events - Create MessageBus, HTTP session and register webhook handlers
#   CLIDeps - Lightweight dependency container for CLI submit operations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v5.12.1 - CLIDeps.submit return type int -> TaskId (forwards submit_task which now returns TaskId); import TaskId. The public Yascheduler.queue_submit_task_async facade extracts .value to preserve the public -> int contract.
#   PREVIOUS_CHANGE: v5.12.0 - make_daemon now constructs SSHMachineRepository + SSHMachineOperations (two ports) instead of a single SSHMachineRepository / SSHMachineOperations. Both are shared between CloudProvisionerImpl (machine_repository + machine_operations) and Orchestrator (repository + operations) on the clouds is None branch.
# END_CHANGE_SUMMARY

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
    PostgresUnitOfWork,
    SSHMachineOperations,
    SSHMachineRepository,
    list_private_keys,
    resolve_adapter,
    webhook_handler,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import PurePath

    from yascheduler.domain import EngineRepository
    from yascheduler.infra.cloud import ConfigCloud

    from .config import Config


# START_CONTRACT: CLIDeps
#   PURPOSE: Lightweight dependency container for CLI submit operations.
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
    #   OUTPUTS: { TaskId - the generated task_id (the public Yascheduler.queue_submit_task facade extracts .value to keep the public -> int contract; yasubmit prints str(TaskId) → bare integer) }
    #   SIDE_EFFECTS: Creates task in database.
    #   LINKS: M-APPLICATION-SUBMIT
    # END_CONTRACT: CLIDeps.submit
    async def submit(
        self,
        label: str,
        metadata: dict[str, object],
        engine_name: str,
    ) -> TaskId:
        return await submit_task(
            label,
            metadata,
            engine_name,
            self.engines,
            self.uow_factory,
            self.remote_tasks_dir,
        )


# START_CONTRACT: _setup_domain_events
#   PURPOSE: Create MessageBus, HTTP client session, and register webhook handlers for all event types.
#   INPUTS: { None }
#   OUTPUTS: { tuple[MessageBus, aiohttp.ClientSession] - (bus, http_session) }
#   SIDE_EFFECTS: Creates HTTP session; registers webhook_handler for each event type.
#   LINKS: M-APPLICATION-MESSAGE-BUS, M-NOTIFIER-WEBHOOK, M-DOMAIN-EVENTS
# END_CONTRACT: _setup_domain_events
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


# START_CONTRACT: make_daemon
#   PURPOSE: Async factory creating Orchestrator with all daemon dependencies.
#   INPUTS: { config: Config, log: Optional[Logger], clouds: Optional[CloudProvisionerImpl] }
#   OUTPUTS: { Orchestrator - ready to await start() }
#   SIDE_EFFECTS: Creates UoW factory, SSH connections, and cloud provisioner.
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-CLOUD-PROVISIONER, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS, M-APPLICATION-UOW, M-APPLICATION-ALLOCATION-TRACKER
# END_CONTRACT: make_daemon
async def make_daemon(
    config: Config,
    log: logging.Logger | None = None,
    *,
    clouds: CloudProvisionerImpl | None = None,
) -> Orchestrator:
    if log is None:
        log = logging.getLogger("Orchestrator")

    bus, http = _setup_domain_events()
    try:

        def uow_factory() -> AbstractUnitOfWork:
            return PostgresUnitOfWork(config.db, bus)

        allocation_tracker = AllocationTracker()
        allocation_lock = asyncio.Lock()

        # Single SSHMachineRepository + SSHMachineOperations for the production
        # path (clouds is None): shared between CloudProvisionerImpl
        # (machine_repository + machine_operations) and Orchestrator
        # (repository + operations) so _setup_vm connections are visible to the
        # orchestrator (no double-connect) and reaped at shutdown. The
        # pre-built-clouds branch still wires a fresh pair to the orchestrator;
        # caller-supplied clouds keep their own.
        repository = SSHMachineRepository(log=log)
        operations = SSHMachineOperations(repository=repository, log=log)

        if clouds is None:
            active_clouds: list[ConfigCloud] = []
            _adapters: dict[str, CloudAdapter] = {}
            _configs: dict[str, ConfigCloud] = {}
            for cfg in config.clouds:
                if cfg.max_nodes <= 0:
                    log.warning(
                        "Cloud %s skipped: max_nodes=%d <= 0",
                        cfg.prefix,
                        cfg.max_nodes,
                    )
                    continue
                adapter = resolve_adapter(cfg, log)
                if adapter is None:
                    continue
                _adapters[adapter.name] = adapter
                _configs[adapter.name] = cfg
                active_clouds.append(cfg)

            log.info("Active cloud APIs: %s", ", ".join(_adapters.keys()) or "-")
            clouds = CloudProvisionerImpl(
                adapters=_adapters,
                configs=_configs,
                machine_repository=repository,
                machine_operations=operations,
                local_config=config.local,
                remote_config=config.remote,
                engines=config.engines,
                log=log,
            )
        else:
            # Caller-supplied clouds: filter by max_nodes > 0 AND adapter
            # actually resolved (matches the primary path's contract from
            # design D7). configs is keyed by adapter.name == cfg.prefix for
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
            operations=operations,
            engines=config.engines,
            log=log,
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


# START_CONTRACT: make_cli_deps
#   PURPOSE: Sync factory creating lightweight CLIDeps for CLI commands (no SSH/cloud).
#   INPUTS: { config: Config }
#   OUTPUTS: { CLIDeps }
#   SIDE_EFFECTS: None — no connections created until use.
#   LINKS: M-APPLICATION-SUBMIT, M-PERSISTENCE-UOW
# END_CONTRACT: make_cli_deps
def make_cli_deps(config: Config) -> CLIDeps:

    bus = MessageBus()

    def _uow_factory() -> AbstractUnitOfWork:
        return PostgresUnitOfWork(config.db, bus)

    return CLIDeps(
        engines=config.engines,
        uow_factory=_uow_factory,
        remote_tasks_dir=config.remote.tasks_dir,
    )
