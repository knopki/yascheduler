# FILE: yascheduler/clouds/cloud_api_manager.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Multi-cloud orchestrator: provider selection, allocation, deallocation, capacity.
#   SCOPE: CloudAPIManager class managing multiple providers; CLOUD_ADAPTER_GETTERS registry.
#   DEPENDS: M-CLOUD-API, M-DB, M-CONFIG, M-CLOUD-ADAPTERS, M-CLOUD-PROTOCOLS, M-COMPAT
#   LINKS: M-SCHEDULER, M-CLOUD-API, M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CLOUD_ADAPTER_GETTERS - Registry mapping cloud prefix to adapter factory
#   _resolve_adapter - Look up cloud adapter by prefix from the CLOUD_ADAPTER_GETTERS registry
#   CloudAPIManager - Multi-cloud orchestrator; create, stop, allocate, deallocate, capacity
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.1 - Extracted _resolve_adapter from create to stay under 60-line limit.
#   PREVIOUS_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Cloud API manager"""

import asyncio
import logging
from asyncio.locks import Lock
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from attrs import define, field

from ..compat import Self
from ..config import ConfigCloud, ConfigLocal, ConfigRemote, EngineRepository
from ..db import DB
from .adapters import get_azure_adapter, get_hetzner_adapter, get_upcloud_adapter
from .cloud_api import CloudAPI
from .protocols import CloudCapacity

CLOUD_ADAPTER_GETTERS = {
    "az": get_azure_adapter,
    "hetzner": get_hetzner_adapter,
    "upcloud": get_upcloud_adapter,
}


