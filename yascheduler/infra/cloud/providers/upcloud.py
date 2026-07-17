"""Upcloud cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission UpCloud servers so the scheduler can run compute workloads on UpCloud through the generic CloudAdapter contract.
# SCOPE: UpCloud create/delete node functions.
# DEPENDENCIES: USES API: upcloud-api (CloudManager SDK); WRITES: HTTP to UpCloud API (server create/delete/destroy)
# KEYWORDS: upcloud, server, create, delete, api, ssh key, cloud manager
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures.thread import ThreadPoolExecutor
from functools import cache
from typing import TYPE_CHECKING, cast

try:
    from upcloud_api import CloudManager, Server, Storage, login_user_block

    _UPCLOUD_AVAILABLE = True
except ImportError:
    _UPCLOUD_AVAILABLE = False

from yascheduler.infra.cloud import CloudCreateNodeDTO, get_rnd_name

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey

    from yascheduler.infra.cloud import CloudInitConfig, ConfigCloudUpcloud

__all__ = ["upcloud_create_node", "upcloud_delete_node"]

executor = ThreadPoolExecutor(max_workers=5)


# region FUNC_get_client
# PURPOSE: Reuse an authenticated UpCloud client across calls so repeated server operations do not re-authenticate.
@cache
def get_client(cfg: ConfigCloudUpcloud) -> CloudManager:
    """Get Upcloud client."""
    client = CloudManager(cfg.login, cfg.password)
    client.authenticate()
    return client


# endregion FUNC_get_client


# region FUNC_upcloud_create_node_sync
# PURPOSE: Provision an UpCloud server with SSH key and cloud-config so the VM is ready for scheduler use immediately after creation.
def upcloud_create_node_sync(
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create node."""
    if not _UPCLOUD_AVAILABLE:
        msg = "UpCloud SDK not installed. Install upcloud-api package."
        raise ImportError(msg)
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
        ),
    )
    ip_addr = cast("str | None", server.get_public_ip())
    assert ip_addr is not None
    logger.info("CREATED %s", ip_addr)
    return CloudCreateNodeDTO(
        external_id=ip_addr,
        hostname=ip_addr,
        username=cfg.username,
        jump_host=cfg.jump_host,
        jump_port=cfg.jump_port,
        jump_username=cfg.jump_username or "root",
    )


# endregion FUNC_upcloud_create_node_sync


# region FUNC_upcloud_create_node
# PURPOSE: Offload synchronous UpCloud server creation to a thread so the async caller does not block the event loop.
async def upcloud_create_node(
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create node."""
    if not _UPCLOUD_AVAILABLE:
        msg = "UpCloud SDK not installed. Install upcloud-api package."
        raise ImportError(msg)
    return await asyncio.get_running_loop().run_in_executor(
        executor,
        upcloud_create_node_sync,
        cfg,
        key,
        cloud_config,
    )


# endregion FUNC_upcloud_create_node


# region FUNC_upcloud_delete_node_sync
# PURPOSE: Tear down an UpCloud server by IP (stop, destroy server, clean up storage) so billing stops and no orphaned storage accrues costs.
def upcloud_delete_node_sync(
    cfg: ConfigCloudUpcloud,
    external_id: str,
) -> None:
    """Delete node."""
    if not _UPCLOUD_AVAILABLE:
        msg = "UpCloud SDK not installed. Install upcloud-api package."
        raise ImportError(msg)
    client = get_client(cfg)
    for server in client.get_servers():
        if server.get_public_ip() == external_id:
            server.stop()
            logger.info("WAITING FOR STOP...")
            time.sleep(20)
            while True:
                try:
                    server.destroy()
                except Exception:  # noqa: PERF203
                    time.sleep(5)
                else:
                    break
            for storage in server.storage_devices:  # type: ignore[attr-defined]
                storage.destroy()
            logger.info("DELETED %s", external_id)
            break
    else:
        logger.info("NODE %s NOT DELETED AS UNKNOWN", external_id)


# endregion FUNC_upcloud_delete_node_sync


# region FUNC_upcloud_delete_node
# PURPOSE: Offload synchronous UpCloud server deletion to a thread so the async caller does not block the event loop.
async def upcloud_delete_node(
    cfg: ConfigCloudUpcloud,
    external_id: str,
) -> None:
    """Delete node."""
    if not _UPCLOUD_AVAILABLE:
        msg = "UpCloud SDK not installed. Install upcloud-api package."
        raise ImportError(msg)
    return await asyncio.get_running_loop().run_in_executor(
        executor,
        upcloud_delete_node_sync,
        cfg,
        external_id,
    )


# endregion FUNC_upcloud_delete_node
