"""Hetzner cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission Hetzner Cloud servers so the scheduler can run compute workloads on Hetzner through the generic CloudAdapter contract.
# SCOPE: Hetzner create/delete node functions.
# DEPENDENCIES: USES API: hcloud (Hetzner Cloud SDK); WRITES: HTTP to Hetzner API (server/SSH key create/delete)
# KEYWORDS: hetzner, cloud, server, create, delete, api, ssh key
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from concurrent.futures.thread import ThreadPoolExecutor
from functools import cache, partial
from typing import TYPE_CHECKING, cast

from hcloud import APIException
from hcloud import Client as HClient
from hcloud.images.domain import Image
from hcloud.locations.domain import Location
from hcloud.server_types.domain import ServerType
from hcloud.ssh_keys.domain import SSHKey as HSSHKey

from yascheduler.infra.cloud import CloudCreateNodeDTO, get_key_name, get_rnd_name

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey as ASSHKey

    from yascheduler.infra.cloud import CloudInitConfig, ConfigCloudHetzner

__all__ = ["hetzner_create_node", "hetzner_delete_node"]

executor = ThreadPoolExecutor(max_workers=5)


# region FUNC_get_client
# PURPOSE: Reuse an authenticated Hetzner API client across calls so repeated server create/delete does not re-authenticate on every operation.
@cache
def get_client(cfg: ConfigCloudHetzner) -> HClient:
    """Get Hetzner client."""
    return HClient(cfg.token)


# endregion FUNC_get_client


# region FUNC_get_ssh_key_id
# PURPOSE: Register the local SSH key with the Hetzner project (or find its existing ID) so the server receives the right key on creation and duplicates are handled gracefully.
# ENSURES: Creates new SSH key in Hetzner project if not exists; deduplicates on uniqueness error.
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


# endregion FUNC_get_ssh_key_id


# region FUNC_hetzner_create_node
# PURPOSE: Provision a Hetzner server via the CloudAdapter interface so the generic provisioner can launch Hetzner compute nodes.
async def hetzner_create_node(
    cfg: ConfigCloudHetzner,
    key: ASSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create node."""
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
    return CloudCreateNodeDTO(
        external_id=str(server.id),
        hostname=ip_str,
        username=cfg.username,
        jump_host=cfg.jump_host,
        jump_port=cfg.jump_port,
        jump_username=cfg.jump_username or "root",
    )


# endregion FUNC_hetzner_create_node


# region FUNC_hetzner_delete_node
# PURPOSE: Tear down a Hetzner server by server ID so billing stops and the node slot is freed for reallocation.
# INVARIANTS:
# - Resolves via client.servers.get_by_id(int(external_id))
# - APIException(code="not_found") is logged and returns without error
async def hetzner_delete_node(
    cfg: ConfigCloudHetzner,
    external_id: str,
) -> None:
    """Delete node."""
    loop = asyncio.get_running_loop()
    client = await loop.run_in_executor(executor, get_client, cfg)

    try:
        server = await loop.run_in_executor(
            executor,
            client.servers.get_by_id,
            int(external_id),
        )
    except (ValueError, APIException) as err:
        if isinstance(err, APIException) and err.code == "not_found":
            logger.warning("NODE %s NOT DELETED AS UNKNOWN", external_id)
            return
        raise

    if server:
        await loop.run_in_executor(executor, server.delete)
        logger.info("DELETED %s", external_id)
    else:
        logger.warning("NODE %s NOT DELETED AS UNKNOWN", external_id)


# endregion FUNC_hetzner_delete_node
