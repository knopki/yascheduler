"""VastAI cloud provider."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission VastAI GPU instances so the scheduler can run compute workloads on transient VastAI hosts through the generic CloudAdapter contract.
# SCOPE: cloud-side lifecycle only, NOT DB/UoW/SSH-setup/allocator.
# DEPENDENCIES: USES API: cloud.vast.ai (aiohttp)
# KEYWORDS: vastai, provider, create, delete, ssh key, offers, instances
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Literal, TypedDict

import aiohttp

from yascheduler.infra.cloud import CloudCreateNodeDTO
from yascheduler.infra.cloud.utils import get_rnd_name

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from asyncssh.public_key import SSHKey as ASSHKey

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
    from yascheduler.infra.cloud.cloud_init import CloudInitConfig
    from yascheduler.shared import Required, Self, TypeGuard, Unpack

__all__ = ["vastai_create_node", "vastai_delete_node"]
logger = logging.getLogger(__name__)

_VASTAI_BASE_URL = "https://cloud.vast.ai/api/v0"
_HTTP_BAD_REQUEST = 400
_HTTP_NOT_FOUND = 404

# Best-effort orphan reconcile after an ambiguous non-idempotent create.
# Covers listing-lag (instance not yet visible after PUT) and transient
# listing failures; matched by the unique per-create label.
_RECONCILE_ATTEMPTS = 3
_RECONCILE_INTERVAL = 20.0

# Verify-after-delete: poll GET /instances/{id}/ until 404 so a 2xx DELETE
# (accepted, not gone) cannot leave a billed orphan. Mirrors Vultr/Hetzner.
_DELETE_VERIFY_TIMEOUT = 180.0
_DELETE_VERIFY_INTERVAL = 20.0


# region BLOCK_API_errors
# PURPOSE: VastAI API error type carrying the HTTP status so the orchestrator's retry loop can distinguish idempotent 404 (already gone) from real failures.
class VastAIError(Exception):
    """VastAI API error carrying the HTTP status.

    `status` is the HTTP status when the error originated from an HTTP
    response, or None for transport-level failures.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


# endregion BLOCK_API_errors

# region BLOCK_API_typed_dicts
# PURPOSE: TypedDict mirrors of the Vast.ai REST API response/request shapes, so client methods and validators share one structural contract.


class VastAISSHKey(TypedDict):
    public_key: str


class VastAICreateSSHKeyResponse(TypedDict):
    success: bool
    key: VastAISSHKey


class VastAIOffer(TypedDict):
    id: int
    dph_total: float | int


class VastAIOffersResponce(TypedDict):
    offers: list[VastAIOffer]


class VastAICreateInstanceResponce(TypedDict):
    new_contract: int | float


class VastAIInstance(TypedDict):
    id: int | float
    actual_status: str | None
    ssh_host: str
    ssh_port: int | float


class VastAIShowInstanceResponce(TypedDict):
    instances: VastAIInstance


class VastAIShowInstancesResponce(TypedDict):
    next_token: str | None
    instances: list[VastAIInstance]


VastAIFilter = dict[str, str | int | float | bool | list[str]]


class VastAISearchOffersFilters(TypedDict, total=False):
    duration: VastAIFilter
    gpu_ram: VastAIFilter
    num_gpus: VastAIFilter
    gpu_frac: VastAIFilter
    reliability: VastAIFilter
    rentable: VastAIFilter
    rented: VastAIFilter
    dph_total: VastAIFilter


class VastAICreateInstanceParams(TypedDict, total=False):
    image: Required[str]
    template_hash_id: str
    label: str
    disk: int
    env: str
    vm: bool
    onstart: str


class VastAIShowInstancesFilters(TypedDict, total=False):
    actual_status: VastAIFilter
    gpu_name: VastAIFilter
    verification: VastAIFilter
    id: VastAIFilter
    label: VastAIFilter


# endregion BLOCK_API_typed_dicts

