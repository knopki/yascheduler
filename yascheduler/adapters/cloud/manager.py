# FILE: yascheduler/adapters/cloud/manager.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CloudProvisionerImpl — implementation of the CloudProvisioner port with multi-provider support.
#   SCOPE: CloudProvisionerImpl class implementing allocate, deallocate, capacity with provider selection,
#     cloud-config building, cloud-init wait, and node setup via SSHMachineGateway.
#   DEPENDS: M-DOMAIN-PORTS, M-DOMAIN-MODEL, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CONFIG, M-SSH-GATEWAY
#   LINKS: M-CLOUD-PROVISIONER, M-SSH-GATEWAY, M-CLOUD-ADAPTERS-NEW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudAllocateError         # Cloud node allocation error
#   CloudSetupError            # Cloud node setup error (SSH/cloud-init)
#   CloudProvisionerImpl       # CloudProvisioner port implementation with multi-provider support
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Extract SSH key logic to ssh_keys.py; delegate _get_ssh_key to get_or_create_ssh_key.
#   PREVIOUS_CHANGE: v1.1.0 - Extract _acquire_provider_slot from allocate, _connect_to_vm from _setup_vm to fix func-size warnings.
# END_CHANGE_SUMMARY

"""Cloud provisioner implementation"""

from __future__ import annotations

import asyncio
from asyncio.locks import Lock
from typing import TYPE_CHECKING

from attrs import define, field

from yascheduler.domain.model import ConnectedMachine, Node

from .cloud_config import CloudConfig
from .protocols import CloudCapacity
from .ssh_keys import get_or_create_ssh_key

if TYPE_CHECKING:
    import logging
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey

    from yascheduler.adapters.cloud.adapters import CloudAdapter
    from yascheduler.adapters.cloud.protocols import PCloudConfig
    from yascheduler.adapters.ssh.gateway import SSHMachineGateway
    from yascheduler.config import (
        ConfigCloud,
        ConfigLocal,
        ConfigRemote,
        EngineRepository,
    )
    from yascheduler.domain.ports import NodeRepository


class CloudAllocateError(Exception):
    """Cloud node allocation error — provider selection or VM creation failed."""


class CloudSetupError(Exception):
    """Cloud node setup error — SSH / cloud-init / engine installation failed."""


