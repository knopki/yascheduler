"""Cloud provisioner implementation."""
# region MODULE_CONTRACT
# PURPOSE: Translate the CloudProvisioner port into concrete cloud-API calls (VM lifecycle, SSH setup, cloud-init) while keeping all persistence in the caller's hands.
# SCOPE: CloudProvisionerImpl: allocate/deallocate/select_provider lifecycle with SSH setup and cloud-init.
# DEPENDENCIES: READS: SSH private keys from local keys_dir (via list_private_keys); delegates SSH connection to machine_repository
# KEYWORDS: cloud provisioner, allocate, deallocate, select provider, vm, cloud-init, ssh, setup
# endregion MODULE_CONTRACT

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

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey

    from yascheduler.domain import EngineRepository, LocalSettings, RemoteDefaults
    from yascheduler.infra import SSHMachineRepository

    from .adapters import CloudAdapter
    from .cloud_configs import ConfigCloud
    from .dto import CloudCreateNodeDTO

__all__ = ["CloudProvisionerImpl"]
logger = logging.getLogger(__name__)


# region CLASS_CloudProvisionerImpl
# PURPOSE: Implement the CloudProvisioner port through concrete cloud-API calls so the allocator can spin up and tear down cloud VMs without knowing provider specifics.
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

    # region METHOD_stop
    # PURPOSE: Release all SSH connections opened during cloud setup so the daemon can shut down cleanly without leaking connections.
    # ENSURES: Awaits machine_repository.disconnect_all(), closing every connection in the repository's _machines registry.
    async def stop(self) -> None:
        """Drain machine_repository connections opened during cloud allocation."""
        logger.info("cloud provisioner stop — draining machine_repository")
        await self.machine_repository.disconnect_all()

    # endregion METHOD_stop

    # region METHOD_select_provider
    # PURPOSE: Pick the best provider by priority/capacity/platform and respect its concurrency throttle so the allocator avoids overload and chooses cost-effectively.
    # ENSURES: Sync, no I/O; returns None when no capacity or throttle.
    def select_provider(
        self,
        platforms: list[str],
        current_counts: dict[str, int],
    ) -> str | None:
        """Select best provider — sync port method."""
        # region BLOCK_pure_select
        adapter = select_provider_pure(
            self.adapters,
            self.configs,
            platforms,
            current_counts,
        )
        # endregion BLOCK_pure_select

        if adapter is None:
            return None

        # region BLOCK_throttle_check
        if adapter.get_op_semaphore().locked():
            logger.debug("THROTTLE", extra={"provider": adapter.name})
            return None
        # endregion BLOCK_throttle_check

        return adapter.name

    # endregion METHOD_select_provider

    # region METHOD_allocate
    # PURPOSE: Spin up a cloud VM, run cloud-init and engine setup, and return an enabled Node so the scheduler gets a usable compute node. On failure, tear down the VM to avoid orphaned billable resources.
    # REQUIRES: provider name is known and has a config.
    # ENSURES:
    # - returned Node.node_id == node.node_id
    # - hostname, external_id, username, port, jump_host, jump_port, jump_username copied from CloudCreateNodeDTO
    # - cloud == adapter.name
    # - on success enabled=True and ncpus is None — the standalone get_cpu_cores() is NOT invoked here
    # RAISES: CloudAllocateError if provider unknown or VM creation fails; CloudSetupError if SSH/cloud-init/setup fails.
    async def allocate(self, provider: str, node: Node) -> Node:
        """Create VM on named provider, run cloud-init and engine setup, return the enabled Node (no DB write; caller flips enabled=TRUE via NodeRepository."""
        # region BLOCK_resolve_allocate_provider
        adapter = self.adapters.get(provider)
        if adapter is None:
            msg = f"Unknown provider: {provider}"
            raise CloudAllocateError(msg)
        config = self.configs.get(provider)
        if config is None:
            msg = f"Config not found for provider {provider}"
            raise CloudAllocateError(msg)
        # endregion BLOCK_resolve_allocate_provider

        # region BLOCK_create_vm
        logger.debug("CREATE_VM", extra={"provider": adapter.name})
        try:
            dto: CloudCreateNodeDTO = await adapter.create_node(
                cfg=config,
                key=await self._get_ssh_key(),
                cloud_config=await self._get_cloud_config_data(adapter, config),
            )
        except Exception as err:
            logger.exception("cloud create failed for %s", adapter.name)
            msg = f"Create node error: {err}"
            raise CloudAllocateError(msg) from err
        # endregion BLOCK_create_vm

        # region BLOCK_setup_vm
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
            hostname=dto.hostname,
            external_id=dto.external_id,
            cloud=adapter.name,
            username=dto.username,
            port=dto.port,
            jump_host=dto.jump_host,
            jump_port=dto.jump_port,
            jump_username=dto.jump_username,
        )
        try:
            node = await self._setup_vm(node, adapter, config)
        except CloudSetupError as err:
            logger.warning(
                "cloud setup failed for %s node_id=%s — removing VM: %s",
                node.hostname,
                node.node_id,
                err,
            )
            try:
                await self.machine_repository.disconnect(node.node_id)
            except Exception as disc_err:
                logger.warning(
                    "cloud disconnect failed: node_id=%s err=%s",
                    node.node_id,
                    disc_err,
                )
            await adapter.delete_node(cfg=config, external_id=node.external_id)  # type: ignore[arg-type]
            raise
        except Exception as err:
            logger.warning(
                "cloud setup failed for %s node_id=%s — removing VM: %s",
                node.hostname,
                node.node_id,
                err,
            )
            try:
                await self.machine_repository.disconnect(node.node_id)
            except Exception as disc_err:
                logger.warning(
                    "cloud disconnect failed: node_id=%s err=%s",
                    node.node_id,
                    disc_err,
                )
            await adapter.delete_node(cfg=config, external_id=node.external_id)  # type: ignore[arg-type]
            msg = f"Setup node error: {err}"
            raise CloudSetupError(msg) from err
        # endregion BLOCK_setup_vm

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

    # endregion METHOD_allocate

    # region METHOD_deallocate
    # PURPOSE: Tear down a cloud VM by provider so billing stops and the node slot is freed for reallocation.
    # REQUIRES: node.cloud is set and corresponds to a known provider with config.
    # ENSURES: No-ops (warn+return) when node.cloud is None, provider has no adapter, or provider has no config.
    async def deallocate(self, node: Node) -> None:
        """Delete VM via named provider's SDK (no DB access)."""
        # region BLOCK_resolve_deallocate_provider
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
        # endregion BLOCK_resolve_deallocate_provider

        # region BLOCK_delete_vm
        await adapter.delete_node(cfg=config, external_id=node.external_id)  # type: ignore[arg-type]
        logger.debug(
            "DONE",
            extra={
                "hostname": node.hostname,
                "cloud": node.cloud,
                "node_id": node.node_id,
            },
        )
        # endregion BLOCK_delete_vm

    # endregion METHOD_deallocate

    # ---- Private helpers ----

    def _is_platform_supported(self, adapter: CloudAdapter, platform: str) -> bool:
        """Check if adapter supports the given platform."""
        return any(check(platform) for check in adapter.supported_platform_checks)

    # region METHOD__get_ssh_key
    # PURPOSE: Load or generate an SSH key safely across concurrent allocations so cloud VM creation never fails on missing credentials.
    # ENSURES: Loads or generates SSH key file.
    async def _get_ssh_key(self) -> SSHKey:
        """Async-thread-safe SSH key load/generate."""
        async with self.ssh_key_lock:
            return await asyncio.get_running_loop().run_in_executor(
                None,
                get_or_create_ssh_key,
                self.local_config.keys_dir,
            )

    # endregion METHOD__get_ssh_key

    # region METHOD__get_cloud_config_data
    # PURPOSE: Assemble cloud-init data with engine packages matching the adapter's platforms so the VM boots ready for the scheduler's workload.
    # ENSURES: package_upgrade flag is sourced from config.package_upgrade (per-provider DTO field).
    async def _get_cloud_config_data(
        self,
        adapter: CloudAdapter,
        config: ConfigCloud,
    ) -> CloudInitConfig:
        """Build cloud-config with engine packages for this adapter's platforms."""
        # region BLOCK_filter_engines
        supported_engines = self.engines.filter(
            lambda e: (
                (
                    bool(e.platforms)
                    and any(
                        self._is_platform_supported(adapter, p) for p in e.platforms
                    )
                )
                or not e.platforms
            ),
        )
        pkgs = supported_engines.get_platform_packages()
        # endregion BLOCK_filter_engines
        return CloudInitConfig(
            package_upgrade=config.package_upgrade,
            packages=pkgs,
        )

    # endregion METHOD__get_cloud_config_data

    # region METHOD__setup_vm
    # PURPOSE: Wait for cloud-init (if the provider needs it), install engines, and stamp the Node enabled so a freshly-created VM becomes a functional compute node ready for job execution.
    # REQUIRES: node has hostname/username set; adapter has timeout settings.
    # ENSURES: Connects to VM, runs cloud-init (if needed), installs engines, stamps enabled=True.
    # RAISES: CloudSetupError on any SSH/cloud-init/setup failure.
    async def _setup_vm(
        self,
        node: Node,
        adapter: CloudAdapter,
        config: ConfigCloud,
    ) -> Node:
        """Connect to VM, wait for cloud-init (if needed), install engines, return enabled Node via replace."""
        # region BLOCK_ssh_connect_setup
        session = await self._connect_to_vm(node, adapter, config)
        # endregion BLOCK_ssh_connect_setup

        # region BLOCK_cloud_init
        if adapter.needs_cloud_init:
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
            except asyncio.TimeoutError as err:
                msg = (
                    f"cloud-init status --wait timed out on {node.hostname} "
                    f"after {adapter.create_node_timeout}s"
                )
                raise CloudSetupError(msg) from err
            except Exception as err:
                msg = f"cloud-init status --wait failed on {node.hostname}: {err}"
                raise CloudSetupError(msg) from err
            if result.exit_code != 0:
                msg = (
                    f"cloud-init failed on {node.hostname}: exit={result.exit_code} "
                    f"stdout={result.stdout} stderr={result.stderr}"
                )
                raise CloudSetupError(msg)
        # endregion BLOCK_cloud_init

        # region BLOCK_setup_node
        logger.debug("SETUP_NODE", extra={"hostname": node.hostname})
        try:
            await session.setup_node(self.engines)
        except Exception as err:
            msg = f"Setup node {node.hostname} failed: {err}"
            raise CloudSetupError(msg) from err
        # endregion BLOCK_setup_node

        logger.debug(
            "READY",
            extra={"hostname": node.hostname, "node_id": node.node_id},
        )
        return replace(node, enabled=True)

    # endregion METHOD__setup_vm

    # region METHOD__connect_to_vm
    # PURPOSE: Establish SSH connectivity to the new VM so setup operations (cloud-init check, engine install) can proceed.
    # REQUIRES: node has hostname/username; adapter has timeout settings.
    # ENSURES: Opens SSH connection to VM (session registered under node.node_id).
    # RAISES: CloudSetupError if SSH connection fails.
    async def _connect_to_vm(
        self,
        node: Node,
        adapter: CloudAdapter,
        config: ConfigCloud,  # noqa:  ARG002 Unused method argument
    ) -> MachineSession:
        """Connect to VM via SSH gateway with retry-friendly error wrapping."""
        # region BLOCK_get_keys
        keys: Sequence[PurePath] = await asyncio.get_running_loop().run_in_executor(
            None,
            list_private_keys,
            self.local_config.keys_dir,
        )
        # endregion BLOCK_get_keys

        # region BLOCK_ssh_connect_vm
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
            msg = f"SSH connect to {node.hostname} failed: {err}"
            raise CloudSetupError(
                msg,
            ) from err
        # endregion BLOCK_ssh_connect_vm
        return session

    # endregion METHOD__connect_to_vm


# endregion CLASS_CloudProvisionerImpl
