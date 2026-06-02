# FILE: yascheduler/clouds/cloud_api_manager.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Multi-cloud orchestrator: provider selection, allocation, deallocation, capacity.
#   SCOPE: CloudAPIManager class managing multiple providers; CLOUD_ADAPTER_GETTERS registry.
#   DEPENDS: M-CLOUD-PROVISIONER, M-DB, M-CONFIG, M-CLOUD-ADAPTERS, M-CLOUD-PROTOCOLS, M-COMPAT
#   LINKS: M-SCHEDULER, M-CLOUD-API, M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CLOUD_ADAPTER_GETTERS - Registry mapping cloud prefix to adapter factory
#   _resolve_adapter - Look up cloud adapter by prefix from the CLOUD_ADAPTER_GETTERS registry
#   _CloudAPICompat - Lightweight compat wrapper for apis property
#   CloudAPIManager - Multi-cloud orchestrator wrapping CloudProvisionerImpl
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Refactored to delegate to CloudProvisionerImpl (Phase 3).
#   PREVIOUS_CHANGE: v1.6.1 - Extracted _resolve_adapter from create to stay under 60-line limit.
# END_CHANGE_SUMMARY

"""Cloud API manager"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from attrs import define, field

from yascheduler.adapters.cloud.adapters import (
    CloudAdapter,
    get_azure_adapter,
    get_hetzner_adapter,
    get_upcloud_adapter,
    get_vastai_adapter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..adapters.cloud.manager import CloudProvisionerImpl
    from ..adapters.cloud.protocols import CloudCapacity
    from ..compat import Self
    from ..config import ConfigCloud, ConfigLocal, ConfigRemote, EngineRepository
    from ..db import DB

CLOUD_ADAPTER_GETTERS = {
    "az": get_azure_adapter,
    "hetzner": get_hetzner_adapter,
    "upcloud": get_upcloud_adapter,
    "vastai": get_vastai_adapter,
}


# START_CONTRACT: _resolve_adapter
#   PURPOSE: Look up cloud adapter by prefix from the CLOUD_ADAPTER_GETTERS registry
#   INPUTS: { cfg: ConfigCloud - cloud provider config with prefix, log: logging.Logger - logger instance }
#   OUTPUTS: { Optional[CloudAdapter] - resolved adapter or None if prefix unknown or deps missing }
#   SIDE_EFFECTS: Logs error on ImportError
#   LINKS: M-CLOUD-MANAGER, M-CLOUD-ADAPTERS
# END_CONTRACT: _resolve_adapter
def _resolve_adapter(cfg: ConfigCloud, log: logging.Logger) -> CloudAdapter | None:
    # START_BLOCK_RESOLVE_ADAPTER
    try:
        getter = CLOUD_ADAPTER_GETTERS[cfg.prefix]
        return getter(cfg.prefix)
    except KeyError:
        return None
    except ImportError:
        log.error(
            "The cloud %s is skipped because the dependencies are not installed",
            cfg.prefix,
        )
        return None
    # END_BLOCK_RESOLVE_ADAPTER


@define(frozen=True)
class _CloudAPICompat:
    """Lightweight compat for apis property — exposes .config.max_nodes / .name."""

    name: str
    config: ConfigCloud


@define(frozen=True)
class CloudAPIManager:
    """Cloud API manager — thin wrapper around CloudProvisionerImpl."""

    impl: CloudProvisionerImpl = field()
    apis_compat: dict[str, _CloudAPICompat] = field()
    log: logging.Logger = field()

    @property
    def apis(self) -> dict[str, _CloudAPICompat]:
        """Return lightweight compat dict for backward-compatible .config.max_nodes access."""
        return self.apis_compat

    # START_CONTRACT: create
    #   PURPOSE: Async factory building CloudProvisionerImpl and compat wrappers.
    #   INPUTS: { db: DB - database connection, local_config: ConfigLocal - local settings, remote_config: ConfigRemote - remote settings, cloud_configs: Sequence[ConfigCloud] - list of cloud provider configs, engines: EngineRepository - engine definitions, log: Optional[logging.Logger] - optional parent logger }
    #   OUTPUTS: { Self - initialized CloudAPIManager instance }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-MANAGER, M-CLOUD-PROVISIONER, M-SSH-GATEWAY
    # END_CONTRACT: create
    @classmethod
    async def create(
        cls,
        db: DB,
        local_config: ConfigLocal,
        remote_config: ConfigRemote,
        cloud_configs: Sequence[ConfigCloud],
        engines: EngineRepository,
        log: logging.Logger | None = None,
    ) -> Self:
        "Create cloud API manager"
        if log:
            log = log.getChild(cls.__name__)
        else:
            log = logging.getLogger(cls.__name__)

        adapters: dict[str, CloudAdapter] = {}
        configs: dict[str, ConfigCloud] = {}
        apis: dict[str, _CloudAPICompat] = {}

        for cfg in cloud_configs:
            if cfg.max_nodes <= 0:
                log.warning(
                    "The cloud %s is skipped because of <1 max nodes", cfg.prefix
                )
                continue

            adapter = _resolve_adapter(cfg, log)
            if adapter is None:
                continue

            adapters[adapter.name] = adapter
            configs[adapter.name] = cfg
            apis[adapter.name] = _CloudAPICompat(name=adapter.name, config=cfg)

        log.info("Active cloud APIs: %s", (", ".join(adapters.keys()) or "-"))

        # Lazy import to avoid circular dependencies
        from yascheduler.adapters.cloud.manager import CloudProvisionerImpl
        from yascheduler.adapters.ssh.gateway import SSHMachineGateway

        impl = CloudProvisionerImpl(
            adapters=adapters,
            configs=configs,
            node_repo=db._node_repo,
            machine_gateway=SSHMachineGateway(log=log),
            local_config=local_config,
            remote_config=remote_config,
            engines=engines,
            log=log,
        )

        return cls(impl=impl, apis_compat=apis, log=log)

    def __bool__(self) -> bool:
        return bool(self.impl)

    async def stop(self) -> None:
        await self.impl.stop()

    def mark_task_done(self, on_task: int) -> None:
        self.impl.mark_task_done(on_task)

    async def get_capacity(self) -> dict[str, CloudCapacity]:
        return await self.impl.get_capacity()

    async def select_best_provider(
        self, want_platforms: Sequence[str] | None = None
    ) -> CloudAdapter | None:
        """Select best cloud API — stub, now delegated via CloudProvisionerImpl."""
        self.log.debug("[CloudManager][select_best_provider] delegating (stub)")
        return None

    async def allocate_node(
        self, want_platforms: Sequence[str] | None = None, throttle: bool = False
    ) -> str | None:
        """Allocate new node — delegate to CloudProvisionerImpl."""
        return await self.impl.allocate_with_tracking(
            on_task=None,
            platforms=list(want_platforms) if want_platforms else [],
            throttle=throttle,
        )

    async def allocate(
        self,
        on_task: int | None = None,
        want_platforms: Sequence[str] | None = None,
        throttle: bool = True,
    ) -> str | None:
        """Allocate cloud node with task tracking — delegate to CloudProvisionerImpl."""
        return await self.impl.allocate_with_tracking(
            on_task=on_task,
            platforms=list(want_platforms) if want_platforms else [],
            throttle=throttle,
        )

    async def deallocate(self, ip_addr: str) -> bool | None:
        """Deallocate cloud node — delegate to CloudProvisionerImpl."""
        try:
            await self.impl.deallocate(ip_addr)
        except Exception as err:
            self.log.error("Can't deallocate node %s: %s", ip_addr, err)
            return False
        return None