# START_CONTRACT: CloudProvisionerImpl
#   PURPOSE: Multi-cloud provisioner implementing CloudProvisioner port + backward-compat methods.
#   INPUTS: {
#     adapters: dict[str, CloudAdapter] - provider name to adapter,
#     configs: dict[str, ConfigCloud] - provider name to config,
#     node_repo: NodeRepository - DB operations,
#     machine_gateway: SSHMachineGateway - SSH connections,
#     local_config: ConfigLocal - local daemon config (keys),
#     remote_config: ConfigRemote - remote machine defaults,
#     engines: EngineRepository - engine definitions for cloud-config,
#     log: logging.Logger - logger
#   }
#   OUTPUTS: { CloudProvisionerImpl - frozen instance }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-PORTS, M-SSH-GATEWAY, M-CLOUD-MANAGER
# END_CONTRACT: CloudProvisionerImpl
@define(frozen=True)
class CloudProvisionerImpl:
    """Multi-cloud provisioner implementing CloudProvisioner port.

    Satisfies ``CloudProvisioner`` Protocol via structural subtyping.
    Also exposes backward-compat methods for unmigrated callers.
    """

    adapters: dict[str, CloudAdapter] = field()
    configs: dict[str, ConfigCloud] = field()
    node_repo: NodeRepository = field()
    machine_gateway: SSHMachineGateway = field()
    local_config: ConfigLocal = field()
    remote_config: ConfigRemote = field()
    engines: EngineRepository = field()
    log: logging.Logger = field()
    on_tasks: set[int] = field(init=False, factory=set)
    allocation_lock: Lock = field(factory=Lock, init=False)
    ssh_key_lock: asyncio.Lock = field(factory=asyncio.Lock, init=False)

    # ---- Compatibility helpers ----

    def __bool__(self) -> bool:
        """True when at least one adapter is configured."""
        return bool(self.adapters)

    @property
    def apis(self) -> dict[str, CloudAdapter]:
        """Return adapters dict (matches old CloudAPIManager.apis convention)."""
        return self.adapters

    async def stop(self) -> None:
        """No-op — compatibility hook."""
        self.log.info("[CloudProvisionerImpl] stop (no-op)")

    def mark_task_done(self, on_task: int) -> None:
        """Remove task from in-flight tracking set."""
        self.on_tasks.discard(on_task)

    # START_CONTRACT: CloudProvisionerImpl.allocate
    #   PURPOSE: Select best provider, create VM, connect SSH, cloud-init, setup node.
    #   INPUTS: { platforms: list[str] - required platform identifiers }
    #   OUTPUTS: { Node - persisted node record }
    #   SIDE_EFFECTS: Creates cloud VM, writes SSH key, installs engines. Removes tmp + deletes VM on failure.
    #   RAISES: CloudAllocateError - if no provider or VM creation fails;
    #           CloudSetupError - if SSH/cloud-init/setup fails
    #   LINKS: M-CLOUD-MANAGER, M-SSH-GATEWAY
    # END_CONTRACT: CloudProvisionerImpl.allocate
    async def allocate(self, platforms: list[str]) -> Node:
        """Allocate a new cloud node — satisfies ``CloudProvisioner`` port."""
        # START_BLOCK_SELECT_PROVIDER
        adapter, config, tmp_ip = await self._acquire_provider_slot(platforms)
        # END_BLOCK_SELECT_PROVIDER

        # START_BLOCK_CREATE_VM
        self.log.debug(
            "[CloudProvisionerImpl][allocate][CREATE_VM] provider=%s",
            adapter.name,
        )
        try:
            ip_addr = await adapter.create_node(
                log=self.log,
                cfg=config,
                key=await self._get_ssh_key(),
                cloud_config=await self._get_cloud_config_data(adapter),
            )
        except Exception as err:
            self.log.error("[CloudProvisionerImpl][allocate][CREATE_FAILED] %s", err)
            await self._safe_remove_tmp(tmp_ip)
            raise CloudAllocateError(f"Create node error: {err}") from err
        # END_BLOCK_CREATE_VM

        # START_BLOCK_CLEANUP_TMP
        await self._safe_remove_tmp(tmp_ip)
        # END_BLOCK_CLEANUP_TMP

        # START_BLOCK_SETUP_VM
        try:
            node = await self._setup_vm(ip_addr, adapter, config)
        except (CloudSetupError, Exception) as err:
            self.log.warning(
                "[CloudProvisionerImpl][allocate][SETUP_FAILED] ip=%s - removing VM",
                ip_addr,
            )
            await adapter.delete_node(log=self.log, cfg=config, host=ip_addr)
            if isinstance(err, CloudSetupError):
                raise
            raise CloudSetupError(f"Setup node error: {err}") from err
        # END_BLOCK_SETUP_VM

        # START_BLOCK_PERSIST_NODE
        self.log.info(
            "[CloudProvisionerImpl][allocate][DONE] ip=%s provider=%s ncpus=%d",
            node.ip,
            node.cloud,
            node.ncpus,
        )
        await self.node_repo.add(node)
        # END_BLOCK_PERSIST_NODE
        return node

    # START_CONTRACT: CloudProvisionerImpl.deallocate
    #   PURPOSE: Disable cloud node, delete VM, remove from DB.
    #   INPUTS: { ip: str - IP address of the node to deallocate }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Disables node, deletes cloud VM, removes from DB. Logs errors.
    #   LINKS: M-CLOUD-MANAGER
    # END_CONTRACT: CloudProvisionerImpl.deallocate
    async def deallocate(self, ip: str) -> None:
        """Deallocate a cloud node — satisfies ``CloudProvisioner`` port."""
        # START_BLOCK_GET_NODE
        node = await self.node_repo.get(ip)
        if node is None:
            self.log.warning("[CloudProvisionerImpl][deallocate][NOT_FOUND] ip=%s", ip)
            return
        if not node.cloud:
            self.log.warning("[CloudProvisionerImpl][deallocate][NO_CLOUD] ip=%s", ip)
            return
        # END_BLOCK_GET_NODE

        # START_BLOCK_RESOLVE_PROVIDER
        adapter = self.adapters.get(node.cloud)
        if adapter is None:
            self.log.warning(
                "[CloudProvisionerImpl][deallocate][UNSUPPORTED] ip=%s cloud=%s",
                ip,
                node.cloud,
            )
            return
        config = self.configs.get(node.cloud)
        if config is None:
            self.log.warning(
                "[CloudProvisionerImpl][deallocate][NO_CONFIG] ip=%s cloud=%s",
                ip,
                node.cloud,
            )
            return
        # END_BLOCK_RESOLVE_PROVIDER

        # START_BLOCK_DISABLE_AND_DELETE
        await self.node_repo.disable(ip)
        await adapter.delete_node(log=self.log, cfg=config, host=ip)
        await self.node_repo.remove(ip)
        self.log.info(
            "[CloudProvisionerImpl][deallocate][DONE] ip=%s cloud=%s", ip, node.cloud
        )
        # END_BLOCK_DISABLE_AND_DELETE

    # START_CONTRACT: CloudProvisionerImpl.capacity
    #   PURPOSE: Report available capacity per provider (max - current).
    #   INPUTS: { None }
    #   OUTPUTS: { dict[str, int] - provider name to available slots }
    #   SIDE_EFFECTS: Reads all nodes from DB.
    #   LINKS: M-CLOUD-MANAGER
    # END_CONTRACT: CloudProvisionerImpl.capacity
    async def capacity(self) -> dict[str, int]:
        """Return available capacity per provider — satisfies ``CloudProvisioner`` port."""
        cap = await self.get_capacity()
        return {name: max(0, c.max - c.current) for name, c in cap.items()}

    # ---- Backward-compat methods ----

    # START_CONTRACT: CloudProvisionerImpl.allocate_with_tracking
    #   PURPOSE: Backward-compat wrapper: task dedup, error handling, returns IP string.
    #   INPUTS: {
    #     on_task: Optional[int] - task ID for dedup tracking,
    #     platforms: Optional[list[str]] - platform filter,
    #     throttle: bool - whether to skip overloaded providers (default True)
    #   }
    #   OUTPUTS: { str | None - node IP or None on error/duplicate }
    #   SIDE_EFFECTS: Tracks in-flight allocations via on_tasks set.
    #   LINKS: M-CLOUD-MANAGER
    # END_CONTRACT: CloudProvisionerImpl.allocate_with_tracking
    async def allocate_with_tracking(
        self,
        on_task: int | None = None,
        platforms: list[str] | None = None,
        throttle: bool = True,
    ) -> str | None:
        """Backward-compat allocate: dedup by task_id, return IP string or None."""
        # START_BLOCK_DEDUP
        if on_task is not None and on_task in self.on_tasks:
            self.log.debug(
                "[CloudProvisionerImpl][allocate_with_tracking][DEDUP] on_task=%s",
                on_task,
            )
            return None
        if on_task is not None:
            self.on_tasks.add(on_task)
        # END_BLOCK_DEDUP

        # START_BLOCK_DELEGATE
        try:
            node = await self.allocate(platforms or [])
            return node.ip
        except (CloudAllocateError, CloudSetupError) as err:
            self.log.error(
                "[CloudProvisionerImpl][allocate_with_tracking][FAIL] %s", err
            )
            if on_task is not None:
                self.mark_task_done(on_task)
            return None
        # END_BLOCK_DELEGATE

    # START_CONTRACT: CloudProvisionerImpl.get_capacity
    #   PURPOSE: Return CloudCapacity objects per provider (backward compat).
    #   INPUTS: { None }
    #   OUTPUTS: { dict[str, CloudCapacity] - provider name to capacity info }
    #   SIDE_EFFECTS: Reads all nodes from DB.
    #   LINKS: M-CLOUD-MANAGER
    # END_CONTRACT: CloudProvisionerImpl.get_capacity
    async def get_capacity(self) -> dict[str, CloudCapacity]:
        """Return CloudCapacity per provider (backward compat)."""
        # START_BLOCK_COUNT_NODES
        nodes = await self.node_repo.list_all()
        counts: dict[str, int] = {}
        for n in nodes:
            if n.cloud:
                counts[n.cloud] = counts.get(n.cloud, 0) + 1
        # END_BLOCK_COUNT_NODES

        # START_BLOCK_BUILD_CAPACITY
        result: dict[str, CloudCapacity] = {}
        for name, adapter in self.adapters.items():
            config = self.configs.get(name)
            current = counts.get(name, 0)
            max_nodes = config.max_nodes if config else 0
            result[name] = CloudCapacity(
                name=name,
                current=current,
                max=max_nodes,
            )
        # END_BLOCK_BUILD_CAPACITY
        return result

    # ---- Private helpers ----

    # START_CONTRACT: CloudProvisionerImpl._select_best_provider
    #   PURPOSE: Pick the highest-priority provider with available capacity & platform support.
    #   INPUTS: { platforms: list[str] - required platform identifiers }
    #   OUTPUTS: { CloudAdapter | None - best matching provider or None }
    #   SIDE_EFFECTS: Reads all nodes from DB.
    #   LINKS: M-CLOUD-MANAGER
    # END_CONTRACT: CloudProvisionerImpl._select_best_provider
    async def _select_best_provider(self, platforms: list[str]) -> CloudAdapter | None:
        """Select best provider by priority and capacity."""
        # START_BLOCK_GET_COUNTS
        nodes = await self.node_repo.list_all()
        counts: dict[str, int] = {}
        for n in nodes:
            if n.cloud:
                counts[n.cloud] = counts.get(n.cloud, 0) + 1
        # END_BLOCK_GET_COUNTS

        # START_BLOCK_FILTER_SUITABLE
        suitable: list[CloudAdapter] = []
        for name, adapter in self.adapters.items():
            config = self.configs.get(name)
            if config is None:
                continue
            current = counts.get(name, 0)
            if current >= config.max_nodes:
                self.log.debug(
                    "[CloudProvisionerImpl][select_provider][MAXED] %s (%d/%d)",
                    name,
                    current,
                    config.max_nodes,
                )
                continue
            # start of platform check block
            if not any(self._is_platform_supported(adapter, p) for p in platforms):
                self.log.debug(
                    "[CloudProvisionerImpl][select_provider][NO_PLATFORM] %s for %s",
                    name,
                    platforms,
                )
                continue
            # end of platform check block
            suitable.append(adapter)
        # END_BLOCK_FILTER_SUITABLE

        if not suitable:
            self.log.debug(
                "[CloudProvisionerImpl][select_provider][NONE] no suitable providers"
            )
            return None

        # START_BLOCK_SORT_BY_PRIORITY
        suitable.sort(
            key=lambda a: self.configs[a.name].priority,  # type: ignore[index]
            reverse=True,
        )
        chosen = suitable[0]
        self.log.debug(
            "[CloudProvisionerImpl][select_provider][CHOSEN] %s (priority=%d)",
            chosen.name,
            self.configs[chosen.name].priority,  # type: ignore[index]
        )
        # END_BLOCK_SORT_BY_PRIORITY
        return chosen

    # START_CONTRACT: CloudProvisionerImpl._is_platform_supported
    #   PURPOSE: Check if a platform string is supported by the given adapter.
    #   INPUTS: { adapter: CloudAdapter, platform: str }
    #   OUTPUTS: { bool }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-ADAPTERS
    # END_CONTRACT: CloudProvisionerImpl._is_platform_supported
    def _is_platform_supported(self, adapter: CloudAdapter, platform: str) -> bool:
        """Check if adapter supports the given platform."""
        return any(check(platform) for check in adapter.supported_platform_checks)

    # START_CONTRACT: CloudProvisionerImpl._get_ssh_key
    #   PURPOSE: Async wrapper around get_or_create_ssh_key with lock for thread safety.
    #   INPUTS: { None }
    #   OUTPUTS: { SSHKey - loaded or generated SSH key }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-PROVISIONER, M-CLOUD-SSH-KEYS
    # END_CONTRACT: CloudProvisionerImpl._get_ssh_key
    async def _get_ssh_key(self) -> SSHKey:
        """Async-thread-safe SSH key load/generate."""
        async with self.ssh_key_lock:
            return await asyncio.get_running_loop().run_in_executor(
                None, get_or_create_ssh_key, self.local_config.keys_dir, self.log
            )

    # START_CONTRACT: CloudProvisionerImpl._get_cloud_config_data
    #   PURPOSE: Build cloud-config with packages for engines matching adapter platforms.
    #   INPUTS: { adapter: CloudAdapter - target provider adapter }
    #   OUTPUTS: { PCloudConfig - cloud-config data with packages }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-CLOUD
    # END_CONTRACT: CloudProvisionerImpl._get_cloud_config_data
    async def _get_cloud_config_data(self, adapter: CloudAdapter) -> PCloudConfig:
        """Build cloud-config with engine packages for this adapter's platforms."""
        # START_BLOCK_FILTER_ENGINES
        supported_engines = self.engines.filter(
            lambda e: (
                (
                    bool(e.platforms)
                    and any(
                        self._is_platform_supported(adapter, p) for p in e.platforms
                    )
                )
                or not e.platforms
            )
        )
        pkgs = supported_engines.get_platform_packages()
        # END_BLOCK_FILTER_ENGINES
        return CloudConfig(package_upgrade=True, packages=pkgs)

    # START_CONTRACT: CloudProvisionerImpl._acquire_provider_slot
    #   PURPOSE: Select provider, check throttle, add tmp node. Returns (adapter, config, tmp_ip).
    #   INPUTS: { platforms: list[str] - required platform identifiers }
    #   OUTPUTS: { tuple[CloudAdapter, ConfigCloud, str] - (adapter, config, tmp_ip) }
    #   SIDE_EFFECTS: Creates temp node in DB; acquires allocation_lock.
    #   RAISES: CloudAllocateError - if no provider or provider overloaded
    #   LINKS: M-CLOUD-MANAGER, M-DOMAIN-PORTS
    # END_CONTRACT: CloudProvisionerImpl._acquire_provider_slot
    async def _acquire_provider_slot(
        self, platforms: list[str]
    ) -> tuple[CloudAdapter, ConfigCloud, str]:
        """Select provider, check throttle, add tmp node."""
        # START_BLOCK_SELECT_PROVIDER
        async with self.allocation_lock:
            adapter = await self._select_best_provider(platforms)
            if adapter is None:
                raise CloudAllocateError(
                    f"No available provider for platforms {platforms}"
                )
            config = self.configs.get(adapter.name)
            if config is None:
                raise CloudAllocateError(
                    f"Config not found for provider {adapter.name}"
                )

            # START_BLOCK_CHECK_THROTTLE
            if adapter.get_op_semaphore().locked():
                self.log.debug(
                    "[CloudProvisionerImpl][allocate][THROTTLE] provider=%s sleeping 1s",
                    adapter.name,
                )
                await asyncio.sleep(1)
                raise CloudAllocateError(f"Provider {adapter.name} is overloaded")
            # END_BLOCK_CHECK_THROTTLE

            # START_BLOCK_ADD_TMP
            self.log.debug(
                "[CloudProvisionerImpl][allocate][TMP] provider=%s username=%s",
                adapter.name,
                config.username,
            )
            tmp_ip = await self.node_repo.add_tmp(adapter.name, config.username)
            # END_BLOCK_ADD_TMP
        # END_BLOCK_SELECT_PROVIDER
        return adapter, config, tmp_ip

    # START_CONTRACT: CloudProvisionerImpl._setup_vm
    #   PURPOSE: Connect via SSH, wait for cloud-init, install engines, get CPU count.
    #   INPUTS: {
    #     ip_addr: str - VM IP address,
    #     adapter: CloudAdapter - provider adapter (for timeout settings),
    #     config: ConfigCloud - provider config (for SSH username/jump)
    #   }
    #   OUTPUTS: { Node - node model with ncpus populated }
    #   SIDE_EFFECTS: Connects to VM, runs cloud-init, installs engines.
    #   RAISES: CloudSetupError - on any SSH/cloud-init/setup failure
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: CloudProvisionerImpl._setup_vm
    async def _setup_vm(
        self,
        ip_addr: str,
        adapter: CloudAdapter,
        config: ConfigCloud,
    ) -> Node:
        """Connect to VM, wait for cloud-init, install engines, return Node."""
        # START_BLOCK_SSH_CONNECT
        connected_machine = await self._connect_to_vm(ip_addr, adapter, config)
        # END_BLOCK_SSH_CONNECT

        # START_BLOCK_CLOUD_INIT
        self.log.debug("[CloudProvisionerImpl][setup_vm][CLOUD_INIT] ip=%s", ip_addr)
        try:
            result = await self.machine_gateway.run(
                connected_machine, "cloud-init status --wait"
            )
            if result.exit_code != 0:
                raise CloudSetupError(
                    f"cloud-init failed on {ip_addr}: exit={result.exit_code} "
                    f"stderr={result.stderr}"
                )
        except CloudSetupError:
            raise
        except Exception as err:
            raise CloudSetupError(
                f"cloud-init status --wait failed on {ip_addr}: {err}"
            ) from err
        # END_BLOCK_CLOUD_INIT

        # START_BLOCK_SETUP_NODE
        self.log.debug("[CloudProvisionerImpl][setup_vm][SETUP_NODE] ip=%s", ip_addr)
        try:
            await self.machine_gateway.setup_node(ip_addr, self.engines)
        except Exception as err:
            raise CloudSetupError(f"Setup node {ip_addr} failed: {err}") from err
        # END_BLOCK_SETUP_NODE

        # START_BLOCK_GET_CPUS
        try:
            ncpus = await self.machine_gateway.get_cpu_cores(ip_addr)
        except Exception as err:
            raise CloudSetupError(f"Get CPU cores for {ip_addr} failed: {err}") from err
        # END_BLOCK_GET_CPUS

        self.log.info(
            "[CloudProvisionerImpl][setup_vm][READY] ip=%s ncpus=%d",
            ip_addr,
            ncpus,
        )
        return Node(
            ip=ip_addr,
            ncpus=ncpus,
            enabled=True,
            cloud=adapter.name,
            username=config.username,
            port=22,
        )

    # START_CONTRACT: CloudProvisionerImpl._connect_to_vm
    #   PURPOSE: Connect to VM via SSH gateway with retry-friendly error wrapping.
    #   INPUTS: {
    #     ip_addr: str - VM IP address,
    #     adapter: CloudAdapter - provider adapter (for timeout settings),
    #     config: ConfigCloud - provider config (for SSH username/jump)
    #   }
    #   OUTPUTS: { ConnectedMachine - connected machine instance }
    #   SIDE_EFFECTS: Opens SSH connection to VM.
    #   RAISES: CloudSetupError - if SSH connection fails
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: CloudProvisionerImpl._connect_to_vm
    async def _connect_to_vm(
        self, ip_addr: str, adapter: CloudAdapter, config: ConfigCloud
    ) -> ConnectedMachine:
        """Connect to VM via SSH gateway with retry-friendly error wrapping."""
        # START_BLOCK_GET_KEYS
        keys: Sequence[PurePath] = await asyncio.get_running_loop().run_in_executor(
            None, self.local_config.get_private_keys
        )
        # END_BLOCK_GET_KEYS

        # START_BLOCK_SSH_CONNECT
        self.log.debug(
            "[CloudProvisionerImpl][setup_vm][CONNECT] ip=%s username=%s",
            ip_addr,
            config.username,
        )
        try:
            connected_machine = await self.machine_gateway.connect(
                ip=ip_addr,
                username=config.username,
                client_keys=keys,
                connect_timeout=adapter.create_node_conn_timeout,
                data_dir=self.remote_config.data_dir,
                engines_dir=self.remote_config.engines_dir,
                tasks_dir=self.remote_config.tasks_dir,
                jump_host=getattr(config, "jump_host", None) or None,
                jump_username=getattr(config, "jump_username", None) or None,
            )
        except Exception as err:
            raise CloudSetupError(f"SSH connect to {ip_addr} failed: {err}") from err
        # END_BLOCK_SSH_CONNECT
        return connected_machine

    # START_CONTRACT: CloudProvisionerImpl._safe_remove_tmp
    #   PURPOSE: Remove temporary node from DB, ignoring errors.
    #   INPUTS: { tmp_ip: str - temporary IP to remove }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Removes tmp node from DB.
    #   LINKS: M-DOMAIN-PORTS
    # END_CONTRACT: CloudProvisionerImpl._safe_remove_tmp
    async def _safe_remove_tmp(self, tmp_ip: str) -> None:
        """Remove temporary node, swallow errors."""
        try:
            await self.node_repo.remove(tmp_ip)
        except Exception:  # noqa: BLE001
            self.log.debug(
                "[CloudProvisionerImpl][safe_remove_tmp] ignore error for %s",
                tmp_ip,
            )
