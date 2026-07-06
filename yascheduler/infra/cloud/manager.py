# FILE: yascheduler/infra/cloud/manager.py
# VERSION: 2.17.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CloudProvisionerImpl — pure cloud-API adapter implementing CloudProvisioner port (create/delete VM, cloud-init, setup, SSH keys); no DB access.
#   SCOPE: CloudProvisionerImpl class implementing allocate(provider, node: Node)->Node (derives the identity via replace on the passed node after create_node, threads it through _setup_vm/_connect_to_vm, returns replace(node, enabled=True, ncpus); reuses node.node_id as node identity), deallocate(node: Node) (reads node.cloud/node.ip internally, no-ops on cloud is None), select_provider with provider selection via select_provider_pure, cloud-config building, cloud-init wait, and node setup via SSHMachineRepository + SSHMachineOperations.
#   DEPENDS: M-DOMAIN-PORTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-ENGINE, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CLOUD-PROVIDER-SELECTION, M-CLOUD-CONFIGS, M-CLOUD-INIT, M-CLOUD-SSH-KEYS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-KEYS, M-DOMAIN-SETTINGS
#   LINKS: M-CLOUD-PROVISIONER, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROVIDER-SELECTION, M-DOMAIN-EXCEPTIONS, M-SSH-KEYS, M-DOMAIN-ENGINE, M-CLOUD-INIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudAllocateError         # Cloud node allocation error (re-exported from domain.exceptions)
#   CloudSetupError            # Cloud node setup error (re-exported from domain.exceptions)
#   CloudProvisionerImpl       # Pure cloud-API adapter implementing CloudProvisioner port (no DB); allocate(provider, node: Node)->Node, deallocate(node: Node), select_provider
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.17.0 - cloud-port-node-arg: allocate/deallocate take node: Node; allocate derives identity via replace(node, ...) (no fresh Node); deallocate reads node.cloud/node.ip, no-ops on cloud is None.
#   PREVIOUS_CHANGE: v2.16.0 - simplify-cloud-connect-node-args: allocate constructs the identity Node once (after create_node) and threads it through _setup_vm/_connect_to_vm; the three Node constructions collapse to one (no ersatz Node). _setup_vm returns replace(node, enabled=True, ncpus); _connect_to_vm passes the Node straight to connect with no username/port args. Setup-failure except blocks call disconnect(node.node_id) before delete_node. Removed the `# FIXME: just use Node` comment; added `replace` to the dataclasses import.
# END_CHANGE_SUMMARY

"""Cloud provisioner implementation"""

from __future__ import annotations

import asyncio
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
    import logging
    from collections.abc import Sequence
    from pathlib import PurePath

    from asyncssh.public_key import SSHKey

    from yascheduler.domain import EngineRepository, LocalSettings, RemoteDefaults
    from yascheduler.infra import SSHMachineOperations, SSHMachineRepository

    from .adapters import CloudAdapter
    from .cloud_configs import ConfigCloud