# START_CONTRACT: _resolve_adapter
#   PURPOSE: Look up cloud adapter by prefix from the CLOUD_ADAPTER_GETTERS registry
#   INPUTS: { cfg: ConfigCloud - cloud provider config with prefix, log: logging.Logger - logger instance }
#   OUTPUTS: { Optional[CloudAdapter] - resolved adapter or None if prefix unknown or deps missing }
#   SIDE_EFFECTS: Logs error on ImportError
#   LINKS: M-CLOUD-MANAGER, M-CLOUD-ADAPTERS
# END_CONTRACT: _resolve_adapter
def _resolve_adapter(cfg, log):
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
class CloudAPIManager:
    """Cloud API manager"""

    apis: dict[str, CloudAPI[ConfigCloud]] = field()
    db: DB = field()
    log: logging.Logger = field()
    on_tasks: set[int] = field(init=False, factory=set)
    keys_dir: Path = field(factory=Path)
    allocation_lock: Lock = field(factory=Lock, init=False)

    # START_CONTRACT: create
    #   PURPOSE: Async factory that instantiates all configured cloud providers
    #   INPUTS: { db: DB - database connection, local_config: ConfigLocal - local settings, remote_config: ConfigRemote - remote settings, cloud_configs: Sequence[ConfigCloud] - list of cloud provider configs, engines: EngineRepository - engine definitions, log: Optional[logging.Logger] - optional parent logger }
    #   OUTPUTS: { Self - initialized CloudAPIManager instance }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-MANAGER, M-CLOUD-API
    # END_CONTRACT: create
    @classmethod
    async def create(
        cls,
        db: DB,
        local_config: ConfigLocal,
        remote_config: ConfigRemote,
        cloud_configs: Sequence[ConfigCloud],
        engines: EngineRepository,
        log: Optional[logging.Logger] = None,
    ) -> Self:
        "Create cloud API manager"
        if log:
            log = log.getChild(cls.__name__)
        else:
            log = logging.getLogger(cls.__name__)

        apis: dict[str, CloudAPI[ConfigCloud]] = {}
        ssh_key_lock = asyncio.Lock()

        for cfg in cloud_configs:
            if cfg.max_nodes <= 0:
                log.warning(
                    "The cloud %s is skipped because of <1 max nodes", cfg.prefix
                )
                continue

            adapter = _resolve_adapter(cfg, log)
            if adapter is None:
                continue

            apis[adapter.name] = CloudAPI(
                adapter=adapter,
                config=cfg,
                local_config=local_config,
                remote_config=remote_config,
                engines=engines,
                ssh_key_lock=ssh_key_lock,
                log=log,
            )

        log.info("Active cloud APIs: %s", (", ".join(apis.keys()) or "-"))

        return cls(
            apis=apis,
            db=db,
            log=log,
            keys_dir=local_config.keys_dir,
        )

    def __bool__(self) -> bool:
        return bool(len(self.apis))

    async def stop(self) -> None:
        self.log.info("Stopping clouds...")

    def mark_task_done(self, on_task: int) -> None:
        self.on_tasks.discard(on_task)

    # START_CONTRACT: get_capacity
    #   PURPOSE: Report current capacity across all providers
    #   INPUTS: { None }
    #   OUTPUTS: { dict[str, CloudCapacity] - mapping of provider name to capacity info }
    #   SIDE_EFFECTS: Reads from DB
    #   LINKS: M-CLOUD-MANAGER, M-DB
    # END_CONTRACT: get_capacity
    async def get_capacity(self) -> dict[str, CloudCapacity]:
        data: dict[str, CloudCapacity] = {}
        for name, count in (await self.db.count_nodes_clouds()).items():
            api = self.apis.get("name")
            data[name] = CloudCapacity(
                name=name,
                current=count,
                max=api.config.max_nodes if api else 0,
            )

        for api in self.apis.values():
            if api.name not in data:
                data[api.name] = CloudCapacity(
                    name=api.name, current=0, max=api.config.max_nodes
                )
        return data

    # START_CONTRACT: select_best_provider
    #   PURPOSE: Pick provider with highest priority and available capacity
    #   INPUTS: { want_platforms: Optional[Sequence[str]] - optional platform filter }
    #   OUTPUTS: { Optional[CloudAPI[ConfigCloud]] - best matching provider or None }
    #   SIDE_EFFECTS: Reads from DB via get_capacity
    #   LINKS: M-CLOUD-MANAGER
    # END_CONTRACT: select_best_provider
    async def select_best_provider(
        self, want_platforms: Optional[Sequence[str]] = None
    ) -> Optional[CloudAPI[ConfigCloud]]:
        """Select best cloud API"""
        self.log.debug(
            "[CloudManager][select_best_provider] providers=%s",
            ", ".join(self.apis.keys()),
        )
        used_providers = []
        suitable_providers = list(self.apis.keys())

        # START_BLOCK_FILTER_PROVIDERS
        cap = await self.get_capacity()

        for name, capacity in cap.items():
            used_providers.append((name, capacity.current))
            api = self.apis.get(name)
            if not api:
                continue
            # remove maxed out providers
            if capacity.current >= api.config.max_nodes:
                suitable_providers.remove(api.name)
                continue
            # remove not supported platforms
            if want_platforms:
                if not any(map(api.is_platform_supported, want_platforms)):
                    suitable_providers.remove(api.name)

        # END_BLOCK_FILTER_PROVIDERS
        self.log.debug("[CloudManager][select_best_provider] used=%s", used_providers)
        if not suitable_providers:
            self.log.debug("[CloudManager][select_best_provider] no suitable providers")
            return

        # START_BLOCK_SORT_SELECT
        ok_apis = filter(lambda x: x.name in suitable_providers, self.apis.values())
        ok_apis_sorted = sorted(ok_apis, key=lambda x: x.config.priority, reverse=True)
        api = ok_apis_sorted[0]
        self.log.debug(
            "[CloudManager][select_best_provider][CHOSEN] provider=%s", api.name
        )
        return api
        # END_BLOCK_SORT_SELECT

    # START_CONTRACT: allocate_node
    #   PURPOSE: Select provider, create a cloud node, wait for ready
    #   INPUTS: { want_platforms: Optional[Sequence[str]] - optional platform filter, throttle: bool - whether to skip overloaded providers }
    #   OUTPUTS: { Optional[str] - allocated node IP address or None }
    #   SIDE_EFFECTS: Adds node to DB
    #   LINKS: M-CLOUD-MANAGER, M-DB
    # END_CONTRACT: allocate_node
    async def allocate_node(
        self, want_platforms: Optional[Sequence[str]] = None, throttle: bool = False
    ) -> Optional[str]:
        """Allocate new node"""
        async with self.allocation_lock:
            api = await self.select_best_provider(want_platforms)
            if not api:
                return
            if throttle and api.get_op_semaphore().locked():
                self.log.debug(
                    "[CloudManager][allocate_node][OVERLOADED] provider=%s", api.name
                )
                await asyncio.sleep(1)
                return

            tmp_ip = await self.db.add_tmp_node(api.name, api.config.username)
            await self.db.commit()
        # START_BLOCK_CREATE_NODE
        try:
            ip_addr = await api.create_node()
        finally:
            await self.db.remove_node(tmp_ip)
            await self.db.commit()
        # END_BLOCK_CREATE_NODE

        # START_BLOCK_REGISTER_NODE
        _ = await self.db.add_node(
            ip_addr=ip_addr,
            username=api.config.username,
            port=None,
            cloud=api.name,
            enabled=True,
        )
        await self.db.commit()
        # END_BLOCK_REGISTER_NODE
        return ip_addr

    # START_CONTRACT: allocate
    #   PURPOSE: Externally-safe allocate wrapper with error handling and task tracking
    #   INPUTS: { on_task: Optional[int] - optional task id to mark, want_platforms: Optional[Sequence[str]] - optional platform filter, throttle: bool - whether to skip overloaded providers }
    #   OUTPUTS: { Optional[str] - allocated node IP address or None on error }
    #   SIDE_EFFECTS: Tracks on_task in on_tasks set, logs allocation errors
    #   LINKS: M-CLOUD-MANAGER, M-DB
    # END_CONTRACT: allocate
    async def allocate(
        self,
        on_task: Optional[int] = None,
        want_platforms: Optional[Sequence[str]] = None,
        throttle: bool = True,
    ) -> Optional[str]:
        if on_task in self.on_tasks:
            return
        if on_task:
            self.on_tasks.add(on_task)
        try:
            return await self.allocate_node(want_platforms, throttle)
        except Exception as err:
            self.log.error(f"Can't allocate node: {err}")
            if on_task:
                self.mark_task_done(on_task)
        return

    # START_CONTRACT: deallocate
    #   PURPOSE: Delete cloud node by IP address
    #   INPUTS: { ip_addr: str - IP address of node to deallocate }
    #   OUTPUTS: { Optional[bool] - False on deletion error, None otherwise }
    #   SIDE_EFFECTS: Disables and removes node from DB, deletes cloud VM
    #   LINKS: M-CLOUD-MANAGER, M-DB
    # END_CONTRACT: deallocate
    async def deallocate(self, ip_addr: str):
        node = await self.db.get_node(ip_addr)
        if not node or not node.cloud:
            return
        if node.cloud not in self.apis:
            self.log.warning(
                f"Can't deallocate node {node.ip} - unsupported cloud {node.cloud}"
            )
        await self.db.disable_node(ip_addr)
        await self.db.commit()
        # START_BLOCK_DELETE_NODE
        try:
            await self.apis[node.cloud].delete_node(node.ip)
        except Exception as err:
            self.log.error(f"Can't deallocate node {node.ip}: {err}")
            return False
        # END_BLOCK_DELETE_NODE
        # START_BLOCK_REMOVE_NODE
        await self.db.remove_node(node.ip)
        await self.db.commit()
        # END_BLOCK_REMOVE_NODE
