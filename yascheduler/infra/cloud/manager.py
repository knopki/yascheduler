# FILE: yascheduler/infra/cloud/manager.py
# VERSION: 2.25.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CloudProvisionerImpl — pure cloud-API adapter implementing CloudProvisioner port (create/delete VM, cloud-init, setup, SSH keys); no DB access.
#   SCOPE: CloudProvisionerImpl: allocate/deallocate/select_provider lifecycle with SSH setup and cloud-init.
#   DEPENDS: M-DOMAIN-PORTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-ENGINE, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CLOUD-PROVIDER-SELECTION, M-CLOUD-CONFIGS, M-CLOUD-INIT, M-CLOUD-SSH-KEYS, M-SSH-REPOSITORY, M-SSH-SESSION, M-SSH-KEYS, M-DOMAIN-SETTINGS
#   LINKS: M-CLOUD-PROVISIONER, M-SSH-REPOSITORY, M-SSH-SESSION, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROVIDER-SELECTION, M-DOMAIN-EXCEPTIONS, M-SSH-KEYS, M-DOMAIN-ENGINE, M-CLOUD-INIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudAllocateError         # Cloud node allocation error (re-exported from domain.exceptions)
#   CloudSetupError            # Cloud node setup error (re-exported from domain.exceptions)
#   CloudProvisionerImpl       # Pure cloud-API adapter implementing CloudProvisioner port (no DB); allocate(provider, node: Node)->Node, deallocate(node: Node), select_provider
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v2.25.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v2.24.0 - remove log parameter from __init__/signatures; bind module-local logger = get_logger("M-CLOUD-PROVISIONER") at module top
# END_CHANGE_SUMMARY

