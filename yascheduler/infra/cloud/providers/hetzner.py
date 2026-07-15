"""Hetzner cloud methods."""
# FILE: yascheduler/infra/cloud/providers/hetzner.py
# VERSION: 1.10.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Hetzner Cloud server creation and deletion via API.
#   SCOPE: Hetzner create/delete node functions.
#   DEPENDS: M-CLOUD-CONFIGS, M-CLOUD-PROTOCOLS, M-CLOUD-UTILS
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-CONFIGS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   get_client - Get cached Hetzner API client
#   get_ssh_key_id - Get or create Hetzner SSH key ID
#   hetzner_create_node - Create Hetzner server (public entry point)
#   find_srv - Find server by IP address
#   hetzner_delete_node - Delete Hetzner server (public entry point)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.10.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v1.9.0 - remove log parameter from function signatures; bind module-local logger = get_logger("M-CLOUD-HETZNER") at module top
# END_CHANGE_SUMMARY
#

from __future__ import annotations

import asyncio
import logging
from concurrent.futures.thread import ThreadPoolExecutor
from functools import cache, partial
from typing import TYPE_CHECKING, cast

try:
    from hcloud import APIException
    from hcloud import Client as HClient
    from hcloud.images.domain import Image
    from hcloud.locations.domain import Location
    from hcloud.server_types.domain import ServerType
    from hcloud.ssh_keys.domain import SSHKey as HSSHKey

    _HETZNER_AVAILABLE = True
except ImportError:
    _HETZNER_AVAILABLE = False

from yascheduler.infra.cloud import get_key_name, get_rnd_name

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey as ASSHKey
    from hcloud.servers.client import BoundServer

    from yascheduler.infra.cloud import CloudInitConfig, ConfigCloudHetzner

executor = ThreadPoolExecutor(max_workers=5)


# START_CONTRACT: get_client
#   PURPOSE: Get cached Hetzner API client for given config
#   INPUTS: { cfg: ConfigCloudHetzner - Hetzner cloud config with API token }
#   OUTPUTS: { HClient - Hetzner API client instance }
#   SIDE_EFFECTS: None - uses cache
#   LINKS: M-CLOUD-HETZNER
# END_CONTRACT: get_client
@cache
def get_client(cfg: ConfigCloudHetzner) -> HClient:
    """Get Hetzner client."""
    return HClient(cfg.token)


# START_CONTRACT: get_ssh_key_id
#   PURPOSE: Get or create Hetzner SSH key ID from local SSH key
#   INPUTS: { client: HClient - Hetzner API client, key: ASSHKey - local SSH key }
#   OUTPUTS: { int - Hetzner SSH key ID }
#   SIDE_EFFECTS: Creates new SSH key in Hetzner project if not exists
#   LINKS: M-CLOUD-HETZNER
# END_CONTRACT: get_ssh_key_id
@cache
def get_ssh_key_id(client: HClient, key: ASSHKey) -> int:
    """Get Hetzner ssh id."""
    key_name = get_key_name(key)
    pub_key = key.export_public_key("openssh").decode("utf-8")

    try:
        hkey = client.ssh_keys.create(name=key_name, public_key=pub_key)
        return cast("int", hkey.id)
    except APIException as err:
        # Hetzner signals a duplicate key with code `uniqueness_error` (newer
        # API wording "SSH key not unique"); older wording contained "already".
        if err.code == "uniqueness_error" or "already" in str(err):
            hkey = client.ssh_keys.get_by_fingerprint(
                key.get_fingerprint("md5").split(":", maxsplit=1)[1],
            ) or client.ssh_keys.get_by_name(key_name)
            if hkey:
                return cast("int", hkey.id)
            prefix = "yakey"
            name_len = len(get_rnd_name(prefix))
            for hkey in client.ssh_keys.get_all():
                if (
                    cast("str", hkey.name).startswith(prefix)
                    and len(cast("str", hkey.name)) == name_len
                ):
                    return cast("int", hkey.id)
        raise


# START_CONTRACT: hetzner_create_node
#   PURPOSE: Create Hetzner server with SSH key and cloud-config
#   INPUTS: { cfg: ConfigCloudHetzner - Hetzner config, key: ASSHKey - SSH key, cloud_config: Optional[CloudInitConfig] - optional cloud-init user-data renderer }
#   OUTPUTS: { str - IP address of created server }
#   SIDE_EFFECTS: Creates Hetzner Cloud server with associated resources
#   LINKS: M-CLOUD-HETZNER
# END_CONTRACT: hetzner_create_node
async def hetzner_create_node(
    cfg: ConfigCloudHetzner,
    key: ASSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> str:
    """Create node."""
    if not _HETZNER_AVAILABLE:
        msg = "Hetzner SDK not installed. Install hcloud package."
        raise ImportError(msg)
    loop = asyncio.get_running_loop()
    client = await loop.run_in_executor(executor, get_client, cfg)
    ssh_key_id = await loop.run_in_executor(executor, get_ssh_key_id, client, key)

    create_server = partial(
        client.servers.create,
        name=get_rnd_name("node"),
        server_type=ServerType(name=cfg.server_type),
        image=Image(name=cfg.image_name),
        location=Location(name=cfg.location) if cfg.location else None,
        ssh_keys=[HSSHKey(id=ssh_key_id, name=get_key_name(key))],
        user_data=cloud_config.render() if cloud_config else None,
    )
    response = await loop.run_in_executor(executor, create_server)
    server = response.server
    ip_addr = server.public_net and server.public_net.ipv4 and server.public_net.ipv4.ip
    assert ip_addr
    ip_str = str(ip_addr)
    logger.info("CREATED %s", ip_str)
    return ip_str


# START_CONTRACT: find_srv
#   PURPOSE: Find Hetzner BoundServer by public IP address
#   INPUTS: { client: HClient - Hetzner API client, host: str - IP address to search for }
#   OUTPUTS: { Optional[BoundServer] - server if found, None otherwise }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-HETZNER
# END_CONTRACT: find_srv
def find_srv(client: HClient, host: str) -> BoundServer | None:
    """Find BoundServer by IP addr."""
    for server in client.servers.get_all():
        if (
            server.public_net and server.public_net.ipv4 and server.public_net.ipv4.ip
        ) == host and server.id:
            return client.servers.get_by_id(server.id)
    return None


# START_CONTRACT: hetzner_delete_node
#   PURPOSE: Delete Hetzner server by host IP address
#   INPUTS: { cfg: ConfigCloudHetzner - Hetzner config, host: str - IP address of server to delete }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Deletes Hetzner Cloud server
#   LINKS: M-CLOUD-HETZNER, find_srv
# END_CONTRACT: hetzner_delete_node
async def hetzner_delete_node(
    cfg: ConfigCloudHetzner,
    host: str,
) -> None:
    """Delete node."""
    if not _HETZNER_AVAILABLE:
        msg = "Hetzner SDK not installed. Install hcloud package."
        raise ImportError(msg)
    loop = asyncio.get_running_loop()
    client = await loop.run_in_executor(executor, get_client, cfg)
    server = await loop.run_in_executor(executor, find_srv, client, host)

    if server:
        await loop.run_in_executor(executor, server.delete)
        logger.info("DELETED %s", host)

    else:
        logger.info("NODE %s NOT DELETED AS UNKNOWN", host)
