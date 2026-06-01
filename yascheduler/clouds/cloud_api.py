# FILE: yascheduler/clouds/cloud_api.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Generic cloud provider interface: node creation, deletion, SSH key management.
#   SCOPE: CloudAPI generic class, CloudConfig renderer, CloudCreateNodeError, CloudSetupNodeError.
#   DEPENDS: M-CLOUD-PROTOCOLS, M-CLOUD-ADAPTERS, M-CONFIG, M-REMOTE, M-CLOUD-UTILS, M-REMOTE-PROTOCOL
#   LINKS: M-CLOUD-MANAGER, M-REMOTE, M-CLOUD-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudCreateNodeError - Cloud node allocation error
#   CloudSetupNodeError - Cloud node setup error
#   CloudConfig - Cloud config data class; renders user-data (cloud-config) format
#   CloudAPI - Generic cloud provider; creates/deletes nodes, manages SSH keys, builds cloud-config
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Cloud API module"""

import asyncio
import base64
import json
import logging
from functools import cache
from typing import Generic, Union

import backoff
from asyncssh.process import ProcessError
from asyncssh.public_key import SSHKey, generate_private_key, read_private_key
from attrs import asdict, define, field

from ..config import ConfigLocal, ConfigRemote, EngineRepository
from ..remote_machine import RemoteMachine, SSHRetryExc
from .adapters import CloudAdapter
from .protocols import PCloudConfig, TConfigCloud_inv
from .utils import get_rnd_name


class CloudCreateNodeError(Exception):
    """Cloud node allocation error"""


class CloudSetupNodeError(Exception):
    """Cloud node setup error"""


@define(frozen=True)
class CloudConfig(PCloudConfig):
    "Cloud config init"

    bootcmd: tuple[Union[str, list[str]], ...] = field(factory=tuple)
    package_upgrade: bool = field(default=False)
    packages: list[str] = field(factory=list)

    def render(self) -> str:
        "Render to user-data format"
        return "#cloud-config\n" + json.dumps(asdict(self))

    def render_base64(self) -> str:
        "Render to user-data format as base64 string"
        return base64.b64encode(self.render().encode()).decode()


@define(frozen=True)
class CloudAPI(Generic[TConfigCloud_inv]):
    "Cloud API protocol"

    adapter: CloudAdapter[TConfigCloud_inv] = field()
    config: TConfigCloud_inv = field()
    local_config: ConfigLocal = field()
    remote_config: ConfigRemote = field()
    engines: EngineRepository = field()
    log: logging.Logger = field()
    ssh_key_lock: asyncio.Lock = field(factory=asyncio.Lock)

    def __attrs_post_init__(self) -> None:
        if self.log:
            object.__setattr__(self, "log", self.log.getChild(self.adapter.name))
        else:
            object.__setattr__(self, "log", logging.getLogger(self.adapter.name))

    @property
    def name(self) -> str:
        "Cloud name"
        return self.adapter.name

    # START_CONTRACT: get_op_semaphore
    #   PURPOSE: Return cached semaphore for limiting concurrent cloud operations
    #   INPUTS: { None }
    #   OUTPUTS: { asyncio.Semaphore - semaphore for operation rate limiting }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-API
    # END_CONTRACT: get_op_semaphore
    @cache
    def get_op_semaphore(self) -> asyncio.Semaphore:
        """
        Cached semaphore getter.
        It's because you cannot create async semaphore outside the loop.
        "attached to a different loop" error.
        """
        return self.adapter.get_op_semaphore()

    # START_CONTRACT: is_platform_supported
    #   PURPOSE: Check if given platform string is supported by this cloud
    #   INPUTS: { platform: str - platform identifier string }
    #   OUTPUTS: { bool - True if platform is supported }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-API
    # END_CONTRACT: is_platform_supported
    def is_platform_supported(self, platform: str) -> bool:
        "Is platform is supported by cloud?"
        return any(map(lambda x: x(platform), self.adapter.supported_platform_checks))

    # START_CONTRACT: get_ssh_key_sync
    #   PURPOSE: Load existing or generate new SSH key for cloud node access
    #   INPUTS: { None }
    #   OUTPUTS: { SSHKey - loaded or newly generated SSH key }
    #   SIDE_EFFECTS: Generates and writes new SSH key file to disk if none exists
    #   LINKS: M-CLOUD-API, M-REMOTE
    # END_CONTRACT: get_ssh_key_sync
    def get_ssh_key_sync(self) -> SSHKey:
        "Load or generate new SSHKey"
        prefix = "yakey"
        # try to load
        for filepath in self.local_config.keys_dir.iterdir():
            if not filepath.name.startswith(prefix) or not filepath.is_file():
                continue
            ssh_key = read_private_key(filepath)
            ssh_key.set_comment(filepath.name)
            self.log.debug(
                "[CloudAPI][get_ssh_key_sync] key=%s fingerprint=%s",
                filepath.name,
                ssh_key.get_fingerprint("md5"),
            )
            return ssh_key

        key_name = get_rnd_name(prefix)
        filepath = self.local_config.keys_dir / key_name
        ssh_key = generate_private_key(alg_name="ssh-rsa", comment=key_name)
        ssh_key.write_private_key(filepath)
        filepath.chmod(0o600)
        ssh_key.set_comment(key_name)
        self.log.info("WRITTEN KEY %s: %s", key_name, ssh_key.get_fingerprint("md5"))
        return ssh_key

    # START_CONTRACT: get_ssh_key
    #   PURPOSE: Async wrapper around get_ssh_key_sync with lock for thread safety
    #   INPUTS: { None }
    #   OUTPUTS: { SSHKey - loaded or generated SSH key }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-API, get_ssh_key_sync
    # END_CONTRACT: get_ssh_key
    async def get_ssh_key(self) -> SSHKey:
        "Load or generate ssh key (cached)"
        async with self.ssh_key_lock:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.get_ssh_key_sync
            )

    # START_CONTRACT: get_cloud_config_data
    #   PURPOSE: Build cloud-config with packages for engines on supported platforms
    #   INPUTS: { None }
    #   OUTPUTS: { PCloudConfig - cloud-config data with packages for supported engines }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-API, M-CONFIG-CLOUD
    # END_CONTRACT: get_cloud_config_data
    async def get_cloud_config_data(self) -> PCloudConfig:
        "Common cloud-config"
        engines = self.engines.filter(
            lambda e: (
                bool(e.platforms)
                and any(map(self.is_platform_supported, e.platforms))
                or not e.platforms
            )
        )
        pkgs = engines.get_platform_packages()
        return CloudConfig(package_upgrade=True, packages=pkgs)

    # START_CONTRACT: mk_machine
    #   PURPOSE: Connect to existing IP and create a RemoteMachine instance
    #   INPUTS: { ip_addr: str - IP address to connect to }
    #   OUTPUTS: { RemoteMachine - connected remote machine instance }
    #   SIDE_EFFECTS: Establishes SSH connection with retry backoff
    #   LINKS: M-CLOUD-API, M-REMOTE
    # END_CONTRACT: mk_machine
    async def mk_machine(self, ip_addr: str) -> RemoteMachine:
        "Create RemoteMachine"
        keys = await asyncio.get_running_loop().run_in_executor(
            None, self.local_config.get_private_keys
        )
        retry = backoff.on_exception(
            wait_gen=backoff.fibo,
            max_time=self.adapter.create_node_timeout,
            exception=SSHRetryExc,
        )
        return await retry(RemoteMachine.create)(
            host=ip_addr,
            username=self.config.username,
            client_keys=keys,
            logger=self.log,
            connect_timeout=self.adapter.create_node_conn_timeout,
            data_dir=self.remote_config.data_dir,
            engines_dir=self.remote_config.engines_dir,
            tasks_dir=self.remote_config.tasks_dir,
            jump_host=self.config.jump_host,
            jump_username=self.config.jump_username,
        )

    # START_CONTRACT: create_node
    #   PURPOSE: Create VM via adapter, wait for SSH readiness, setup node with engines
    #   INPUTS: { None }
    #   OUTPUTS: { str - IP address of the created node }
    #   SIDE_EFFECTS: Allocates cloud VM, transfers SSH keys, runs cloud-init, installs engines; cleans up on failure
    #   LINKS: M-CLOUD-API, M-REMOTE
    # END_CONTRACT: create_node
    async def create_node(self) -> str:
        "Create new node"
        async with self.adapter.get_op_semaphore():
            try:
                ip_addr = await self.adapter.create_node(
                    log=self.log,
                    cfg=self.config,
                    key=await self.get_ssh_key(),
                    cloud_config=await self.get_cloud_config_data(),
                )
            except Exception as err:
                raise CloudCreateNodeError(f"Create node error: {err}") from err

            try:
                machine = await self.mk_machine(ip_addr)
                await machine.run("cloud-init status --wait")
                await machine.setup_node(self.engines)
            except (ProcessError, Exception) as err:
                if isinstance(err, ProcessError):
                    self.log.error(
                        (
                            "Setup node %s failed: command '%s' failed with exit code %s; stderr: %s"
                        ),
                        ip_addr,
                        err.command,
                        err.returncode,
                        err.stderr,
                    )
                self.log.warning("Setup node %s failed - deallocate", ip_addr)
                await self.delete_node(ip_addr)
                raise CloudSetupNodeError(f"Setup node error: {err}") from err
            return ip_addr

    # START_CONTRACT: delete_node
    #   PURPOSE: Delete VM by host address via adapter
    #   INPUTS: { host: str - IP or hostname of VM to delete }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Terminates cloud VM, releases cloud resources
    #   LINKS: M-CLOUD-API
    # END_CONTRACT: delete_node
    async def delete_node(self, host: str) -> None:
        "Delete node"
        async with self.adapter.get_op_semaphore():
            return await self.adapter.delete_node(
                log=self.log, cfg=self.config, host=host
            )