# region BLOCK_API_validators
# PURPOSE: TypeGuard validators narrowing untyped API JSON to the TypedDict shapes above, so client methods fail fast on shape drift with a VastAIError rather than silently misreading fields.


def _is_api_ssh_key(resp: object) -> TypeGuard[VastAISSHKey]:
    return isinstance(resp, dict) and isinstance(resp.get("public_key"), str)


def _is_api_ssh_keys_list(resp: object) -> TypeGuard[list[VastAISSHKey]]:
    return isinstance(resp, list) and all(_is_api_ssh_key(x) for x in resp)


def _is_api_ssh_key_created(resp: object) -> TypeGuard[VastAICreateSSHKeyResponse]:
    return (
        isinstance(resp, dict)
        and isinstance(resp.get("success"), bool)
        and "key" in resp
        and _is_api_ssh_key(resp["key"])
    )


def _is_api_offer(resp: object) -> TypeGuard[VastAIOffer]:
    return (
        isinstance(resp, dict)
        and isinstance(resp.get("id"), (int, float))
        and isinstance(resp.get("dph_total"), (int, float))
    )


def _is_api_offers_list(resp: object) -> TypeGuard[VastAIOffersResponce]:
    return (
        isinstance(resp, dict)
        and "offers" in resp
        and all(_is_api_offer(x) for x in resp["offers"])
    )


def _is_api_create_instance_resp(
    resp: object,
) -> TypeGuard[VastAICreateInstanceResponce]:
    return isinstance(resp, dict) and isinstance(resp.get("new_contract"), (float, int))


def _is_api_instance(resp: object) -> TypeGuard[VastAIInstance]:
    return (
        isinstance(resp, dict)
        and isinstance(resp.get("id"), (int, float))
        and isinstance(resp.get("actual_status"), (str, type(None)))
        and isinstance(resp.get("ssh_host"), str)
        and isinstance(resp.get("ssh_port"), (int, float))
    )


def _is_api_show_instance_resp(resp: object) -> TypeGuard[VastAIShowInstanceResponce]:
    return (
        isinstance(resp, dict)
        and "instances" in resp
        and _is_api_instance(resp["instances"])
    )


def _is_api_show_instances_resp(resp: object) -> TypeGuard[VastAIShowInstancesResponce]:
    return (
        isinstance(resp, dict)
        and isinstance(resp.get("next_token"), (str, type(None)))
        and isinstance(resp.get("instances"), list)
        and all(_is_api_instance(x) for x in resp["instances"])
    )


# endregion BLOCK_API_validators


