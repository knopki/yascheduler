"""VastAI cloud provider."""
# region MODULE_CONTRACT
# PURPOSE: VastAI provider lifecycle — SSH key registration, offer search, cheapest selection, instance create/poll, delete.
# SCOPE: cloud-side lifecycle only, NOT DB/UoW/SSH-setup/allocator.
# DEPENDENCIES: USES API: cloud.vast.ai (aiohttp)
# KEYWORDS: vastai, provider, create, delete, ssh key, offers, instances
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, TypedDict

import aiohttp

from yascheduler.infra.cloud import CloudCreateNodeDTO
from yascheduler.infra.cloud.utils import get_rnd_name

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey as ASSHKey

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
    from yascheduler.infra.cloud.cloud_init import CloudInitConfig
    from yascheduler.shared import TypeGuard

__all__ = ["vastai_create_node", "vastai_delete_node", "vastai_list_instances"]
logger = logging.getLogger(__name__)

_VASTAI_BASE_URL = "https://cloud.vast.ai/api/v0"
_HTTP_BAD_REQUEST = 400
_HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "DELETE", "OPTIONS"})
_RETRY_MAX_TIME = 60.0
_RETRY_INITIAL_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0
_RETRY_FACTOR = 1.5

# Best-effort orphan reconcile after an ambiguous non-idempotent create.
# Covers listing-lag (instance not yet visible after PUT) and transient
# listing failures; matched by the unique per-create label.
_RECONCILE_ATTEMPTS = 3
_RECONCILE_INTERVAL = 5.0

# Verify-after-delete: poll GET /instances/{id}/ until 404 so a 2xx DELETE
# (accepted, not gone) cannot leave a billed orphan. Mirrors Vultr/Hetzner.
_DELETE_VERIFY_TIMEOUT = 180.0
_DELETE_VERIFY_INTERVAL = 10.0


class VastAIError(Exception):
    """Base exception for VastAI provider errors."""

    def __init__(self, message: str, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


class VastAIDeleteError(VastAIError):
    """VastAI instance deletion failed."""


class VastAINoOffersError(VastAIError):
    """No compatible VastAI offers found."""


class VastAIInvalidOfferError(VastAIError):
    """VastAI offer failed validation."""


class VastAIInstanceCreateError(VastAIError):
    """VastAI instance creation or readiness failed."""


# region FUNC__request
# PURPOSE: To make HTTP requests to Vast API
# REQUIRES: session is an open aiohttp.ClientSession.
# ENSURES: raises VastAIError on non-2xx or unexpected response shape.
async def _request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    json_data: object | None = None,
) -> dict | list:
    """Make an HTTP request to the VastAI API."""
    url = f"{_VASTAI_BASE_URL}{path}"
    kwargs: dict = {}
    if json_data is not None:
        kwargs["json"] = json_data

    try:
        async with session.request(method, url, **kwargs) as resp:
            logger.debug(
                "VASTAI_REQUEST",
                extra={"method": method, "path": path, "status": resp.status},
            )
            if resp.status >= _HTTP_BAD_REQUEST:
                try:
                    body = await resp.json()
                except Exception:
                    body = {}
                msg = body.get("msg", body.get("error", f"HTTP {resp.status}"))
                raise VastAIError(msg, status=resp.status)

            try:
                data = await resp.json()
            except Exception as exc:
                msg = f"Invalid JSON response: {exc}"
                raise VastAIError(msg) from exc

            return data
    except asyncio.CancelledError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        # ponytail: status=None marks a transport error so the retry layer can
        # retry it for idempotent calls (GET/DELETE) without retrying the
        # non-idempotent PUT create, which would double-create a billed instance.
        msg = f"Transport error: {exc}"
        raise VastAIError(msg, status=None) from exc


# endregion FUNC__request


# region FUNC__request_with_retry
# PURPOSE: Wrapper around _request that retries transient errors with exponential backoff.
# REQUIRES: Same as _request.
# ENSURES:
# - 429 retried for all methods (rate-limited requests never execute server-side).
# - Transport errors and 5xx retried ONLY for idempotent methods (GET/HEAD/DELETE/OPTIONS).
#   Retrying the non-idempotent PUT create on an uncertain outcome would
#   double-create a billed instance, so mutating PUT/POST are NOT retried on
#   transport/5xx (only on 429).
def _is_retryable(method: str, exc: VastAIError) -> bool:
    """Return True if the error is safe to retry for the given HTTP method."""
    status = exc.status
    if status == _HTTP_TOO_MANY_REQUESTS:
        return True
    if method.upper() in _IDEMPOTENT_METHODS:
        return status is None or status >= _HTTP_SERVER_ERROR
    return False


