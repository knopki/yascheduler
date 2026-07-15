# FILE: yascheduler/infra/cloud/providers/vastai.py
# VERSION: 1.10.0
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

#   LAST_CHANGE: v1.10.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v1.9.0 - remove log parameter from function signatures; bind module-local logger = get_logger("M-CLOUD-VASTAI") at module top
# END_CHANGE_SUMMARY

"""VastAI cloud methods."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

try:
    import aiohttp

    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey

    from yascheduler.infra.cloud import CloudInitConfig, ConfigCloudVastAI

BASE_URL = "https://console.vast.ai/api/v0"


class _VastApiError(RuntimeError):
    def __init__(self, status: int, reason: str | None, text: str) -> None:
        self.status = status
        self.reason = reason
        self.text = text
        super().__init__(f"VastAI API error: {status} {reason}: {text}")


class _VastDeleteApiError(RuntimeError):
    def __init__(
        self,
        instance_id: int,
        status: int,
        reason: str | None,
        text: str,
    ) -> None:
        self.instance_id = instance_id
        self.status = status
        self.reason = reason
        self.text = text
        super().__init__(
            f"VastAI API error deleting instance {instance_id}: "
            f"{status} {reason}: {text}",
        )


class _VastNoOffersError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("No VastAI offers found matching criteria")


class _VastInvalidOfferIdError(TypeError):
    def __init__(self) -> None:
        super().__init__("Offer missing required 'id' field")


class _VastInvalidInstanceIdError(TypeError):
    def __init__(self) -> None:
        super().__init__("Failed to create instance - no contract ID returned")


class _VastInstanceTimeoutError(TimeoutError):
    def __init__(self, instance_id: int, max_wait: int) -> None:
        self.instance_id = instance_id
        self.max_wait = max_wait
        super().__init__(
            f"Instance {instance_id} did not become ready within {max_wait} seconds",
        )


class _VastInvalidHostInstanceIdError(TypeError):
    def __init__(self, host: str) -> None:
        self.host = host
        super().__init__(f"Instance for {host} has invalid ID")


def _get_headers(api_key: str) -> dict[str, str]:
    """Get headers for VastAI API requests."""
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


# START_CONTRACT: _api_request
#   PURPOSE: Execute authenticated HTTP request to VastAI API with error handling
#   INPUTS: { session: aiohttp.ClientSession - HTTP session, method: str - HTTP method, url: str - request URL, api_key: str - API key, **kwargs: Any - additional request params }
#   OUTPUTS: { dict[str, Any] - parsed JSON response }
#   SIDE_EFFECTS: Makes HTTP request to VastAI API.
#   LINKS: M-CLOUD-VASTAI
# END_CONTRACT: _api_request
async def _api_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    api_key: str,
    **kwargs: dict[str, Any],
) -> dict[str, Any]:
    headers = _get_headers(api_key)
    timeout = aiohttp.ClientTimeout(total=30)

    async with session.request(
        method,
        url,
        headers=headers,
        timeout=timeout,
        **kwargs,
    ) as resp:
        if not resp.ok:
            text = await resp.text()
            raise _VastApiError(resp.status, resp.reason, text)
        return await resp.json()


# START_CONTRACT: _search_offers
#   PURPOSE: Search VastAI marketplace for available GPU offers matching criteria
#   INPUTS: { session: aiohttp.ClientSession, api_key: str, min_vram_mb: int, num_gpus: int, max_price: float }
#   OUTPUTS: { list[dict[str, Any]] - available offers }
#   SIDE_EFFECTS: Makes HTTP request to VastAI API.
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
        session,
        "GET",
        f"{BASE_URL}/bundles/",
        api_key,
        params=params,
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
        session,
        "PUT",
        f"{BASE_URL}/asks/{offer_id}/",
        api_key,
        json=payload,
    )


async def _get_instance_info(
    session: aiohttp.ClientSession,
    api_key: str,
    instance_id: int,
) -> dict[str, Any]:
    data = await _api_request(
        session,
        "GET",
        f"{BASE_URL}/instances/{instance_id}/",
        api_key,
    )
    inner = data.get("instances")
    if isinstance(inner, dict):
        return inner
    if isinstance(inner, list) and inner:
        return inner[0]
    return data


async def _find_instance_by_ip(
    session: aiohttp.ClientSession,
    api_key: str,
    host: str,
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
    session: aiohttp.ClientSession,
    api_key: str,
    instance_id: int,
) -> None:
    headers = _get_headers(api_key)
    timeout = aiohttp.ClientTimeout(total=30)
    url = f"{BASE_URL}/instances/{instance_id}/"

    async with session.delete(url, headers=headers, timeout=timeout) as resp:
        if not resp.ok:
            text = await resp.text()
            raise _VastDeleteApiError(instance_id, resp.status, resp.reason, text)


# START_CONTRACT: vastai_create_node
#   PURPOSE: Create VastAI instance from cheapest matching offer and wait for readiness
#   INPUTS: { cfg: ConfigCloudVastAI, key: SSHKey, cloud_config: Optional[CloudInitConfig] }
#   OUTPUTS: { str - IP address of the running instance }
#   SIDE_EFFECTS: Creates cloud instance; polls until running or timeout
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-VASTAI
# END_CONTRACT: vastai_create_node
async def vastai_create_node(
    cfg: ConfigCloudVastAI,
    key: SSHKey,  # noqa: ARG001
    cloud_config: CloudInitConfig | None = None,  # noqa: ARG001
) -> str:
    """Create VastAI instance from cheapest matching offer and wait for readiness."""
    async with aiohttp.ClientSession() as session:
        logger.info("Searching VastAI offers...")
        offers = await _search_offers(
            session,
            cfg.api_key,
            cfg.min_vram_mb,
            cfg.num_gpus,
            cfg.max_price_per_hr,
        )
        if not offers:
            raise _VastNoOffersError

        offer = offers[0]
        offer_id = offer.get("id")
        if not isinstance(offer_id, int):
            raise _VastInvalidOfferIdError
        logger.info("Creating instance from offer %s", offer_id)

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
            raise _VastInvalidInstanceIdError
        instance_id = cast("int", instance_id)

        max_wait = 600  # 10 minutes
        poll_interval = 8
        for _ in range(max_wait // poll_interval):
            await asyncio.sleep(poll_interval)

            info = await _get_instance_info(session, cfg.api_key, instance_id)
            status = info.get("actual_status") or info.get("status")
            logger.info("Instance %s status: %s", instance_id, status)

            if status == "running":
                ip_addr = info.get("public_ipaddr")
                if ip_addr:
                    logger.info("Instance running at %s", ip_addr)
                    return ip_addr
                logger.warning("Instance running but no public IP address yet")

        raise _VastInstanceTimeoutError(instance_id, max_wait)


# START_CONTRACT: vastai_delete_node
#   PURPOSE: Delete VastAI instance by its IP address
#   INPUTS: { cfg: ConfigCloudVastAI, host: str }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Deletes cloud instance
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-VASTAI
# END_CONTRACT: vastai_delete_node
async def vastai_delete_node(
    cfg: ConfigCloudVastAI,
    host: str,
) -> None:
    """Delete VastAI instance by its IP address."""
    async with aiohttp.ClientSession() as session:
        inst = await _find_instance_by_ip(session, cfg.api_key, host)
        if inst:
            instance_id = inst.get("id")
            if not isinstance(instance_id, int):
                raise _VastInvalidHostInstanceIdError(host)
            await _delete_instance(session, cfg.api_key, cast("int", instance_id))
            logger.info("Deleted VastAI instance %s", instance_id)
        else:
            logger.warning("No VastAI instance found with IP %s", host)