# region CLASS_VastAIClient
# PURPOSE: Wrap a single aiohttp session authenticated to the VastAI API so repeated create/poll/delete calls reuse one connection pool instead of re-handshaking per request.
class VastAIClient:
    """Async Vastai REST API client (aiohttp-based)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._session = aiohttp.ClientSession(
            base_url=_VASTAI_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=aiohttp.ClientTimeout(total=60),
        )

    async def close(self) -> None:
        await self._session.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        params: aiohttp.typedefs.Query | None = None,
        data: dict | None = None,
    ) -> object:
        """Send an async HTTP request to the Vastai API and return parsed JSON."""
        try:
            async with self._session.request(
                method, path, params=params, json=data
            ) as resp:
                logger.debug(
                    "VASTAI_REQUEST",
                    extra={"method": method, "path": path, "status": resp.status},
                )
                if resp.status >= _HTTP_BAD_REQUEST:
                    msg = f"HTTP {resp.status}: {await resp.text()}"
                    raise VastAIError(msg, status=resp.status)
                return await resp.json()
        except aiohttp.ClientResponseError as exc:
            msg = f"HTTP request failed: {exc.message}"
            raise VastAIError(msg, status=exc.status) from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            msg = f"Transport error: {exc}"
            raise VastAIError(msg) from exc

    async def get_ssh_keys(self) -> list[VastAISSHKey]:
        resp = await self._request("GET", "/ssh")
        if not _is_api_ssh_keys_list(resp):
            msg = f"Invalid SSH key list response: {resp}"
            raise VastAIError(msg)
        return resp

    async def create_ssh_key(self, ssh_key: str) -> bool:
        resp = await self._request("POST", "/ssh", data={"ssh_key": ssh_key})
        if not _is_api_ssh_key_created(resp):
            msg = f"Invalid SSH key create response: {resp}"
            raise VastAIError(msg)
        return resp["success"] is True

    async def search_offers(
        self,
        instance_type: str = "ondemand",
        order: list[tuple[str, Literal["asc", "desc"]]] | None = None,
        limit: int = 20,
        **filters: Unpack[VastAISearchOffersFilters],
    ) -> list[VastAIOffer]:
        data = dict(filters)
        data["type"] = instance_type
        if order:
            data["order"] = [list(x) for x in order]
        if limit:
            data["limit"] = limit
        resp = await self._request("POST", "/bundles", data=data)
        if _is_api_offers_list(resp):
            offers = resp["offers"]
            logger.debug("OFFER_SEARCH", extra={"offer_count": len(offers)})
            return offers
        msg = f"Invalid offers list response: {resp}"
        raise VastAIError(msg)

    async def create_instance(
        self, ask_id: int, **params: Unpack[VastAICreateInstanceParams]
    ) -> int:
        data = dict(
            target_state="running", runtype="ssh_proxy", cancel_unavail=True, **params
        )
        resp = await self._request("PUT", f"/asks/{ask_id}", data=data)
        if not _is_api_create_instance_resp(resp):
            msg = f"Invalid create instance response: {resp}"
            raise VastAIError(msg)
        return int(resp["new_contract"])

    async def destroy_instance(self, instance_id: int) -> None:
        await self._request("DELETE", f"/instances/{instance_id}")

    async def show_instance(self, instance_id: int) -> VastAIInstance:
        resp = await self._request("GET", f"/instances/{instance_id}")
        if not _is_api_show_instance_resp(resp):
            msg = f"Invalid show instance response: {resp}"
            raise VastAIError(msg)
        return resp["instances"]

    async def show_instances(
        self, select_filters: VastAIShowInstancesFilters | None = None, limit: int = 25
    ) -> AsyncIterator[VastAIInstance]:
        """Yield instances one at a time, paginating through all pages."""
        params: dict = {"limit": limit}
        if select_filters:
            params["select_filters"] = select_filters
        while True:
            resp = await self._request("GET", "/instances", params=params)
            if not _is_api_show_instances_resp(resp):
                msg = f"Invalid show instances response: {resp}"
                raise VastAIError(msg)
            for instance in resp["instances"]:
                yield instance
            if not (after_token := resp.get("next_token")):
                break
            params["after_token"] = after_token


# endregion CLASS_VastAIClient


# region FUNC_ensure_ssh_key
# PURPOSE: Ensure the operator SSH key is registered so the freshly created instance authorizes it and the scheduler can connect without password auth.
# REQUIRES: public_key is a valid SSH public key string.
# ENSURES: Key is registered on the account
async def ensure_ssh_key(
    client: VastAIClient,
    public_key: str,
) -> bool:
    """Ensure the SSH public key is registered on the VastAI account."""
    logger.debug("SSH_KEY_PRESENCE_CHECK", extra={"public_key": public_key})
    for k in await client.get_ssh_keys():
        if k["public_key"].strip() == public_key.strip():
            return True

    success = await client.create_ssh_key(public_key)
    logger.debug(
        "SSH_KEY_REGISTERED", extra={"public_key": public_key, "success": success}
    )
    return success


# endregion FUNC_ensure_ssh_key


# region FUNC_select_cheapest_offer
# PURPOSE: Bound spend under the configured ceiling and spread jobs off a single flaky host — random pick from the five cheapest rather than always the cheapest.
# REQUIRES: offers is a list of offers.
# ENSURES: Returns the cheapest valid offer; raises on empty or invalid.
async def select_cheapest_offer(
    offers: list[VastAIOffer],
    max_price_per_hr: float,
) -> VastAIOffer:
    """Select the cheapest compatible offer from a sorted list."""
    if not offers:
        msg = "No offers found matching the configured criteria"
        raise VastAIError(msg)

    # Not cheapest, but random from the top-5 cheapest
    # Don't fall into the same broken provider
    offer = random.choice(sorted(offers, key=lambda x: x["dph_total"])[:5])  # noqa: S311

    dph_total = offer["dph_total"]
    if dph_total > max_price_per_hr:
        msg = f"Offer price {dph_total} exceeds max price {max_price_per_hr}"
        raise VastAIError(msg)

    logger.debug(
        "SELECTED_OFFER",
        extra={"offer_id": offer["id"], "dph_total": dph_total},
    )
    return offer


# endregion FUNC_select_cheapest_offer


# region FUNC_generate_onstart
# PURPOSE: Flatten the cloud-init config into one shell script because VastAI's onstart is a single script, not cloud-init.
# ENSURES: Returns a startup script string.
async def generate_onstart(
    cfg: ConfigCloudVastAI,
    cloud_config: CloudInitConfig | None = None,
) -> str:
    """Generate the onstart script for a VastAI instance."""
    if cfg.onstart_script is not None:
        return cfg.onstart_script

    if cloud_config is None:
        return ""

    image = cfg.image
    is_kvm = detect_launch_mode(image) == "kvm"
    use_apt = "debian" in image.lower() or "ubuntu" in image.lower()
    pm = "apt-get" if use_apt else "dnf"

    lines: list[str] = []
    if is_kvm:
        lines.append("#!/bin/bash")

    if cloud_config.package_upgrade:
        lines.append(
            "apt-get update && apt-get upgrade -y" if use_apt else "dnf upgrade -y",
        )

    if cloud_config.packages:
        lines.append(f"{pm} install -y {' '.join(cloud_config.packages)}")

    for cmd in cloud_config.bootcmd:
        if isinstance(cmd, list):
            lines.extend(cmd)
        else:
            lines.append(cmd)

    return "\n".join(lines)


# endregion FUNC_generate_onstart


async def _best_effort_delete(client: VastAIClient, instance_id: int) -> None:
    """Best-effort delete an instance to prevent orphans.

    Swallows any exception so it never masks the original create error or
    skips the caller's error propagation. A transport error here does not
    re-raise: the caller's failure is the one that matters, and the orphan
    (if any) is the subject of a separate reconcile path.
    """
    try:
        logger.debug("ORPHAN_CLEANUP", extra={"instance_id": instance_id})
        await client.destroy_instance(instance_id)
    except Exception:  # best-effort cleanup must not mask caller error
        logger.warning("NODE %s NOT DELETED", instance_id)


# region FUNC__reconcile_orphan_by_label
# PURPOSE: Close the non-idempotent-create orphan window by matching and best-effort deleting an instance created during a failed/ambiguous PUT, using the unique label generated pre-PUT.
# ENSURES: Never raises — the original create error propagates regardless. Retries the listing _RECONCILE_ATTEMPTS times with a delay to cover listing-lag (instance not yet visible after PUT) and transient listing failures; on each tick a label match triggers best-effort delete, exhausting all attempts without a match logs a warning for manual reconciliation.
async def _reconcile_orphan_by_label(
    client: VastAIClient,
    label: str,
) -> None:
    """Best-effort delete of an instance created during an ambiguous PUT.

    PUT /asks/{offer_id}/ is not idempotent: if the transport breaks after the
    server accepted the create, an instance exists that we never got an id for.
    Match it by the unique label generated pre-PUT and delete it. Never raises.
    """
    for attempt in range(1, _RECONCILE_ATTEMPTS + 1):
        orphan_id: int | float | None = None
        try:
            async for inst in client.show_instances(
                select_filters={"label": {"eq": label}}
            ):
                orphan_id = inst["id"]
                break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "RECONCILE_LIST_TRANSIENT",
                extra={"label": label, "attempt": attempt},
            )
            if attempt < _RECONCILE_ATTEMPTS:
                await asyncio.sleep(_RECONCILE_INTERVAL)
                continue
            logger.warning(
                "RECONCILE_LOOKUP_FAILED — potential orphan billing; manual check needed",
                extra={"label": label},
            )
            return
        if orphan_id is not None:
            logger.warning(
                "RECONCILE_DELETE_ORPHAN",
                extra={"label": label, "instance_id": orphan_id},
            )
            await _best_effort_delete(client, int(orphan_id))
            return
        logger.debug(
            "RECONCILE_NO_ORPHAN",
            extra={"label": label, "attempt": attempt},
        )
        if attempt < _RECONCILE_ATTEMPTS:
            await asyncio.sleep(_RECONCILE_INTERVAL)
    logger.warning(
        "RECONCILE_NO_ORPHAN — %s listing attempts found no match for label %s",
        _RECONCILE_ATTEMPTS,
        label,
    )


# endregion FUNC__reconcile_orphan_by_label


# region FUNC__verify_instance_gone
# PURPOSE: Poll GET /instances/{id}/ until 404 (confirmed gone) so delete never claims success on a still-billing orphan after an accepted DELETE.
# ENSURES: Returns True on 404 (confirmed gone). Returns False on timeout (logs ERROR for manual intervention). Never raises. Transient GET errors during polling are treated as "uncertain, keep polling".
async def _verify_instance_gone(client: VastAIClient, instance_id: int) -> bool:
    """Poll GET until the instance returns 404 or _DELETE_VERIFY_TIMEOUT expires.

    Returns True iff confirmed gone. Never raises.
    """
    deadline = asyncio.get_running_loop().time() + _DELETE_VERIFY_TIMEOUT
    while asyncio.get_running_loop().time() < deadline:
        try:
            await client.show_instance(instance_id)
        except VastAIError as err:
            if err.status == _HTTP_NOT_FOUND:
                logger.info("INSTANCE %s delete confirmed gone (404)", instance_id)
                return True
            logger.debug(
                "VERIFY_GET_RETRY",
                extra={"instance_id": instance_id, "status": err.status},
            )
        await asyncio.sleep(_DELETE_VERIFY_INTERVAL)
    logger.error(
        "INSTANCE %s STILL PRESENT %ss after accepted DELETE — "
        "manual deletion required via VastAI console",
        instance_id,
        _DELETE_VERIFY_TIMEOUT,
    )
    return False


# endregion FUNC__verify_instance_gone


# region FUNC__delete_and_verify
# PURPOSE: Delete a VastAI instance by known id and confirm gone so neither create_node cleanup nor vastai_delete_node leaves a billable orphan — the instance id is known, so direct delete+verify (no label reconcile).
# ENSURES: Returns True iff the instance is confirmed gone (DELETE 404 or verify GET 404). Returns False on verify timeout (logs ERROR for manual intervention). DELETE errors other than 404 propagate to the orchestrator (idempotent, retried next cycle). Never raises on verify-path failures.
# MODEL: VastAI DELETE is asynchronous (2xx = accepted, not gone). A 404 on DELETE means already gone. After an accepted DELETE, poll GET until 404 or _DELETE_VERIFY_TIMEOUT.
async def _delete_and_verify(client: VastAIClient, instance_id: int) -> bool:
    """Delete an instance and verify it is gone.

    Returns True iff confirmed gone (404). DELETE errors other than 404
    propagate (idempotent — orchestrator retries). Verify-path failures
    return False (never raise).
    """
    try:
        await client.destroy_instance(instance_id)
    except VastAIError as err:
        if err.status == _HTTP_NOT_FOUND:
            logger.warning("Instance %s already gone (DELETE 404)", instance_id)
            return True
        raise
    return await _verify_instance_gone(client, instance_id)


# endregion FUNC__delete_and_verify


# region FUNC_wait_until_ready
# PURPOSE: Bridge VastAI's async create (returns before ssh_host/port exist) so create_node only reports success once the scheduler can actually connect.
# REQUIRES: client is an open VastAIClient; instance_id is a valid instance id.
# ENSURES: Returns the instance dict when actual_status == "running". Raises VastAIError on timeout, terminal status, or any show-instance failure. Does NOT delete the instance — vastai_create_node wraps this in try/except and runs _delete_and_verify so the instance is confirmed gone, not best-effort-gone.
async def wait_until_ready(
    client: VastAIClient, instance_id: int, timeout: float
) -> VastAIInstance:
    """Poll until the VastAI instance is ready."""
    deadline = asyncio.get_running_loop().time() + timeout
    poll_interval = 5.0

    while True:
        now = asyncio.get_running_loop().time()
        if now >= deadline:
            logger.debug("POLL_TIMEOUT", extra={"instance_id": instance_id})
            msg = f"Instance {instance_id} did not become ready within {timeout}s"
            raise VastAIError(msg)

        try:
            inst = await client.show_instance(instance_id)
        except asyncio.CancelledError:
            raise
        except VastAIError as err:
            logger.debug(
                "POLL_SHOW_FAILED",
                extra={"instance_id": instance_id, "status": err.status},
            )
            msg = f"Instance {instance_id} status query failed: {err}"
            raise VastAIError(msg) from err
        status = inst["actual_status"]

        logger.debug(
            "POLL_STATUS",
            extra={"instance_id": instance_id, "status": status},
        )

        if status == "running":
            logger.debug(
                "INSTANCE_READY",
                extra={
                    "instance_id": instance_id,
                    "ssh_host": inst["ssh_host"],
                    "ssh_port": inst["ssh_port"],
                },
            )
            logger.info(
                "NEW INSTANCE! %s with root@%s -P %s",
                instance_id,
                inst["ssh_host"],
                inst["ssh_port"],
            )
            return inst

        if status in ("stopped", "frozen", "exited", "unknown", "offline"):
            logger.debug(
                "POLL_TERMINAL",
                extra={"instance_id": instance_id, "status": status},
            )
            msg = f"Instance {instance_id} entered terminal status: {status}"
            raise VastAIError(msg)

        await asyncio.sleep(poll_interval)


# endregion FUNC_wait_until_ready


def detect_launch_mode(
    image: str,
) -> str:
    """Detect the launch mode (kvm or docker) from the image name."""
    return "kvm" if "vastai/kvm" in image else "docker"


# region FUNC_vastai_create_node
# PURPOSE: Provision a VastAI GPU instance via the CloudAdapter interface so the generic provisioner can launch VastAI compute nodes.
# ENSURES: Returns CloudCreateNodeDTO with external_id = instance id, hostname = SSH host, port = SSH port.
# INVARIANTS:
# - external_id = instance id; session closed on all paths.
# - Never raises after an instance was created without best-effort removing it: a failed create call (transport ambiguity or malformed response) reconciles any instance matching the unique per-create label before re-raising.
# - Readiness polling cleans up the known instance on every failure path that leaves the poll loop (timeout, terminal status, show-instance failure).
async def vastai_create_node(
    cfg: ConfigCloudVastAI,
    key: ASSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create a VastAI GPU instance."""
    public_key = key.export_public_key().decode()

    async with VastAIClient(cfg.api_key) as client:
        logger.debug("SSH_KEY_CHECK", extra={})
        await ensure_ssh_key(client, public_key)

        logger.debug("OFFER_SEARCH_START", extra={})
        offers = await client.search_offers(
            instance_type="ondemand",
            order=[("dph_total", "asc")],
            limit=20,
            duration={"gte": 60},
            gpu_ram={"gte": cfg.min_vram_mb},
            num_gpus={"eq": cfg.num_gpus},
            gpu_frac={"gte": 1.0},
            reliability={"gte": 0.99},
            rentable={"eq": True},
            rented={"eq": False},
            dph_total={"lte": cfg.max_price_per_hr},
        )

        logger.debug("OFFER_SELECT", extra={})
        offer = await select_cheapest_offer(offers, cfg.max_price_per_hr)

        onstart = await generate_onstart(cfg, cloud_config)
        mode = detect_launch_mode(cfg.image)

        # Unique per-create label: PUT /asks is not idempotent, so a transport
        # break after the server accepted the create loses the returned id. The
        # unique label lets _reconcile_orphan_by_label target only the instance
        # this create produced, never other instances on the same account. The
        # configured cfg.label prefix is retained so broad filters (e2e cleanup)
        # still match via startswith.
        create_label = get_rnd_name(cfg.label)
        try:
            instance_id = await client.create_instance(
                ask_id=offer["id"],
                image=cfg.image,
                disk=cfg.disk_gb,
                vm=mode == "kvm",
                label=create_label,
                onstart=onstart,
                env=cfg.docker_options or "",
            )
        except Exception:
            # Transport ambiguity (break after accept) or malformed create
            # response (2xx without new_contract): the instance may exist with
            # no captured id. Reconcile by the unique label before re-raising so
            # no billable orphan leaks.
            logger.warning(
                "CREATE_INSTANCE_FAILED — reconciling by label %s",
                create_label,
            )
            await _reconcile_orphan_by_label(client, create_label)
            raise
        logger.debug("INSTANCE_CREATE", extra={"offer_id": offer["id"]})

        # The instance now exists and bills. Any failure below MUST delete it
        # so create_node never leaks a billable orphan (instance id known here,
        # so no label reconcile needed — direct delete+verify).
        try:
            instance = await wait_until_ready(client, instance_id, cfg.connect_grace)
        except Exception:
            logger.exception(
                "Instance %s create_node failed before returning", instance_id
            )
            await _delete_and_verify(client, instance_id)
            raise
        logger.debug("INSTANCE_READY", extra={"instance_id": instance_id})

    return CloudCreateNodeDTO(
        external_id=str(instance_id),
        hostname=instance["ssh_host"],
        port=int(instance["ssh_port"]),
        username="root",
        jump_host=cfg.jump_host,
        jump_port=cfg.jump_port,
        jump_username=cfg.jump_username or "root",
    )


