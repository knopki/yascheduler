# FILE: yascheduler/clouds/upcloud.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: UpCloud server creation and deletion via API.
#   SCOPE: UpCloud create/delete node functions.
#   DEPENDS: M-CONFIG-CLOUD, M-CLOUD-PROTOCOLS, M-CLOUD-UTILS
#   LINKS: M-CLOUD-ADAPTERS, M-CONFIG-CLOUD
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
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Upcloud cloud methods"""

import asyncio
import logging
import time
from concurrent.futures.thread import ThreadPoolExecutor
from functools import cache
from typing import Optional, cast

from asyncssh.public_key import SSHKey
from upcloud_api import CloudManager, Server, Storage, login_user_block

from ..config import ConfigCloudUpcloud
from .protocols import PCloudConfig
from .utils import get_rnd_name

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
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudUpcloud - UpCloud config, key: SSHKey - SSH key, cloud_config: Optional[PCloudConfig] - optional cloud-config }
#   OUTPUTS: { str - public IP address of created server }
#   SIDE_EFFECTS: Creates UpCloud server and storage resources
#   LINKS: M-CLOUD-UPCLOUD
# END_CONTRACT: upcloud_create_node_sync
def upcloud_create_node_sync(
    log: logging.Logger,
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: Optional[PCloudConfig] = None,
) -> str:
    """Create node"""
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
    ip_addr = cast("Optional[str]", server.get_public_ip())
    assert ip_addr is not None
    log.info("CREATED %s", ip_addr)
    return ip_addr


# START_CONTRACT: upcloud_create_node
#   PURPOSE: Create UpCloud server asynchronously via thread pool executor
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudUpcloud - UpCloud config, key: SSHKey - SSH key, cloud_config: Optional[PCloudConfig] - optional cloud-config }
#   OUTPUTS: { str - public IP address of created server }
#   SIDE_EFFECTS: Creates UpCloud server via synchronous call in executor
#   LINKS: M-CLOUD-UPCLOUD, upcloud_create_node_sync
# END_CONTRACT: upcloud_create_node
async def upcloud_create_node(
    log: logging.Logger,
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: Optional[PCloudConfig] = None,
) -> str:
    """Create node"""
    return await asyncio.get_running_loop().run_in_executor(
        executor, upcloud_create_node_sync, log, cfg, key, cloud_config
    )


# START_CONTRACT: upcload_delete_node_sync
#   PURPOSE: Delete UpCloud server synchronously by host IP, waiting for stop and cleanup
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudUpcloud - UpCloud config, host: str - IP address of server to delete }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Stops and destroys UpCloud server and associated storage devices
#   LINKS: M-CLOUD-UPCLOUD
# END_CONTRACT: upcload_delete_node_sync
def upcload_delete_node_sync(
    log: logging.Logger,
    cfg: ConfigCloudUpcloud,
    host: str,
) -> None:
    """Delete node"""
    client = get_client(cfg)
    for server in client.get_servers():
        if server.get_public_ip() == host:
            server.stop()
            log.info("WAITING FOR STOP...")
            time.sleep(20)
            while True:
                try:
                    server.destroy()
                except Exception:
                    time.sleep(5)
                else:
                    break
            for storage in server.storage_devices:
                storage.destroy()
            log.info("DELETED %s", host)
            break
    else:
        log.info("NODE %s NOT DELETED AS UNKNOWN", host)


# START_CONTRACT: upcload_delete_node
#   PURPOSE: Delete UpCloud server asynchronously via thread pool executor
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudUpcloud - UpCloud config, host: str - IP address of server to delete }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Deletes UpCloud server via synchronous call in executor
#   LINKS: M-CLOUD-UPCLOUD, upcload_delete_node_sync
# END_CONTRACT: upcload_delete_node
async def upcload_delete_node(
    log: logging.Logger,
    cfg: ConfigCloudUpcloud,
    host: str,
):
    """Delete node"""
    return await asyncio.get_running_loop().run_in_executor(
        executor, upcload_delete_node_sync, log, cfg, host
    )