async def _request_with_retry(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    json_data: object | None = None,
) -> dict | list:
    """Make an HTTP request with method-aware retry on transient errors."""
    deadline = asyncio.get_running_loop().time() + _RETRY_MAX_TIME
    delay = _RETRY_INITIAL_DELAY
    while True:
        try:
            return await _request(session, method, path, json_data)
        except asyncio.CancelledError:
            raise
        except VastAIError as exc:
            if not _is_retryable(method, exc):
                raise
            if asyncio.get_running_loop().time() >= deadline:
                logger.debug("DEADLINE", extra={"exc": str(exc)})
                raise
            logger.debug("RETRY", extra={"exc": str(exc), "delay": delay})
        await asyncio.sleep(delay)
        delay = min(delay * _RETRY_FACTOR, _RETRY_MAX_DELAY)


# endregion FUNC__request_with_retry


class VastAISSHKey(TypedDict):
    public_key: str


def _is_api_ssh_key(resp: object) -> TypeGuard[VastAISSHKey]:
    return isinstance(resp, dict) and isinstance(resp.get("public_key"), str)


def _is_api_ssh_keys_list(resp: object) -> TypeGuard[list[VastAISSHKey]]:
    return isinstance(resp, list) and all(_is_api_ssh_key(x) for x in resp)


async def _list_ssh_keys(
    session: aiohttp.ClientSession,
) -> list[VastAISSHKey]:
    resp = await _request_with_retry(session, "GET", "/ssh/")
    if not _is_api_ssh_keys_list(resp):
        msg = f"Invalid SSH key list response: {resp}"
        raise VastAIError(msg)
    return resp


async def _create_ssh_key(
    session: aiohttp.ClientSession,
    public_key: str,
) -> bool:
    resp = await _request(
        session,
        "POST",
        "/ssh/",
        json_data={"ssh_key": public_key},
    )
    return isinstance(resp, dict) and resp.get("success") is True


# region FUNC_ensure_ssh_key
# PURPOSE: GET /ssh/ presence check by public key → POST /ssh/ if absent.
# REQUIRES: session is an open aiohttp.ClientSession; public_key is a valid SSH public key string.
# ENSURES: Key is registered on the account
async def ensure_ssh_key(
    session: aiohttp.ClientSession,
    public_key: str,
) -> bool:
    """Ensure the SSH public key is registered on the VastAI account."""
    logger.debug("SSH_KEY_PRESENCE_CHECK", extra={"public_key": public_key})
    keys = await _list_ssh_keys(session)

    for k in keys:
        if k["public_key"].strip() == public_key.strip():
            return True

    success = await _create_ssh_key(session, public_key)
    logger.debug("SSH_KEY_REGISTERED", extra={"public_key": public_key})
    return success


# endregion FUNC_ensure_ssh_key


class VastAIOffer(TypedDict):
    id: int
    dph_total: float | int


class VastAIOffersResponce(TypedDict):
    offers: list[VastAIOffer]


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


# region FUNC_search_offers
# PURPOSE: POST /bundles/ with the fixed filter body. Returns list of offers.
# REQUIRES: session is an open aiohttp.ClientSession.
# ENSURES: Returns list of offer dicts (may be empty).
async def search_offers(
    session: aiohttp.ClientSession,
    cfg: ConfigCloudVastAI,
) -> list[VastAIOffer]:
    """Search VastAI offers matching the configured criteria."""
    body: dict = {
        "duration": {"gte": 60},
        "gpu_ram": {"gte": cfg.min_vram_mb},
        "num_gpus": {"eq": cfg.num_gpus},
        "gpu_frac": {"gte": 1.0},
        "reliability": {"gte": 0.99},
        "rentable": {"eq": True},
        "rented": {"eq": False},
        "dph_total": {"lte": cfg.max_price_per_hr},
        "type": "on-demand",
        "order": [["dph_total", "asc"]],
        "limit": 20,
    }
    resp = await _request_with_retry(session, "POST", "/bundles/", json_data=body)
    if not _is_api_offers_list(resp):
        msg = f"Invalid offers list response: {resp}"
        raise VastAIError(msg)

    offers = resp["offers"]
    logger.debug("OFFER_SEARCH", extra={"offer_count": len(offers)})
    return offers


