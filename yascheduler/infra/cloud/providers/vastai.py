"""VastAI cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission GPU instances on the VastAI marketplace so the scheduler can run GPU-accelerated workloads through the generic CloudAdapter contract.
# SCOPE: VastAI create/delete node functions.
# DEPENDENCIES: USES API: aiohttp (HTTP client); WRITES: HTTP GET/PUT/DELETE to console.vast.ai/api/v0
# KEYWORDS: vastai, gpu, instance, create, delete, rest api, marketplace
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from yascheduler.infra.cloud.dto import CloudCreateNodeDTO

try:
    import aiohttp

    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey

    from yascheduler.infra.cloud import CloudInitConfig, ConfigCloudVastAI

__all__ = [
    "vastai_create_node",
    "vastai_delete_node",
]

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


# region FUNC__api_request
# PURPOSE: Execute an authenticated HTTP request to the VastAI API with typed error wrapping so callers get consistent error handling regardless of the endpoint.
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


# endregion FUNC__api_request


# region FUNC__search_offers
# PURPOSE: Query the VastAI marketplace for GPU offers matching VRAM, GPU count, and price criteria so the cheapest suitable instance is selected for provisioning.
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


# endregion FUNC__search_offers


# region FUNC__create_instance
# PURPOSE: Create a VastAI instance from a selected marketplace offer so the scheduler gets a GPU compute node.
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


# endregion FUNC__create_instance


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


# region FUNC_vastai_create_node
# PURPOSE: Pick the cheapest matching GPU offer, create an instance, and poll until it is running so the provisioner gets a usable IP without manual monitoring.
async def vastai_create_node(
    cfg: ConfigCloudVastAI,
    key: SSHKey,  # noqa: ARG001
    cloud_config: CloudInitConfig | None = None,  # noqa: ARG001
) -> CloudCreateNodeDTO:
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
                    return CloudCreateNodeDTO(
                        external_id=ip_addr,
                        hostname=ip_addr,
                        username=cfg.username,
                        jump_host=cfg.jump_host,
                        jump_port=cfg.jump_port,
                        jump_username=cfg.jump_username or "root",
                    )
                logger.warning("Instance running but no public IP address yet")

        raise _VastInstanceTimeoutError(instance_id, max_wait)


# endregion FUNC_vastai_create_node


# region FUNC_vastai_delete_node
# PURPOSE: Tear down a VastAI GPU instance by IP so billing stops and the GPU slot returns to the marketplace.
async def vastai_delete_node(
    cfg: ConfigCloudVastAI,
    external_id: str,
) -> None:
    """Delete VastAI instance by its IP address."""
    async with aiohttp.ClientSession() as session:
        inst = await _find_instance_by_ip(session, cfg.api_key, external_id)
        if inst:
            instance_id = inst.get("id")
            if not isinstance(instance_id, int):
                raise _VastInvalidHostInstanceIdError(external_id)
            await _delete_instance(session, cfg.api_key, cast("int", instance_id))
            logger.info("Deleted VastAI instance %s", instance_id)
        else:
            logger.warning("No VastAI instance found with IP %s", external_id)


# endregion FUNC_vastai_delete_node
