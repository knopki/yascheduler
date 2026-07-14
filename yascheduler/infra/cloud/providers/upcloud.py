# FILE: yascheduler/infra/cloud/providers/upcloud.py
# VERSION: 1.9.0
#
# START_MODULE_CONTRACT
#   PURPOSE: UpCloud server creation and deletion via API.
#   SCOPE: UpCloud create/delete node functions.
#   DEPENDS: M-CLOUD-CONFIGS, M-CLOUD-PROTOCOLS, M-CLOUD-UTILS
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-CONFIGS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   get_client - Get cached UpCloud CloudManager client
#   upcloud_create_node_sync - Create UpCloud server (sync)
#   upcloud_create_node - Create UpCloud server (async, public entry point)
#   upcload_delete_node_sync - Delete UpCloud server (sync)
#   upcload_delete_node - Delete UpCloud server (async, public entry point)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - remove log parameter from function signatures; bind module-local logger = get_logger("M-CLOUD-UPCLOUD") at module top
#   PREVIOUS_CHANGE: v1.8.0 - Retype upcloud_create_node_sync and upcloud_create_node cloud_config params PCloudConfig | None → CloudInitConfig | None; TYPE_CHECKING import CloudInitConfig from yascheduler.infra.cloud facade.
# END_CHANGE_SUMMARY
#
"""Upcloud cloud methods"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures.thread import ThreadPoolExecutor
from functools import cache
from typing import TYPE_CHECKING, cast

try:
    from upcloud_api import CloudManager, Server, Storage, login_user_block

    _UPCLOUD_AVAILABLE = True
except ImportError:
    _UPCLOUD_AVAILABLE = False

from yascheduler.infra.cloud import get_rnd_name
from yascheduler.shared import get_logger

logger = get_logger("M-CLOUD-PROVIDER-UPCLOUD")

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey

    from yascheduler.infra.cloud import CloudInitConfig, ConfigCloudUpcloud

executor = ThreadPoolExecutor(max_workers=5)


# START_CONTRACT: get_client
#   PURPOSE: Get cached UpCloud CloudManager client with authentication
#   INPUTS: { cfg: ConfigCloudUpcloud - UpCloud config with login credentials }
#   OUTPUTS: { CloudManager - authenticated UpCloud API client }
#   SIDE_EFFECTS: Authenticates with UpCloud API on first call
#   LINKS: M-CLOUD-UPCLOUD
# END_CONTRACT: get_client
@cache
def get_client(cfg: ConfigCloudUpcloud) -> CloudManager:
    """Get Upcloud client"""
    client = CloudManager(cfg.login, cfg.password)
    client.authenticate()
    return client


# START_CONTRACT: upcloud_create_node_sync
#   PURPOSE: Create UpCloud server synchronously with SSH key and cloud-config
#   INPUTS: { cfg: ConfigCloudUpcloud - UpCloud config, key: SSHKey - SSH key, cloud_config: Optional[CloudInitConfig] - optional cloud-init user-data renderer }
#   OUTPUTS: { str - public IP address of created server }
#   SIDE_EFFECTS: Creates UpCloud server and storage resources
#   LINKS: M-CLOUD-UPCLOUD
# END_CONTRACT: upcloud_create_node_sync
def upcloud_create_node_sync(
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> str:
    """Create node"""
    if not _UPCLOUD_AVAILABLE:
        raise ImportError("UpCloud SDK not installed. Install upcloud-api package.")
    client = get_client(cfg)

    login_user = login_user_block(
        username=cfg.username,
        ssh_keys=[key.export_public_key("openssh").decode("utf-8")],
        create_password=False,
    )
    server = client.create_server(
        Server(
            core_number=8,
            memory_amount=4096,
            hostname=get_rnd_name("node"),
            zone="uk-lon1",
            storage_devices=[Storage(os="Debian 10.0", size=40)],
            login_user=login_user,
            user_data=cloud_config.render() if cloud_config else None,
        )
    )
    ip_addr = cast("str | None", server.get_public_ip())
    assert ip_addr is not None
    logger.info("CREATED %s", ip_addr)
    return ip_addr


# START_CONTRACT: upcloud_create_node
#   PURPOSE: Create UpCloud server asynchronously via thread pool executor
#   INPUTS: { cfg: ConfigCloudUpcloud - UpCloud config, key: SSHKey - SSH key, cloud_config: Optional[CloudInitConfig] - optional cloud-init user-data renderer }
#   OUTPUTS: { str - public IP address of created server }
#   SIDE_EFFECTS: Creates UpCloud server via synchronous call in executor
#   LINKS: M-CLOUD-UPCLOUD, upcloud_create_node_sync
# END_CONTRACT: upcloud_create_node
async def upcloud_create_node(
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> str:
    """Create node"""
    if not _UPCLOUD_AVAILABLE:
        raise ImportError("UpCloud SDK not installed. Install upcloud-api package.")
    return await asyncio.get_running_loop().run_in_executor(
        executor, upcloud_create_node_sync, cfg, key, cloud_config
    )


# START_CONTRACT: upcload_delete_node_sync
#   PURPOSE: Delete UpCloud server synchronously by host IP, waiting for stop and cleanup
#   INPUTS: { cfg: ConfigCloudUpcloud - UpCloud config, host: str - IP address of server to delete }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Stops and destroys UpCloud server and associated storage devices
#   LINKS: M-CLOUD-UPCLOUD
# END_CONTRACT: upcload_delete_node_sync
def upcload_delete_node_sync(
    cfg: ConfigCloudUpcloud,
    host: str,
) -> None:
    """Delete node"""
    if not _UPCLOUD_AVAILABLE:
        raise ImportError("UpCloud SDK not installed. Install upcloud-api package.")
    client = get_client(cfg)
    for server in client.get_servers():
        if server.get_public_ip() == host:
            server.stop()
            logger.info("WAITING FOR STOP...")
            time.sleep(20)
            while True:
                try:
                    server.destroy()
                except Exception:
                    time.sleep(5)
                else:
                    break
            for storage in server.storage_devices:  # type: ignore[attr-defined]
                storage.destroy()
            logger.info("DELETED %s", host)
            break
    else:
        logger.info("NODE %s NOT DELETED AS UNKNOWN", host)


# START_CONTRACT: upcload_delete_node
#   PURPOSE: Delete UpCloud server asynchronously via thread pool executor
#   INPUTS: { cfg: ConfigCloudUpcloud - UpCloud config, host: str - IP address of server to delete }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Deletes UpCloud server via synchronous call in executor
#   LINKS: M-CLOUD-UPCLOUD, upcload_delete_node_sync
# END_CONTRACT: upcload_delete_node
async def upcload_delete_node(
    cfg: ConfigCloudUpcloud,
    host: str,
) -> None:
    """Delete node"""
    if not _UPCLOUD_AVAILABLE:
        raise ImportError("UpCloud SDK not installed. Install upcloud-api package.")
    return await asyncio.get_running_loop().run_in_executor(
        executor, upcload_delete_node_sync, cfg, host
    )