# endregion FUNC_search_offers


# region FUNC_select_cheapest_offer
# PURPOSE: First offer from the already-sorted list. Empty list → VastAINoOffersError. Price violating constraint → VastAIInvalidOfferError.
# REQUIRES: offers is a list of offers.
# ENSURES: Returns the cheapest valid offer; raises on empty or invalid.
async def select_cheapest_offer(
    offers: list[VastAIOffer],
    max_price_per_hr: float,
) -> VastAIOffer:
    """Select the cheapest compatible offer from a sorted list."""
    if not offers:
        msg = "No offers found matching the configured criteria"
        raise VastAINoOffersError(msg)

    # Not cheapest, but random from the top-5 cheapest
    # Don't fall into the same broken provider
    offer = random.choice(sorted(offers, key=lambda x: x["dph_total"])[:5])  # noqa: S311

    dph_total = offer["dph_total"]
    if dph_total > max_price_per_hr:
        msg = f"Offer price {dph_total} exceeds max price {max_price_per_hr}"
        raise VastAIInvalidOfferError(msg)

    logger.debug(
        "SELECTED_OFFER",
        extra={"offer_id": offer["id"], "dph_total": dph_total},
    )
    return offer


# endregion FUNC_select_cheapest_offer


# region FUNC_generate_onstart
# PURPOSE: Custom cfg.onstart_script verbatim if non-empty; otherwise cloud-init translation with package-manager detection.
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


class VastAICreateInstanceResponce(TypedDict):
    new_contract: int | float


def _is_api_create_instance_resp(
    resp: object,
) -> TypeGuard[VastAICreateInstanceResponce]:
    return isinstance(resp, dict) and isinstance(resp.get("new_contract"), (float, int))


async def _create_instance(
    session: aiohttp.ClientSession,
    offer_id: int,
    image: str,
    disk_gb: float,
    env: str | None,
    vm: bool,
    onstart: str | None,
    label: str = "yascheduler",
) -> int:
    json_data = {
        "image": image,
        "label": label,
        "dist": disk_gb,
        "runtype": "ssh_proxy",
        "target_state": "running",
        "cancel_unavail": True,
        "vm": vm,
    }
    if env:
        json_data["env"] = env
    if onstart:
        json_data["onstart"] = onstart
    resp = await _request_with_retry(session, "PUT", f"/asks/{offer_id}/", json_data)
    if not _is_api_create_instance_resp(resp):
        msg = f"Invalid create instance response: {resp}"
        raise VastAIError(msg)
    return int(resp["new_contract"])


async def _best_effort_delete(
    session: aiohttp.ClientSession,
    instance_id: int,
) -> None:
    """Best-effort delete an instance to prevent orphans.

    Swallows any exception so it never masks the original create error or
    skips the caller's error propagation. A transport error here does not
    re-raise: the caller's failure is the one that matters, and the orphan
    (if any) is the subject of a separate reconcile path.
    """
    try:
        logger.debug("ORPHAN_CLEANUP", extra={"instance_id": instance_id})
        await _request_with_retry(session, "DELETE", f"/instances/{instance_id}/")
    except Exception:  # best-effort cleanup must not mask caller error
        logger.warning("NODE %s NOT DELETED", instance_id)