# START_CONTRACT: CloudProvisionerImpl
#   PURPOSE: Cloud-API adapter implementing CloudProvisioner port (create/delete VM, cloud-init, setup, SSH keys); no DB access.
#   INPUTS: {
#     adapters: dict[str, CloudAdapter] - provider name to adapter,
#     configs: dict[str, ConfigCloud] - provider name to config,
#     machine_repository: SSHMachineRepository - SSH connection collection (connect/disconnect),
#     machine_operations: SSHMachineOperations - single-machine operations (setup_node, get_cpu_cores, run),
#     local_config: LocalSettings - local daemon config (keys),
#     remote_config: RemoteDefaults - remote machine defaults,
#     engines: EngineRepository - engine definitions for cloud-config,
#     log: logging.Logger - logger
#   }
#   OUTPUTS: { CloudProvisionerImpl - frozen instance }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-PORTS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROVIDER-SELECTION, M-DOMAIN-EXCEPTIONS
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
    machine_operations: SSHMachineOperations
    local_config: LocalSettings
    remote_config: RemoteDefaults
    engines: EngineRepository
    log: logging.Logger
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
        self.log.info("[CloudProvisionerImpl] stop — draining machine_repository")
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
            self.adapters, self.configs, platforms, current_counts, self.log
        )
        # END_BLOCK_PURE_SELECT

        if adapter is None:
            return None

        # START_BLOCK_THROTTLE_CHECK
        if adapter.get_op_semaphore().locked():
            self.log.debug(
                "[CloudProvisionerImpl][select_provider][THROTTLE] provider=%s",
                adapter.name,
            )
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
    #   LINKS: M-CLOUD-PROVISIONER, M-SSH-REPOSITORY, M-SSH-OPERATIONS
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
        self.log.debug(
            "[CloudProvisionerImpl][allocate][CREATE_VM] provider=%s",
            adapter.name,
        )
        try:
            ip_addr = await adapter.create_node(
                log=self.log,
                cfg=config,
                key=await self._get_ssh_key(),
                cloud_config=await self._get_cloud_config_data(adapter, config),
            )
        except Exception as err:
            self.log.error("[CloudProvisionerImpl][allocate][CREATE_FAILED] %s", err)
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
        node = replace(node, ip=ip_addr, cloud=adapter.name, username=config.username)
        try:
            node = await self._setup_vm(node, adapter, config)
        except CloudSetupError:
            self.log.warning(
                "[CloudProvisionerImpl][allocate][SETUP_FAILED] ip=%s node_id=%s - removing VM",
                node.ip,
                node.node_id,
            )
            try:
                await self.machine_repository.disconnect(node.node_id)
            except Exception as disc_err:
                self.log.warning(
                    "[CloudProvisionerImpl][allocate][DISCONNECT_FAILED] node_id=%s err=%s",
                    node.node_id,
                    disc_err,
                )
            await adapter.delete_node(log=self.log, cfg=config, host=node.ip)
            raise
        except Exception as err:
            self.log.warning(
                "[CloudProvisionerImpl][allocate][SETUP_FAILED] ip=%s node_id=%s - removing VM",
                node.ip,
                node.node_id,
            )
            try:
                await self.machine_repository.disconnect(node.node_id)
            except Exception as disc_err:
                self.log.warning(
                    "[CloudProvisionerImpl][allocate][DISCONNECT_FAILED] node_id=%s err=%s",
                    node.node_id,
                    disc_err,
                )
            await adapter.delete_node(log=self.log, cfg=config, host=node.ip)
            raise CloudSetupError(f"Setup node error: {err}") from err
        # END_BLOCK_SETUP_VM

        self.log.debug(
            "[CloudProvisionerImpl][allocate][DONE] ip=%s node_id=%s provider=%s ncpus=%d",
            node.ip,
            node.node_id,
            node.cloud,
            node.ncpus,
        )
        return node

    # START_CONTRACT: CloudProvisionerImpl.deallocate
    #   PURPOSE: Delete VM via named provider's SDK (no DB access).
    #   INPUTS: { node: Node - provider and host read from node.cloud/node.ip }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Deletes cloud VM. No-ops (warn+return) when node.cloud is None, provider has no adapter, or provider has no config.
    #   LINKS: M-CLOUD-PROVISIONER
    # END_CONTRACT: CloudProvisionerImpl.deallocate
    async def deallocate(self, node: Node) -> None:
        # START_BLOCK_RESOLVE_DEALLOCATE_PROVIDER
        if node.cloud is None:
            self.log.warning(
                "[CloudProvisionerImpl][deallocate][NO_CLOUD] node_id=%s",
                node.node_id,
            )
            return
        adapter = self.adapters.get(node.cloud)
        if adapter is None:
            self.log.warning(
                "[CloudProvisionerImpl][deallocate][UNSUPPORTED] ip=%s cloud=%s",
                node.ip,
                node.cloud,
            )
            return
        config = self.configs.get(node.cloud)
        if config is None:
            self.log.warning(
                "[CloudProvisionerImpl][deallocate][NO_CONFIG] ip=%s cloud=%s",
                node.ip,
                node.cloud,
            )
            return
        # END_BLOCK_RESOLVE_DEALLOCATE_PROVIDER

        # START_BLOCK_DELETE_VM
        await adapter.delete_node(log=self.log, cfg=config, host=node.ip)
        self.log.debug(
            "[CloudProvisionerImpl][deallocate][DONE] ip=%s cloud=%s node_id=%s",
            node.ip,
            node.cloud,
            node.node_id,
        )
        # END_BLOCK_DELETE_VM

    # ---- Private helpers ----

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
    #   PURPOSE: Bring a freshly-created VM to a usable state (cloud-init done, engines installed) and return the enabled Node with ncpus populated.
    #   INPUTS: {
    #     node: Node - session registers under node.node_id,
    #     adapter: CloudAdapter - provider adapter (for timeout settings),
    #     config: ConfigCloud - provider config (for jump host)
    #   }
    #   OUTPUTS: { Node - enabled=True, ncpus populated (via dataclasses.replace); the caller persists via uow.nodes.update }
    #   SIDE_EFFECTS: Connects to VM (session registers under node.node_id), runs cloud-init, installs engines.
    #   RAISES: CloudSetupError - on any SSH/cloud-init/setup failure
    #   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS
    # END_CONTRACT: CloudProvisionerImpl._setup_vm
    async def _setup_vm(
        self,
        node: Node,
        adapter: CloudAdapter,
        config: ConfigCloud,
    ) -> Node:
        """Connect to VM, wait for cloud-init, install engines, return enabled Node via replace."""
        # START_BLOCK_SSH_CONNECT_SETUP
        session = await self._connect_to_vm(node, adapter, config)
        # END_BLOCK_SSH_CONNECT_SETUP

        # START_BLOCK_CLOUD_INIT
        # `cloud-init status --wait` blocks until cloud-init finishes (or hangs).
        # Bound it with adapter.create_node_timeout so a hung cloud-init cannot
        # pin an allocator worker forever. The failure message includes both
        # stdout and stderr — cloud-init writes its status line to stdout, so
        # omitting stdout (the previous behavior) gave no clue why it failed.
        self.log.debug("[CloudProvisionerImpl][setup_vm][CLOUD_INIT] ip=%s", node.ip)
        try:
            result = await asyncio.wait_for(
                self.machine_operations.run(session, "cloud-init status --wait"),
                timeout=adapter.create_node_timeout,
            )
            if result.exit_code != 0:
                raise CloudSetupError(
                    f"cloud-init failed on {node.ip}: exit={result.exit_code} "
                    f"stdout={result.stdout} stderr={result.stderr}"
                )
        except asyncio.TimeoutError as err:
            raise CloudSetupError(
                f"cloud-init status --wait timed out on {node.ip} "
                f"after {adapter.create_node_timeout}s"
            ) from err
        except CloudSetupError:
            raise
        except Exception as err:
            raise CloudSetupError(
                f"cloud-init status --wait failed on {node.ip}: {err}"
            ) from err
        # END_BLOCK_CLOUD_INIT

        # START_BLOCK_SETUP_NODE
        self.log.debug("[CloudProvisionerImpl][setup_vm][SETUP_NODE] ip=%s", node.ip)
        try:
            await self.machine_operations.setup_node(session, self.engines)
        except Exception as err:
            raise CloudSetupError(f"Setup node {node.ip} failed: {err}") from err
        # END_BLOCK_SETUP_NODE

        # START_BLOCK_GET_CPUS
        try:
            ncpus = await self.machine_operations.get_cpu_cores(session)
        except Exception as err:
            raise CloudSetupError(f"Get CPU cores for {node.ip} failed: {err}") from err
        # END_BLOCK_GET_CPUS

        self.log.debug(
            "[CloudProvisionerImpl][setup_vm][READY] ip=%s node_id=%s ncpus=%d",
            node.ip,
            node.node_id,
            ncpus,
        )
        return replace(node, enabled=True, ncpus=ncpus)

    # START_CONTRACT: CloudProvisionerImpl._connect_to_vm
    #   PURPOSE: Connect to VM via SSH gateway (registering the session under node.node_id) with retry-friendly error wrapping.
    #   INPUTS: {
    #     node: Node - the identity object allocate constructed after create_node (carries node_id, ip, username, port, cloud); session registers under node.node_id,
    #     adapter: CloudAdapter - provider adapter (for timeout settings),
    #     config: ConfigCloud - provider config (for jump host)
    #   }
    #   OUTPUTS: { MachineSession - connected machine session instance }
    #   SIDE_EFFECTS: Opens SSH connection to VM (session registered under node.node_id).
    #   RAISES: CloudSetupError - if SSH connection fails
    #   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS
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
        self.log.debug(
            "[CloudProvisionerImpl][setup_vm][CONNECT] ip=%s node_id=%s username=%s",
            node.ip,
            node.node_id,
            node.username,
        )
        try:
            session = await self.machine_repository.connect(
                node=node,
                client_keys=keys,
                connect_timeout=adapter.create_node_conn_timeout,
                data_dir=self.remote_config.data_dir,
                engines_dir=self.remote_config.engines_dir,
                tasks_dir=self.remote_config.tasks_dir,
                jump_host=config.jump_host or None,
                jump_username=config.jump_username or None,
            )
        except Exception as err:
            raise CloudSetupError(f"SSH connect to {node.ip} failed: {err}") from err
        # END_BLOCK_SSH_CONNECT_VM
        return session
