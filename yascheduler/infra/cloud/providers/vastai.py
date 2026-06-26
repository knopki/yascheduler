# FILE: yascheduler/infra/cloud/providers/vastai.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: VastAI GPU marketplace instance creation and deletion via REST API.
#   SCOPE: VastAI create/delete node functions.
#   DEPENDS: M-CLOUD-CONFIGS, M-CLOUD-PROTOCOLS
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-CONFIGS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   BASE_URL - VastAI API base URL
#   _get_headers - Build auth headers for VastAI API
#   _api_request - Make authenticated API request with error handling
#   _search_offers - Search available GPU offers matching criteria
#   _create_instance - Create VastAI instance from an offer
#   _get_instance_info - Get instance status/info by ID
#   _find_instance_by_ip - Find instance by public IP address
#   _delete_instance - Delete VastAI instance by ID
#   vastai_create_node - Create VastAI node (public entry point)
#   vastai_delete_node - Delete VastAI node by IP (public entry point)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - TYPE_CHECKING import ConfigCloudVastAI from yascheduler.infra.cloud facade (cloud-configs-to-infra-registry); the DTO relocated from yascheduler.config.cloud and the cloud subpackage facade is the canonical import path.
#   PREVIOUS_CHANGE: v1.6.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

"""VastAI cloud methods"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

try:
    import aiohttp

    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

if TYPE_CHECKING:
    import logging

    from asyncssh.public_key import SSHKey

    from yascheduler.infra.cloud import ConfigCloudVastAI, PCloudConfig

BASE_URL = "https://console.vast.ai/api/v0"


# START_CONTRACT: _get_headers
#   PURPOSE: Build authorization headers for VastAI API requests
#   INPUTS: { api_key: str - VastAI API key }
#   OUTPUTS: { dict[str, str] - headers with Bearer auth and JSON content type }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-VASTAI
# END_CONTRACT: _get_headers
def _get_headers(api_key: str) -> dict[str, str]:
    """Get headers for VastAI API requests"""
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


# START_CONTRACT: _api_request
#   PURPOSE: Execute authenticated HTTP request to VastAI API with error handling
#   INPUTS: { session: aiohttp.ClientSession - HTTP session, method: str - HTTP method, url: str - request URL, api_key: str - API key, **kwargs: Any - additional request params }
#   OUTPUTS: { dict[str, Any] - parsed JSON response }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-VASTAI
# END_CONTRACT: _api_request
async def _api_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    api_key: str,
    **kwargs: Any,  # noqa: ANN401
) -> dict[str, Any]:
    headers = _get_headers(api_key)
    timeout = aiohttp.ClientTimeout(total=30)

    async with session.request(
        method, url, headers=headers, timeout=timeout, **kwargs
    ) as resp:
        if not resp.ok:
            text = await resp.text()
            raise RuntimeError(f"VastAI API error: {resp.status} {resp.reason}: {text}")
        return await resp.json()


# START_CONTRACT: _search_offers
#   PURPOSE: Search VastAI marketplace for available GPU offers matching criteria
#   INPUTS: { session: aiohttp.ClientSession, api_key: str, min_vram_mb: int, num_gpus: int, max_price: float }
#   OUTPUTS: { list[dict[str, Any]] - available offers }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-VASTAI
# END_CONTRACT: _search_offers
async def _search_offers(
    session: aiohttp.ClientSession,
    api_key: str,
    min_vram_mb: int,
    num_gpus: int,
    max_price: float,
) -> list[dict[str, Any]]:
    query = {
        "gpu_ram": {"gte": min_vram_mb},
        "num_gpus": {"eq": num_gpus},
        "gpu_frac": {"gte": 1.0},
        "rentable": {"eq": True},
        "rented": {"eq": False},
        "dph_total": {"lte": max_price},
        "type": "on-demand",
        "order": [["dph_total", "asc"]],
        "limit": 20,
    }
    params = {"q": str(query)}
    data = await _api_request(
        session, "GET", f"{BASE_URL}/bundles/", api_key, params=params
    )
    return data.get("offers", [])


# START_CONTRACT: _create_instance
#   PURPOSE: Create a VastAI instance from a selected offer
#   INPUTS: { session, api_key, offer_id, image, disk_gb, onstart_script, docker_options, env }
#   OUTPUTS: { dict[str, Any] - creation response }
#   SIDE_EFFECTS: Creates cloud instance
#   LINKS: M-CLOUD-VASTAI
# END_CONTRACT: _create_instance
async def _create_instance(
    session: aiohttp.ClientSession,
    api_key: str,
    offer_id: int,
    image: str,
    disk_gb: int,
    onstart_script: str,
    docker_options: str,
    env: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "client_id": "me",
        "image": image,
        "disk": disk_gb,
        "onstart": onstart_script,
        "runtype": "ssh_direct",
        "docker_options": docker_options,
        "env": env,
        "force": False,
    }
    return await _api_request(
        session, "PUT", f"{BASE_URL}/asks/{offer_id}/", api_key, json=payload
    )


async def _get_instance_info(
    session: aiohttp.ClientSession, api_key: str, instance_id: int
) -> dict[str, Any]:
    data = await _api_request(
        session, "GET", f"{BASE_URL}/instances/{instance_id}/", api_key
    )
    inner = data.get("instances")
    if isinstance(inner, dict):
        return inner
    if isinstance(inner, list) and inner:
        return inner[0]
    return data


async def _find_instance_by_ip(
    session: aiohttp.ClientSession, api_key: str, host: str
) -> dict[str, Any] | None:
    data = await _api_request(session, "GET", f"{BASE_URL}/instances/", api_key)
    instances = data.get("instances", [])
    if isinstance(instances, dict):
        instances = [instances]
    for inst in instances:
        if inst.get("public_ipaddr") == host:
            return inst
    return None


async def _delete_instance(
    session: aiohttp.ClientSession, api_key: str, instance_id: int
) -> None:
    headers = _get_headers(api_key)
    timeout = aiohttp.ClientTimeout(total=30)
    url = f"{BASE_URL}/instances/{instance_id}/"

    async with session.delete(url, headers=headers, timeout=timeout) as resp:
        if not resp.ok:
            text = await resp.text()
            raise RuntimeError(
                f"VastAI API error deleting instance {instance_id}: "
                f"{resp.status} {resp.reason}: {text}"
            )


# START_CONTRACT: vastai_create_node
#   PURPOSE: Create VastAI instance from cheapest matching offer and wait for readiness
#   INPUTS: { log: logging.Logger, cfg: ConfigCloudVastAI, key: SSHKey, cloud_config: Optional[PCloudConfig] }
#   OUTPUTS: { str - IP address of the running instance }
#   SIDE_EFFECTS: Creates cloud instance; polls until running or timeout
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-VASTAI
# END_CONTRACT: vastai_create_node
async def vastai_create_node(
    log: logging.Logger,
    cfg: ConfigCloudVastAI,
    key: SSHKey,
    cloud_config: PCloudConfig | None = None,
) -> str:
    async with aiohttp.ClientSession() as session:
        log.info("Searching VastAI offers...")
        offers = await _search_offers(
            session, cfg.api_key, cfg.min_vram_mb, cfg.num_gpus, cfg.max_price_per_hr
        )
        if not offers:
            raise RuntimeError("No VastAI offers found matching criteria")

        offer = offers[0]
        offer_id = offer.get("id")
        if not isinstance(offer_id, int):
            raise RuntimeError("Offer missing required 'id' field")
        log.info(f"Creating instance from offer {offer_id}")

        result = await _create_instance(
            session,
            cfg.api_key,
            cast("int", offer_id),
            cfg.image,
            cfg.disk_gb,
            cfg.onstart_script,
            cfg.docker_options,
            cfg.env,
        )
        instance_id = result.get("new_contract")
        if not isinstance(instance_id, int):
            raise RuntimeError("Failed to create instance - no contract ID returned")
        instance_id = cast("int", instance_id)

        max_wait = 600  # 10 minutes
        poll_interval = 8
        for _ in range(max_wait // poll_interval):
            await asyncio.sleep(poll_interval)

            info = await _get_instance_info(session, cfg.api_key, instance_id)
            status = info.get("actual_status") or info.get("status")
            log.info(f"Instance {instance_id} status: {status}")

            if status == "running":
                ip_addr = info.get("public_ipaddr")
                if ip_addr:
                    log.info(f"Instance running at {ip_addr}")
                    return ip_addr
                log.warning("Instance running but no public IP address yet")

        raise TimeoutError(
            f"Instance {instance_id} did not become ready within {max_wait} seconds"
        )


# START_CONTRACT: vastai_delete_node
#   PURPOSE: Delete VastAI instance by its IP address
#   INPUTS: { log: logging.Logger, cfg: ConfigCloudVastAI, host: str }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Deletes cloud instance
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-VASTAI
# END_CONTRACT: vastai_delete_node
async def vastai_delete_node(
    log: logging.Logger,
    cfg: ConfigCloudVastAI,
    host: str,
) -> None:
    async with aiohttp.ClientSession() as session:
        inst = await _find_instance_by_ip(session, cfg.api_key, host)
        if inst:
            instance_id = inst.get("id")
            if not isinstance(instance_id, int):
                raise RuntimeError(f"Instance for {host} has invalid ID")
            await _delete_instance(session, cfg.api_key, cast("int", instance_id))
            log.info(f"Deleted VastAI instance {instance_id}")
        else:
            log.warning(f"No VastAI instance found with IP {host}")