# region FUNC__reconcile_orphan_by_label
# PURPOSE: Close the non-idempotent-create orphan window by matching and best-effort deleting an instance created during a failed/ambiguous PUT, using the unique label generated pre-PUT.
# ENSURES: Never raises — the original create error propagates regardless. Retries the listing _RECONCILE_ATTEMPTS times with a delay to cover listing-lag (instance not yet visible after PUT) and transient listing failures; on each tick a label match triggers best-effort delete, exhausting all attempts without a match logs a warning for manual reconciliation.
async def _reconcile_orphan_by_label(
    session: aiohttp.ClientSession,
    label: str,
) -> None:
    """Best-effort delete of an instance created during an ambiguous PUT.

    PUT /asks/{offer_id}/ is not idempotent: if the transport breaks after the
    server accepted the create, an instance exists that we never got an id for.
    Match it by the unique label generated pre-PUT and delete it. Never raises.
    """
    for attempt in range(1, _RECONCILE_ATTEMPTS + 1):
        try:
            instances = await _list_all_instances(session)
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
        orphan_id: int | float | None = None
        for inst in instances:
            if (
                isinstance(inst, dict)
                and inst.get("label") == label
                and isinstance(inst.get("id"), (int, float))
            ):
                orphan_id = inst["id"]
                break
        if orphan_id is not None:
            logger.warning(
                "RECONCILE_DELETE_ORPHAN",
                extra={"label": label, "instance_id": orphan_id},
            )
            await _best_effort_delete(session, int(orphan_id))
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
async def _verify_instance_gone(
    session: aiohttp.ClientSession,
    instance_id: str,
) -> bool:
    """Poll GET until the instance returns 404 or _DELETE_VERIFY_TIMEOUT expires.

    Returns True iff confirmed gone. Never raises.
    """
    deadline = asyncio.get_running_loop().time() + _DELETE_VERIFY_TIMEOUT
    while asyncio.get_running_loop().time() < deadline:
        try:
            resp = await _request(session, "GET", f"/instances/{instance_id}/")
        except VastAIError as err:
            if err.status == _HTTP_NOT_FOUND:
                logger.info("INSTANCE %s delete confirmed gone (404)", instance_id)
                return True
            logger.debug(
                "VERIFY_GET_RETRY",
                extra={"instance_id": instance_id, "status": err.status},
            )
            await asyncio.sleep(_DELETE_VERIFY_INTERVAL)
            continue
        # VastAI returns 200 with instances=null shortly after deletion (eventual
        # consistency): treat a missing/null instances field as gone.
        if not isinstance(resp, dict) or resp.get("instances") is None:
            logger.info(
                "INSTANCE %s delete confirmed gone (instances null)", instance_id
            )
            return True
        await asyncio.sleep(_DELETE_VERIFY_INTERVAL)
    logger.error(
        "INSTANCE %s STILL PRESENT %ss after accepted DELETE — "
        "manual deletion required via VastAI console",
        instance_id,
        _DELETE_VERIFY_TIMEOUT,
    )
    return False


# endregion FUNC__verify_instance_gone


class VastAIInstance(TypedDict):
    id: int | float
    actual_status: str | None
    ssh_host: str
    ssh_port: int | float


class VastAIShowInstanceResponce(TypedDict):
    instances: VastAIInstance | None


