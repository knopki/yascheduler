"""Hetzner cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission Hetzner Cloud servers so the scheduler can run compute workloads on Hetzner through the generic CloudAdapter contract.
# SCOPE: Hetzner create/delete node functions with orphan-prevention and transient-error retry.
# DEPENDENCIES: USES API: aiohttp (Hetzner Cloud REST API v1); WRITES: HTTP to Hetzner API (server/SSH key create/delete)
# KEYWORDS: hetzner, cloud, server, create, delete, api, ssh key, retry, orphan
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, TypedDict

import aiohttp

from yascheduler.infra.cloud import (
    CloudCreateNodeDTO,
    CloudInitConfig,
    build_cloud_init_users,
    get_key_name,
    get_rnd_name,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from asyncssh.public_key import SSHKey as ASSHKey

    from yascheduler.infra.cloud import ConfigCloudHetzner
    from yascheduler.shared import TypeGuard

__all__ = ["HetznerError", "hetzner_create_node", "hetzner_delete_node"]
logger = logging.getLogger(__name__)

_HETZNER_BASE_URL = "https://api.hetzner.cloud/v1"
_HTTP_BAD_REQUEST = 400
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "DELETE", "OPTIONS"})
_RETRY_MAX_TIME = 60.0
_RETRY_INITIAL_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0
_RETRY_FACTOR = 1.5


# region BLOCK_Hetzner_API_types
# PURPOSE: Abstract Hetzner API types
class HetznerError(Exception):
    """Hetzner API error carrying the Hetzner error code and HTTP status."""

    def __init__(
        self,
        message: str,
        code: str | None = None,
        status: int | None = None,
    ) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


class HetznerSshKey(TypedDict):
    id: int
    name: str
    fingerprint: str


class HetznerSshKeyCreateResponse(TypedDict):
    ssh_key: HetznerSshKey


class HetznerSshKeysListResponse(TypedDict):
    ssh_keys: list[HetznerSshKey]


class HetznerServerIpv4(TypedDict):
    ip: str


class HetznerServerPublicNet(TypedDict, total=False):
    ipv4: HetznerServerIpv4


class HetznerServer(TypedDict, total=False):
    id: int
    name: str
    public_net: HetznerServerPublicNet


class HetznerCreateServerResponse(TypedDict):
    server: HetznerServer


def _is_api_ssh_key(obj: object) -> TypeGuard[HetznerSshKey]:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("id"), int)
        and isinstance(obj.get("name"), str)
        and isinstance(obj.get("fingerprint"), str)
    )


def _is_api_ssh_key_create_response(
    obj: object,
) -> TypeGuard[HetznerSshKeyCreateResponse]:
    return (
        isinstance(obj, dict) and "ssh_key" in obj and _is_api_ssh_key(obj["ssh_key"])
    )


def _is_api_ssh_keys_list_response(
    obj: object,
) -> TypeGuard[HetznerSshKeysListResponse]:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("ssh_keys"), list)
        and all(_is_api_ssh_key(k) for k in obj["ssh_keys"])
    )


def _is_api_ipv4(obj: object) -> TypeGuard[HetznerServerIpv4]:
    return isinstance(obj, dict) and isinstance(obj.get("ip"), str)


def _is_api_server(obj: object) -> TypeGuard[HetznerServer]:
    return isinstance(obj, dict) and isinstance(obj.get("id"), int)


def _is_api_create_server_response(
    obj: object,
) -> TypeGuard[HetznerCreateServerResponse]:
    return isinstance(obj, dict) and "server" in obj and _is_api_server(obj["server"])


# region FUNC__request
# PURPOSE: Make an HTTP request to the Hetzner API, parsing Hetzner's error envelope into HetznerError on non-2xx.
# REQUIRES: session is an open aiohttp.ClientSession authenticated with a Bearer token.
# ENSURES: raises HetznerError on non-2xx (carrying error.code + HTTP status) or on transport failure (status=None).
async def _request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    json_data: object | None = None,
    params: dict[str, str] | None = None,
) -> dict | list:
    """Make an HTTP request to the Hetzner Cloud API v1."""
    url = f"{_HETZNER_BASE_URL}{path}"
    kwargs: dict = {}
    if json_data is not None:
        kwargs["json"] = json_data
    if params is not None:
        kwargs["params"] = params

    try:
        async with session.request(method, url, **kwargs) as resp:
            logger.debug(
                "HETZNER_REQUEST",
                extra={"method": method, "path": path, "status": resp.status},
            )
            if resp.status >= _HTTP_BAD_REQUEST:
                try:
                    body = await resp.json()
                except Exception:
                    body = {}
                code = None
                message = f"HTTP {resp.status}"
                if isinstance(body, dict):
                    err = body.get("error")
                    if isinstance(err, dict):
                        raw_code = err.get("code")
                        code = raw_code if isinstance(raw_code, str) else None
                        raw_message = err.get("message")
                        message = (
                            raw_message if isinstance(raw_message, str) else message
                        )
                raise HetznerError(message, code=code, status=resp.status)

            try:
                return await resp.json()
            except Exception as exc:
                msg = f"Invalid JSON response: {exc}"
                raise HetznerError(msg) from exc
    except asyncio.CancelledError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        # status=None marks a transport error so the retry layer can retry it
        # for idempotent calls (GET/DELETE) without retrying the
        # non-idempotent POST create, which would double-create a billed server.
        msg = f"Transport error: {exc}"
        raise HetznerError(msg, status=None) from exc


# endregion FUNC__request


# region FUNC__request_with_retry
# PURPOSE: Wrapper around _request that retries transient errors with exponential backoff.
# ENSURES:
# - 429 retried for all methods (rate-limited requests never execute server-side).
# - Transport errors and 5xx retried ONLY for idempotent methods (GET/HEAD/DELETE/OPTIONS).
#   Retrying the non-idempotent POST create on an uncertain outcome would
#   double-create a billed server, so mutating POST/PUT are NOT retried on
#   transport/5xx (only on 429).
def _is_retryable(method: str, exc: HetznerError) -> bool:
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
    params: dict[str, str] | None = None,
) -> dict | list:
    """Make an HTTP request with method-aware retry on transient errors."""
    deadline = asyncio.get_running_loop().time() + _RETRY_MAX_TIME
    delay = _RETRY_INITIAL_DELAY
    while True:
        try:
            return await _request(session, method, path, json_data, params)
        except asyncio.CancelledError:
            raise
        except HetznerError as exc:
            if not _is_retryable(method, exc):
                raise
            if asyncio.get_running_loop().time() >= deadline:
                logger.debug("DEADLINE", extra={"exc": str(exc)})
                raise
            logger.debug("RETRY", extra={"exc": str(exc), "delay": delay})
        await asyncio.sleep(delay)
        delay = min(delay * _RETRY_FACTOR, _RETRY_MAX_DELAY)


# endregion FUNC__request_with_retry


# region FUNC__resolve_ssh_key_by_fingerprint
# PURPOSE: Resolve an existing SSH key ID by fingerprint query
async def _resolve_ssh_key_by_fingerprint(
    session: aiohttp.ClientSession, key: ASSHKey
) -> int | None:
    """Resolve an existing SSH key ID by fingerprint query."""
    # asyncssh returns "MD5:aa:bb:cc:..."; Hetzner expects "aa:bb:cc:...".
    fingerprint = key.get_fingerprint("md5").split(":", maxsplit=1)[1]
    resp = await _request_with_retry(
        session, "GET", "/ssh_keys", params={"fingerprint": fingerprint}
    )
    if not _is_api_ssh_keys_list_response(resp):
        msg = f"Invalid SSH keys list response: {resp}"
        raise HetznerError(msg)
    if resp["ssh_keys"]:
        return resp["ssh_keys"][0]["id"]
    return None


# endregion FUNC__resolve_ssh_key_by_fingerprint


# region FUNC__resolve_ssh_key_by_name
# PURPOSE: Resolve an existing SSH key ID by name query
async def _resolve_ssh_key_by_name(
    session: aiohttp.ClientSession, key_name: str
) -> int | None:
    """Resolve an existing SSH key ID by name query."""
    resp = await _request_with_retry(
        session, "GET", "/ssh_keys", params={"name": key_name}
    )
    if not _is_api_ssh_keys_list_response(resp):
        msg = f"Invalid SSH keys list response: {resp}"
        raise HetznerError(msg)
    if resp["ssh_keys"]:
        return resp["ssh_keys"][0]["id"]
    return None


# endregion FUNC__resolve_ssh_key_by_name


# region FUNC_ensure_ssh_key
# PURPOSE: Ensure the local SSH key is registered with the Hetzner project, returning its key ID.
# REQUIRES: session is an open aiohttp.ClientSession; key is an asyncssh SSHKey.
# ENSURES: Returns the Hetzner SSH key ID; idempotent across repeated calls (dedup on conflict).
# RATIONALE:
# - Q: Why GET-by-fingerprint first, then POST on miss, then 409-handling?
#   A: The same key is reused, so the already-registered case is the common path
#      and costs a single GET.
async def ensure_ssh_key(
    session: aiohttp.ClientSession, key: ASSHKey, key_name: str
) -> int:
    """Ensure the SSH key is registered with Hetzner; return its key ID."""
    # Common path: the key is already registered (reused across restarts).
    key_id = await _resolve_ssh_key_by_fingerprint(session, key)
    if key_id is not None:
        return key_id

    pub_key = key.export_public_key("openssh").decode("utf-8")
    resp = await _request(
        session,
        "POST",
        "/ssh_keys",
        json_data={"name": key_name, "public_key": pub_key},
    )
    if not _is_api_ssh_key_create_response(resp):
        msg = f"Invalid SSH key create response: {resp}"
        raise HetznerError(msg)
    return resp["ssh_key"]["id"]


# endregion FUNC_ensure_ssh_key


# region FUNC__extract_ipv4
# PURPOSE: Safely extract the public IPv4 from the create-server response, returning None when the shape is absent (anomaly) so the caller can surface a deterministic error and clean up.
def _extract_ipv4(server: Mapping[str, object]) -> str | None:
    public_net = server.get("public_net")
    if not isinstance(public_net, dict):
        return None
    ipv4 = public_net.get("ipv4")
    if not _is_api_ipv4(ipv4):
        return None
    return ipv4["ip"]


# endregion FUNC__extract_ipv4


# region FUNC__best_effort_delete
# PURPOSE: Best-effort delete a Hetzner server by ID, swallowing all errors so it can be used in create-failure cleanup paths where the original error must propagate.
async def _best_effort_delete(
    session: aiohttp.ClientSession,
    server_id: int,
) -> None:
    """Best-effort delete; never raises. Used by create_node cleanup."""
    try:
        logger.debug("ORPHAN_CLEANUP", extra={"server_id": server_id})
        await _request_with_retry(session, "DELETE", f"/servers/{server_id}")
    except Exception:  # best-effort cleanup must not mask caller error
        logger.warning("NODE %s NOT DELETED", server_id)


# endregion FUNC__best_effort_delete


# region FUNC_hetzner_create_node
# PURPOSE: Provision a Hetzner server via the CloudAdapter interface so the generic provisioner can launch Hetzner compute nodes.
# ENSURES:
# - On success returns CloudCreateNodeDTO with external_id = str(server.id), hostname = IPv4.
# - On ANY failure AFTER POST /servers returns a server.id, the server is best-effort deleted via _best_effort_delete so no billable orphan leaks.
# INVARIANTS: external_id = numeric server ID; session closed on all paths.
# RATIONALE:
# - Q: Why inject `users` into cloud-init when ssh_keys already passes the key?
#   A: Hetzner's ssh_keys only inject into root; a non-root cfg.username must be created by cloud-init. root is listed too for determinism. Mirrors vultr's build_users.
async def hetzner_create_node(
    cfg: ConfigCloudHetzner,
    key: ASSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create node."""
    pub_key = key.export_public_key("openssh").decode("utf-8")
    user_data = replace(
        cloud_config or CloudInitConfig(),
        users=build_cloud_init_users(cfg.username, pub_key),
    ).render()

    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {cfg.token}"}
    ) as session:
        # region BLOCK_register_ssh_key
        key_name = get_key_name(key)
        ssh_key_id = await ensure_ssh_key(session, key, key_name)
        # endregion BLOCK_register_ssh_key

        # region BLOCK_create_server
        # POST /servers is non-idempotent — NOT retried on transport/5xx to
        # avoid double-creating a billed server. Hetzner accepts ssh_keys as
        # an array of integer IDs.
        create_body: dict = {
            "name": get_rnd_name(cfg.label),
            "server_type": cfg.server_type,
            "image": cfg.image_name,
            "ssh_keys": [ssh_key_id],
            "user_data": user_data,
        }
        if cfg.location:
            create_body["location"] = cfg.location

        resp = await _request(session, "POST", "/servers", json_data=create_body)
        if not _is_api_create_server_response(resp):
            msg = f"Invalid create server response: {resp}"
            raise HetznerError(msg)
        server = resp["server"]
        server_id = server["id"]
        # endregion BLOCK_create_server

        # region BLOCK_extract_and_cleanup
        try:
            # region BLOCK_extract_ip
            ip_str = _extract_ipv4(server)
            if not ip_str:
                # Hetzner normally returns the IPv4 synchronously in the create
                # response. A missing IP here is an anomaly (API hiccup or race)
                # — surface as a deterministic error and clean up.
                msg = (
                    f"Hetzner server {server_id} created without a public IPv4 "
                    f"address — cannot proceed without a routable host"
                )
                raise RuntimeError(msg)  # noqa: TRY301
            # endregion BLOCK_extract_ip
        except Exception:
            logger.exception("CREATE_FAILED_CLEANUP", extra={"server_id": server_id})
            await _best_effort_delete(session, server_id)
            raise

        logger.info("CREATED %s", ip_str)
        return CloudCreateNodeDTO(
            external_id=str(server_id),
            hostname=ip_str,
            username=cfg.username,
            jump_host=cfg.jump_host,
            jump_port=cfg.jump_port,
            jump_username=cfg.jump_username or "root",
        )
        # endregion BLOCK_extract_and_cleanup