# endregion FUNC_vastai_create_node


# region FUNC_vastai_delete_node
# PURPOSE: Tear down a VastAI instance so billing stops and the node slot is freed for reallocation.
# INVARIANTS:
# - external_id = instance id
# - delegates to _delete_and_verify (delete + async-deletion verify) so the public delete path inherits the same orphan-prevention guarantees as create_node cleanup.
# - On _delete_and_verify returning False RAISES VastAIError so the caller's failure handling (DB row stays disabled for cross-cycle retry) kicks in.
# - DELETE errors other than 404 propagate to the orchestrator, which repeats the whole delete next cycle (DELETE is idempotent).
async def vastai_delete_node(cfg: ConfigCloudVastAI, external_id: str) -> None:
    """Delete a VastAI GPU instance and verify it is gone.

    Raises VastAIError when deletion cannot be confirmed gone, so the caller
    can leave the DB row intact for cross-cycle retry. A 404 (already gone)
    is a no-op.
    """
    try:
        instance_id = int(external_id)
    except (TypeError, ValueError) as err:
        msg = f"Invalid VastAI instance id {external_id!r}: {err}"
        raise VastAIError(msg) from err

    async with VastAIClient(cfg.api_key) as client:
        logger.debug("INSTANCE_DELETE", extra={"instance_id": instance_id})
        if await _delete_and_verify(client, instance_id):
            logger.info("DELETED %s", instance_id)
            return
    msg = (
        f"Instance {instance_id} delete not confirmed gone within "
        f"{_DELETE_VERIFY_TIMEOUT}s — cloud VM may still bill; "
        "orchestrator will retry next cycle"
    )
    raise VastAIError(msg)


# endregion FUNC_vastai_delete_node