def _is_api_instance(resp: object) -> TypeGuard[VastAIInstance]:
    return (
        isinstance(resp, dict)
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


async def _show_instance(
    session: aiohttp.ClientSession,
    instance_id: int,
) -> VastAIInstance:
    resp = await _request_with_retry(session, "GET", f"/instances/{instance_id}/")
    if not _is_api_show_instance_resp(resp) or resp["instances"] is None:
        msg = f"Invalid show instance response: {resp}"
        raise VastAIError(msg)
    return resp["instances"]


# region FUNC_wait_until_ready
# PURPOSE: Return instance info when it's ready or remove failed instance.
# REQUIRES: session is an open aiohttp.ClientSession; instance_id is a valid instance id.
# ENSURES: raises VastAIInstanceCreateError on timeout, terminal status, or any show-instance failure that leaves the poll loop. Every exit path other than ready best-effort deletes the known instance id so no billable orphan leaks.
async def wait_until_ready(
    session: aiohttp.ClientSession,
    instance_id: int,
    timeout: float,
) -> VastAIInstance:
    """Poll until the VastAI instance is ready."""
    deadline = asyncio.get_running_loop().time() + timeout
    poll_interval = 5.0

    while True:
        now = asyncio.get_running_loop().time()
        if now >= deadline:
            logger.debug("POLL_TIMEOUT", extra={"instance_id": instance_id})
            await _best_effort_delete(session, instance_id)
            msg = f"Instance {instance_id} did not become ready within {timeout}s"
            raise VastAIInstanceCreateError(msg)

        try:
            inst = await _show_instance(session, instance_id)
        except asyncio.CancelledError:
            raise
        except VastAIError as err:
            # Any show-instance failure (persistent transport after retry
            # budget, 4xx, malformed response) leaves the poll loop without
            # the existing timeout/terminal cleanup. Delete the known
            # instance so it does not bill unbound, then re-raise.
            logger.debug(
                "POLL_SHOW_FAILED",
                extra={"instance_id": instance_id, "status": err.status},
            )
            await _best_effort_delete(session, instance_id)
            msg = f"Instance {instance_id} status query failed: {err}"
            raise VastAIInstanceCreateError(msg) from err
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
            await _best_effort_delete(session, instance_id)
            msg = f"Instance {instance_id} entered terminal status: {status}"
            raise VastAIInstanceCreateError(msg)

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

    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {cfg.api_key}"},
    ) as session:
        logger.debug("SSH_KEY_CHECK", extra={})
        await ensure_ssh_key(session, public_key)

        logger.debug("OFFER_SEARCH_START", extra={})
        offers = await search_offers(session, cfg)

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
            instance_id = await _create_instance(
                session,
                offer_id=offer["id"],
                image=cfg.image,
                disk_gb=cfg.disk_gb,
                env=cfg.docker_options,
                vm=mode == "kvm",
                onstart=onstart,
                label=create_label,
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
            await _reconcile_orphan_by_label(session, create_label)
            raise
        logger.debug("INSTANCE_CREATE", extra={"offer_id": offer["id"]})

        instance = await wait_until_ready(session, instance_id, cfg.connect_grace)
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
# PURPOSE: Tear down a VastAI instance by instance id so billing stops and the node slot is freed for reallocation.
# INVARIANTS:
# - external_id = instance id
# - Idempotent: already-deleted instance (DELETE 404) returns without raising.
# - Verifies the instance is gone after the DELETE is accepted: polls GET until 404. A 2xx DELETE (accepted, async removal) that never resolves to gone raises VastAIDeleteError so the caller leaves the DB row disabled for cross-cycle retry — no billable orphan from a falsely reported success.
async def vastai_delete_node(
    cfg: ConfigCloudVastAI,
    external_id: str,
) -> None:
    """Delete a VastAI GPU instance and verify it is gone."""
    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {cfg.api_key}"},
    ) as session:
        logger.debug("INSTANCE_DELETE", extra={"instance_id": external_id})
        try:
            await _request_with_retry(
                session,
                "DELETE",
                f"/instances/{external_id}/",
            )
        except VastAIError as exc:
            # 404 / already-deleted is idempotent success — nothing to verify.
            if exc.status == _HTTP_NOT_FOUND:
                return
            raise VastAIDeleteError(str(exc)) from exc

        # DELETE accepted (2xx). VastAI removal is eventually consistent: poll
        # GET until 404 so a 2xx does not imply a removed, non-billing instance.
        if not await _verify_instance_gone(session, external_id):
            msg = (
                f"Instance {external_id} delete not confirmed gone within "
                f"{_DELETE_VERIFY_TIMEOUT}s — cloud VM may still bill; "
                "orchestrator will retry next cycle"
            )
            raise VastAIDeleteError(msg)


# endregion FUNC_vastai_delete_node


# region FUNC_vastai_list_instances
# PURPOSE: List all VastAI instances matching cfg.label so the test can find and clean up orphaned billable instances that were not captured in observed_instance_ids.
# ENSURES: Returns a list of instance dicts with at least "id" and "actual_status".
async def _list_all_instances(session: aiohttp.ClientSession) -> list[dict]:
    """Return all VastAI instances (raw, unfiltered)."""
    resp = await _request_with_retry(session, "GET", "/instances/")
    if not isinstance(resp, dict) or "instances" not in resp:
        logger.warning(
            "LIST_INSTANCES_UNEXPECTED",
            extra={"response_type": type(resp).__name__},
        )
        return []
    instances = resp["instances"]
    if not isinstance(instances, list):
        logger.warning(
            "LIST_INSTANCES_UNEXPECTED",
            extra={"response_type": type(instances).__name__},
        )
        return []
    return instances


async def vastai_list_instances(
    cfg: ConfigCloudVastAI,
) -> list[dict]:
    """List all VastAI instances matching cfg.label."""
    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {cfg.api_key}"},
    ) as session:
        instances = await _list_all_instances(session)
        matched = [
            inst
            for inst in instances
            if isinstance(inst, dict) and inst.get("label") == cfg.label
        ]
        logger.debug(
            "LIST_INSTANCES",
            extra={
                "total": len(instances),
                "matched": len(matched),
                "label": cfg.label,
            },
        )
        return matched


# endregion FUNC_vastai_list_instances