"""Cloud provisioner implementation"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from yascheduler.domain import (
    CloudAllocateError,
    CloudSetupError,
    MachineSession,
    Node,
)
from yascheduler.infra.ssh.keys import list_private_keys

from .cloud_init import CloudInitConfig
from .provider_selection import select_provider_pure
from .ssh_keys import get_or_create_ssh_key

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey

    from yascheduler.domain import EngineRepository, LocalSettings, RemoteDefaults
    from yascheduler.infra import SSHMachineRepository

    from .adapters import CloudAdapter
    from .cloud_configs import ConfigCloud


# START_CONTRACT: CloudProvisionerImpl
#   PURPOSE: Cloud-API adapter implementing CloudProvisioner port (create/delete VM, cloud-init, setup, SSH keys); no DB access.
#   INPUTS: {
#     adapters: dict[str, CloudAdapter] - provider name to adapter,
#     configs: dict[str, ConfigCloud] - provider name to config,
#     machine_repository: SSHMachineRepository - SSH connection collection (connect/disconnect); _setup_vm calls session pass-throughs directly,
#     local_config: LocalSettings - local daemon config (keys),
#     remote_config: RemoteDefaults - remote machine defaults,
#     engines: EngineRepository - engine definitions for cloud-config,
#   }
#   OUTPUTS: { CloudProvisionerImpl - frozen instance }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-PORTS, M-SSH-REPOSITORY, M-SSH-SESSION, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROVIDER-SELECTION, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: CloudProvisionerImpl
@dataclass(frozen=True)
class CloudProvisionerImpl:
    """Multi-cloud provisioner implementing CloudProvisioner port.

    Creates/deletes cloud VMs, handles SSH setup, cloud-init, and engine
    installation. No DB access — all persistence is owned by use cases.
    """

    adapters: dict[str, CloudAdapter]
    configs: dict[str, ConfigCloud]
    machine_repository: SSHMachineRepository
    local_config: LocalSettings
    remote_config: RemoteDefaults
    engines: EngineRepository
    # Internal lock serializing SSH key load/generate across concurrent allocations.
    # Auto-constructed (init=False); not part of constructor signature.
    ssh_key_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    # START_CONTRACT: CloudProvisionerImpl.stop
    #   PURPOSE: Drain all SSH connections held by machine_repository (cloud-setup connections opened by _setup_vm).
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Awaits machine_repository.disconnect_all(), closing every connection in the repository's _machines registry.
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: CloudProvisionerImpl.stop
    async def stop(self) -> None:
        """Drain machine_repository connections opened during cloud allocation."""
        logger.info("cloud provisioner stop — draining machine_repository")
        await self.machine_repository.disconnect_all()

    # START_CONTRACT: CloudProvisionerImpl.select_provider
    #   PURPOSE: Select best provider by priority/capacity/platform, return its name.
    #   INPUTS: {
    #     platforms: list[str] - required platform identifiers,
    #     current_counts: dict[str, int] - provider name -> current node count
    #   }
    #   OUTPUTS: { str | None - selected provider name, or None when no capacity or throttle }
    #   SIDE_EFFECTS: None — sync, no I/O.
    #   LINKS: M-CLOUD-PROVIDER-SELECTION
    # END_CONTRACT: CloudProvisionerImpl.select_provider
    def select_provider(
        self,
        platforms: list[str],
        current_counts: dict[str, int],
    ) -> str | None:
        """Select best provider — sync port method."""
        # START_BLOCK_PURE_SELECT
        adapter = select_provider_pure(
            self.adapters, self.configs, platforms, current_counts
        )
        # END_BLOCK_PURE_SELECT

        if adapter is None:
            return None

        # START_BLOCK_THROTTLE_CHECK
        if adapter.get_op_semaphore().locked():
            logger.debug("THROTTLE", extra={"provider": adapter.name})
            return None
        # END_BLOCK_THROTTLE_CHECK

        return adapter.name

    # START_CONTRACT: CloudProvisionerImpl.allocate
    #   PURPOSE: Create VM on named provider, run cloud-init and engine setup, return the enabled Node (no DB write; caller flips enabled=TRUE via NodeRepository.update).
    #   INPUTS: { provider: str - selected provider name, node: Node - tmp-node whose node_id is reused as the real identity }
    #   OUTPUTS: { Node - enabled=True, ncpus populated, same node_id as the input }
    #   SIDE_EFFECTS: Creates cloud VM, writes SSH key, installs engines. On setup failure: best-effort disconnect (node.node_id) then delete VM.
    #   RAISES: CloudAllocateError - provider unknown or VM creation fails;
    #           CloudSetupError - SSH/cloud-init/setup fails
    #   LINKS: M-CLOUD-PROVISIONER, M-SSH-REPOSITORY, M-SSH-SESSION
    # END_CONTRACT: CloudProvisionerImpl.allocate
    async def allocate(self, provider: str, node: Node) -> Node:
        # START_BLOCK_RESOLVE_ALLOCATE_PROVIDER
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise CloudAllocateError(f"Unknown provider: {provider}")
        config = self.configs.get(provider)
        if config is None:
            raise CloudAllocateError(f"Config not found for provider {provider}")
        # END_BLOCK_RESOLVE_ALLOCATE_PROVIDER

        # START_BLOCK_CREATE_VM
        logger.debug("CREATE_VM", extra={"provider": adapter.name})
        try:
            ip_addr = await adapter.create_node(
                cfg=config,
                key=await self._get_ssh_key(),
                cloud_config=await self._get_cloud_config_data(adapter, config),
            )
        except Exception as err:
            logger.error("cloud create failed for %s: %s", adapter.name, err)
            raise CloudAllocateError(f"Create node error: {err}") from err
        # END_BLOCK_CREATE_VM

        # START_BLOCK_SETUP_VM
        # On either setup-failure path, disconnect the machine_repository
        # session for node.node_id BEFORE deleting the VM. A failed allocation
        # would otherwise leak a stale FREE session under node.node_id pointing
        # at the deleted VM's IP, which the allocator would pick up via
        # list_free() and fail against. disconnect is a safe no-op when
        # _connect_to_vm itself failed (never registered a session — see
        # SSHMachineRepository.disconnect). The disconnect is best-effort:
        # SSHMachineSession._close can raise (e.g. wait_closed on a broken
        # transport), and such a failure MUST NOT skip delete_node or a
        # billable VM would be orphaned — so disconnect failures are logged
        # and swallowed, then delete_node always runs.
        node = replace(
            node,
            hostname=ip_addr,
            external_id=ip_addr,
            cloud=adapter.name,
            username=config.username,
        )
        try:
            node = await self._setup_vm(node, adapter, config)
        except CloudSetupError:
            logger.warning(
                "cloud setup failed for %s node_id=%s — removing VM",
                node.hostname,
                node.node_id,
            )
            try:
                await self.machine_repository.disconnect(node.node_id)
            except Exception as disc_err:
                logger.warning(
                    "cloud disconnect failed: node_id=%s err=%s",
                    node.node_id,
                    disc_err,
                )
            await adapter.delete_node(cfg=config, host=node.hostname)
            raise
        except Exception as err:
            logger.warning(
                "cloud setup failed for %s node_id=%s — removing VM",
                node.hostname,
                node.node_id,
            )
            try:
                await self.machine_repository.disconnect(node.node_id)
            except Exception as disc_err:
                logger.warning(
                    "cloud disconnect failed: node_id=%s err=%s",
                    node.node_id,
                    disc_err,
                )
            await adapter.delete_node(cfg=config, host=node.hostname)
            raise CloudSetupError(f"Setup node error: {err}") from err
        # END_BLOCK_SETUP_VM

        logger.debug(
            "DONE",
            extra={
                "hostname": node.hostname,
                "node_id": node.node_id,
                "provider": node.cloud,
                "ncpus": node.ncpus,
            },
        )
        return node

    # START_CONTRACT: CloudProvisionerImpl.deallocate
    #   PURPOSE: Delete VM via named provider's SDK (no DB access).
    #   INPUTS: { node: Node - provider and host read from node.cloud/node.hostname }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Deletes cloud VM. No-ops (warn+return) when node.cloud is None, provider has no adapter, or provider has no config.
    #   LINKS: M-CLOUD-PROVISIONER
    # END_CONTRACT: CloudProvisionerImpl.deallocate
    async def deallocate(self, node: Node) -> None:
        # START_BLOCK_RESOLVE_DEALLOCATE_PROVIDER
        if node.cloud is None:
            logger.warning(
                "deallocate called with no cloud: node_id=%s",
                node.node_id,
            )
            return
        adapter = self.adapters.get(node.cloud)
        if adapter is None:
            logger.warning(
                "deallocate unsupported cloud: hostname=%s cloud=%s",
                node.hostname,
                node.cloud,
            )
            return
        config = self.configs.get(node.cloud)
        if config is None:
            logger.warning(
                "deallocate no config: hostname=%s cloud=%s",
                node.hostname,
                node.cloud,
            )
            return
        # END_BLOCK_RESOLVE_DEALLOCATE_PROVIDER

        # START_BLOCK_DELETE_VM
        await adapter.delete_node(cfg=config, host=node.hostname)
        logger.debug(
            "DONE",
            extra={
                "hostname": node.hostname,
                "cloud": node.cloud,
                "node_id": node.node_id,
            },
        )
        # END_BLOCK_DELETE_VM

    # ---- Private helpers ----

    def _is_platform_supported(self, adapter: CloudAdapter, platform: str) -> bool:
        """Check if adapter supports the given platform."""
        return any(check(platform) for check in adapter.supported_platform_checks)

    # START_CONTRACT: CloudProvisionerImpl._get_ssh_key
    #   PURPOSE: Async wrapper around get_or_create_ssh_key with lock for thread safety.
    #   INPUTS: { None }
    #   OUTPUTS: { SSHKey - loaded or generated SSH key }
    #   SIDE_EFFECTS: Loads or generates SSH key file.
    async def _get_ssh_key(self) -> SSHKey:
        """Async-thread-safe SSH key load/generate."""
        async with self.ssh_key_lock:
            return await asyncio.get_running_loop().run_in_executor(
                None, get_or_create_ssh_key, self.local_config.keys_dir
            )

    # START_CONTRACT: CloudProvisionerImpl._get_cloud_config_data
    #   PURPOSE: Build cloud-config with packages for engines matching adapter platforms.
    #   INPUTS: {
    #     adapter: CloudAdapter - target provider adapter,
    #     config: ConfigCloud - resolved per-cloud config DTO (sources package_upgrade)
    #   }
    #   OUTPUTS: { CloudInitConfig - cloud-config data with packages }
    #   SIDE_EFFECTS: None — package_upgrade flag is sourced from config.package_upgrade (per-provider DTO field, default True), NOT from self.local_config and NOT hardcoded.
    #   LINKS: M-CLOUD-INIT, M-CLOUD-CONFIGS
    # END_CONTRACT: CloudProvisionerImpl._get_cloud_config_data
    async def _get_cloud_config_data(
        self, adapter: CloudAdapter, config: ConfigCloud
    ) -> CloudInitConfig:
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
        return CloudInitConfig(
            package_upgrade=config.package_upgrade,
            packages=pkgs,
        )

    # START_CONTRACT: CloudProvisionerImpl._setup_vm
    #   PURPOSE: Bring a freshly-created VM to a usable state (cloud-init done, engines installed) and return the enabled Node.
    #   INPUTS: {
    #     node: Node - session registers under node.node_id,
    #     adapter: CloudAdapter - provider adapter (for timeout settings),
    #     config: ConfigCloud - provider config
    #   }
    #   OUTPUTS: { Node }
    #   SIDE_EFFECTS: Stamps jump-leg identity on Node via replace before SSH connect; connects to VM (session registers under node.node_id), runs cloud-init, installs engines.
    #   RAISES: CloudSetupError - on any SSH/cloud-init/setup failure
    #   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
    # END_CONTRACT: CloudProvisionerImpl._setup_vm
    async def _setup_vm(
        self,
        node: Node,
        adapter: CloudAdapter,
        config: ConfigCloud,
    ) -> Node:
        """Connect to VM, wait for cloud-init, install engines, return enabled Node via replace."""
        # START_BLOCK_RESOLVE_JUMP
        # Resolve jump from the matching CloudConfig (prefix == node.cloud)
        # before opening the setup SSH session. Fall back to remote defaults.
        # All three jump fields come from the SAME source (atomic leg rule).
        jump_host = self.remote_config.jump_host
        jump_username = self.remote_config.jump_username or "root"
        jump_port = self.remote_config.jump_port
        if config.prefix == node.cloud and config.jump_host and config.jump_username:
            jump_host = config.jump_host
            jump_username = config.jump_username
            jump_port = config.jump_port
        node = replace(
            node,
            jump_host=jump_host,
            jump_username=jump_username,
            jump_port=jump_port,
        )
        # END_BLOCK_RESOLVE_JUMP

        # START_BLOCK_SSH_CONNECT_SETUP
        session = await self._connect_to_vm(node, adapter, config)
        # END_BLOCK_SSH_CONNECT_SETUP

        # START_BLOCK_CLOUD_INIT
        # `cloud-init status --wait` blocks until cloud-init finishes (or hangs).
        # Bound it with adapter.create_node_timeout so a hung cloud-init cannot
        # pin an allocator worker forever. The failure message includes both
        # stdout and stderr — cloud-init writes its status line to stdout, so
        # omitting stdout (the previous behavior) gave no clue why it failed.
        logger.debug("CLOUD_INIT", extra={"hostname": node.hostname})
        try:
            result = await asyncio.wait_for(
                session.run("cloud-init status --wait"),
                timeout=adapter.create_node_timeout,
            )
            if result.exit_code != 0:
                raise CloudSetupError(
                    f"cloud-init failed on {node.hostname}: exit={result.exit_code} "
                    f"stdout={result.stdout} stderr={result.stderr}"
                )
        except asyncio.TimeoutError as err:
            raise CloudSetupError(
                f"cloud-init status --wait timed out on {node.hostname} "
                f"after {adapter.create_node_timeout}s"
            ) from err
        except CloudSetupError:
            raise
        except Exception as err:
            raise CloudSetupError(
                f"cloud-init status --wait failed on {node.hostname}: {err}"
            ) from err
        # END_BLOCK_CLOUD_INIT

        # START_BLOCK_SETUP_NODE
        logger.debug("SETUP_NODE", extra={"hostname": node.hostname})
        try:
            await session.setup_node(self.engines)
        except Exception as err:
            raise CloudSetupError(f"Setup node {node.hostname} failed: {err}") from err
        # END_BLOCK_SETUP_NODE

        logger.debug(
            "READY", extra={"hostname": node.hostname, "node_id": node.node_id}
        )
        return replace(node, enabled=True)

    # START_CONTRACT: CloudProvisionerImpl._connect_to_vm
    #   PURPOSE: Connect to VM via SSH gateway with retry-friendly error wrapping.
    #   INPUTS: {
    #     node: Node,
    #     adapter: CloudAdapter - provider adapter (for timeout settings),
    #     config: ConfigCloud - provider config
    #   }
    #   OUTPUTS: { MachineSession - connected machine session instance }
    #   SIDE_EFFECTS: Opens SSH connection to VM (session registered under node.node_id).
    #   RAISES: CloudSetupError - if SSH connection fails
    #   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
    # END_CONTRACT: CloudProvisionerImpl._connect_to_vm
    async def _connect_to_vm(
        self,
        node: Node,
        adapter: CloudAdapter,
        config: ConfigCloud,
    ) -> MachineSession:
        """Connect to VM via SSH gateway with retry-friendly error wrapping."""
        # START_BLOCK_GET_KEYS
        keys: Sequence[PurePath] = await asyncio.get_running_loop().run_in_executor(
            None, list_private_keys, self.local_config.keys_dir
        )
        # END_BLOCK_GET_KEYS

        # START_BLOCK_SSH_CONNECT_VM
        logger.debug(
            "CONNECT",
            extra={
                "hostname": node.hostname,
                "node_id": node.node_id,
                "username": node.username,
            },
        )
        try:
            session = await self.machine_repository.connect(
                node=node,
                client_keys=keys,
                connect_timeout=adapter.create_node_conn_timeout,
                data_dir=self.remote_config.data_dir,
                engines_dir=self.remote_config.engines_dir,
                tasks_dir=self.remote_config.tasks_dir,
            )
        except Exception as err:
            raise CloudSetupError(
                f"SSH connect to {node.hostname} failed: {err}"
            ) from err
        # END_BLOCK_SSH_CONNECT_VM
        return session