# endregion FUNC_hetzner_create_node


# region FUNC_hetzner_delete_node
# PURPOSE: Tear down a Hetzner server by server ID so billing stops and the node slot is freed for reallocation.
# INVARIANTS:
# - Resolves deletion by numeric server ID via DELETE /servers/{id} (idempotent, retried on transient errors).
# - HetznerError(code="not_found" / status=404) is logged and returns without error (idempotent no-op).
# - DELETE is retried by _request_with_retry on transport/5xx; a transport-ambiguous DELETE naturally resolves via 404 on the retry.
async def hetzner_delete_node(
    cfg: ConfigCloudHetzner,
    external_id: str,
) -> None:
    """Delete node."""
    try:
        server_id = int(external_id)
    except (TypeError, ValueError) as err:
        msg = f"Invalid Hetzner server id {external_id!r}: {err}"
        raise RuntimeError(msg) from err

    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {cfg.token}"},
    ) as session:
        logger.debug("INSTANCE_DELETE", extra={"server_id": server_id})
        try:
            await _request_with_retry(session, "DELETE", f"/servers/{server_id}")
        except HetznerError as exc:
            if exc.code == "not_found" or exc.status == _HTTP_NOT_FOUND:
                logger.warning("NODE %s NOT DELETED AS UNKNOWN", server_id)
                return
            raise


# endregion FUNC_hetzner_delete_node
