"""Hetzner cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission Hetzner Cloud servers so the scheduler can run compute workloads on Hetzner through the generic CloudAdapter contract.
# SCOPE: Hetzner create/delete node functions with orphan-prevention (per-create reconcile-token label for non-idempotent POST) and transient-error propagation to the orchestrator's retry loop.
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
    from collections.abc import AsyncIterator

    from asyncssh.public_key import SSHKey as ASSHKey

    from yascheduler.infra.cloud import ConfigCloudHetzner
    from yascheduler.shared import Self, TypeGuard, Unpack


__all__ = ["HetznerError", "hetzner_create_node", "hetzner_delete_node"]
logger = logging.getLogger(__name__)

_HETZNER_BASE_URL = "https://api.hetzner.cloud/v1"
_HTTP_BAD_REQUEST = 400
_HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500

_RECONCILE_ATTEMPTS = 3
_RECONCILE_INTERVAL = 5.0
_RECONCILE_LABEL_KEY = "yascheduler/reconcile"


# region BLOCK_API_errors
# PURPOSE: Hetzner API error type carrying the HTTP status, with a transient classifier for retry decisions.
class HetznerError(Exception):
    """Hetzner API error carrying the HTTP status.

    `status` is the HTTP status when the error originated from an HTTP
    response, or None for transport-level failures.
    """

    def __init__(
        self,
        message: str,
        status: int | None = None,
    ) -> None:
        self.status = status
        super().__init__(message)

    @property
    def transient(self) -> bool:
        """True for 429/5xx responses and transport failures — worth retrying."""
        return (
            self.status is None
            or self.status == _HTTP_TOO_MANY_REQUESTS
            or self.status >= _HTTP_SERVER_ERROR
        )


# endregion BLOCK_API_errors


# region BLOCK_API_typed_dicts
# PURPOSE: TypedDict mirrors of the Hetzner REST API response/request shapes used by create, list, and SSH-key endpoints, so client methods and validators share one structural contract.
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


class HetznerServerPublicNet(TypedDict):
    ipv4: HetznerServerIpv4


class HetznerServer(TypedDict):
    id: int
    name: str
    public_net: HetznerServerPublicNet
    labels: dict[str, str]


class HetznerCreateServerRequest(TypedDict):
    name: str
    server_type: str
    image: str
    ssh_keys: list[int]
    user_data: str
    location: str
    labels: dict[str, str]


class HetznerCreateServerResponse(TypedDict):
    server: HetznerServer


class HetznerListServersResponse(TypedDict):
    servers: list[HetznerServer]


# endregion BLOCK_API_typed_dicts


# region BLOCK_API_validators
# PURPOSE: TypeGuard validators narrowing untyped API JSON to the TypedDict shapes above, so client methods fail fast on shape drift with a HetznerError rather than silently misreading fields.
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


def _is_api_public_net(obj: object) -> TypeGuard[HetznerServerPublicNet]:
    return isinstance(obj, dict) and "ipv4" in obj and _is_api_ipv4(obj["ipv4"])


def _is_api_server(obj: object) -> TypeGuard[HetznerServer]:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("id"), int)
        and isinstance(obj.get("name"), str)
        and "public_net" in obj
        and _is_api_public_net(obj["public_net"])
        and isinstance(obj.get("labels"), dict)
    )


def _is_api_create_server_response(
    obj: object,
) -> TypeGuard[HetznerCreateServerResponse]:
    return isinstance(obj, dict) and "server" in obj and _is_api_server(obj["server"])


def _is_api_servers_list_response(obj: object) -> TypeGuard[HetznerListServersResponse]:
    return (
        isinstance(obj, dict)
        and "servers" in obj
        and all(_is_api_server(x) for x in obj["servers"])
    )


# endregion BLOCK_API_validators


# region CLASS_HetznerClient
# PURPOSE: Wrap a single aiohttp session authenticated to the Hetzner API so repeated create/poll/delete calls reuse one connection pool instead of re-handshaking per request.
class HetznerClient:
    """Async Hetzner REST API client (aiohttp-based)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._session = aiohttp.ClientSession(
            base_url=_HETZNER_BASE_URL,
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

    # region METHOD_request
    async def _request(
        self,
        method: str,
        path: str,
        params: aiohttp.typedefs.Query | None = None,
        data: dict | None = None,
    ) -> object:
        """Send an async HTTP request to the Hetzner API v1 and return parsed JSON."""
        try:
            async with self._session.request(
                method, path, params=params, json=data
            ) as resp:
                if resp.status >= _HTTP_BAD_REQUEST:
                    msg = f"HTTP {resp.status}: {await resp.text()}"
                    raise HetznerError(msg, status=resp.status)
                return await resp.json()
        except aiohttp.ClientResponseError as exc:
            msg = f"HTTP request failed: {exc.message}"
            raise HetznerError(msg, status=exc.status) from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            msg = f"Transport error: {exc}"
            raise HetznerError(msg) from exc

    # endregion METHOD_request

    # region METHOD_get_next_page
    def _get_next_page(self, resp: dict) -> int | None:
        "Return meta.pagination.next_page or None."
        return resp.get("meta", {}).get("pagination", {}).get("next_page")

    # endregion METHOD_get_next_page

    # region METHOD_get_ssh_keys
    async def get_ssh_keys(
        self, fingerprint: str | None = None, per_page: int = 25
    ) -> AsyncIterator[HetznerSshKey]:
        params: dict[str, int | str] = {"page": 1, "per_page": per_page}
        if fingerprint:
            params["fingerprint"] = fingerprint
        while True:
            resp = await self._request("GET", "/ssh_keys", params=params)
            if not _is_api_ssh_keys_list_response(resp):
                msg = f"Invalid SSH keys list response: {resp}"
                raise HetznerError(msg)
            for key in resp["ssh_keys"]:
                yield key
            if not (next_page := self._get_next_page(dict(resp))):
                break
            params["page"] = next_page

    # endregion METHOD_get_ssh_keys

    # region METHOD_create_ssh_key
    async def create_ssh_key(self, name: str, public_key: str) -> HetznerSshKey:
        data = {"name": name, "public_key": public_key, "label": "yascheduler key"}
        resp = await self._request("POST", "/ssh_keys", data=data)
        if not _is_api_ssh_key_create_response(resp):
            msg = f"Invalid create SSH key response: {resp}"
            raise HetznerError(msg)
        return resp["ssh_key"]

    # endregion METHOD_create_ssh_key

    # region METHOD_get_servers
    async def get_servers(
        self, label_selector: str | None = None, per_page: int = 25
    ) -> AsyncIterator[HetznerServer]:
        params: dict[str, int | str] = {"page": 1, "per_page": per_page}
        if label_selector:
            params["label_selector"] = label_selector
        while True:
            resp = await self._request("GET", "/servers", params=params)
            if not _is_api_servers_list_response(resp):
                msg = f"Invalid servers list response: {resp}"
                raise HetznerError(msg)
            for server in resp["servers"]:
                yield server
            if not (next_page := self._get_next_page(dict(resp))):
                break
            params["page"] = next_page

    # endregion METHOD_get_servers

    # region METHOD_create_server
    async def create_server(
        self, **server_params: Unpack[HetznerCreateServerRequest]
    ) -> HetznerServer:
        resp = await self._request("POST", "/servers", data=dict(server_params))
        if not _is_api_create_server_response(resp):
            msg = f"Invalid create server response: {resp}"
            raise HetznerError(msg)
        return resp["server"]

    # endregion METHOD_create_server

    # region METHOD_delete_server
    async def delete_server(self, server_id: int) -> None:
        await self._request("DELETE", f"/servers/{server_id}")

    # endregion METHOD_delete_server


# endregion CLASS_HetznerClient


# region FUNC__resolve_ssh_key_by_fingerprint
# PURPOSE: Resolve an existing SSH key ID by fingerprint query
async def _resolve_ssh_key_by_fingerprint(
    client: HetznerClient, key: ASSHKey
) -> int | None:
    """Resolve an existing SSH key ID by fingerprint query."""
    # asyncssh returns "MD5:aa:bb:cc:..."; Hetzner expects "aa:bb:cc:...".
    fingerprint = key.get_fingerprint("md5").split(":", maxsplit=1)[1]
    async for ssh_key in client.get_ssh_keys(fingerprint=fingerprint):
        return ssh_key["id"]
    return None


# endregion FUNC__resolve_ssh_key_by_fingerprint


# region FUNC_ensure_ssh_key
# PURPOSE: Ensure the local SSH key is registered with the Hetzner project, returning its key ID.
# REQUIRES: client is an open HetznerClient; key is an asyncssh SSHKey.
# ENSURES: Returns the Hetzner SSH key ID; idempotent across repeated calls (dedup on conflict).
# RATIONALE:
# - Q: Why GET-by-fingerprint first, then POST on miss?
#   A: The same key is reused, so the already-registered case is the common path
#      and costs a single GET.
async def ensure_ssh_key(client: HetznerClient, key: ASSHKey, key_name: str) -> int:
    """Ensure the SSH key is registered with Hetzner; return its key ID."""
    # Common path: the key is already registered (reused across restarts).
    key_id = await _resolve_ssh_key_by_fingerprint(client, key)
    if key_id is not None:
        return key_id
    pub_key = key.export_public_key("openssh").decode("utf-8")
    hetzner_key = await client.create_ssh_key(key_name, pub_key)
    return hetzner_key["id"]


# endregion FUNC_ensure_ssh_key


# region FUNC_hetzner_create_node
# PURPOSE: Provision a Hetzner server via the CloudAdapter interface so the generic provisioner can launch Hetzner compute nodes.
# ENSURES:
# - On success returns CloudCreateNodeDTO with external_id = str(server.id), hostname = IPv4.
# INVARIANTS:
# - external_id = numeric server ID; client closed on all paths.
# - On any create_server failure, best-effort reconcile by the per-create
#   label deletes an already-created server so no billable orphan leaks; the
#   original error re-raises regardless.
# RATIONALE:
# - Q: Why inject `users` into cloud-init when ssh_keys already passes the key?
#   A: Hetzner's ssh_keys only inject into root; a non-root cfg.username must be created by cloud-init. root is listed too for determinism. Mirrors vultr's build_users.
# - Q: Why reconcile by label rather than by server name, when both carry the same unique random value?
#   A: get_servers supports server-side filtering by label_selector, so the reconcile lists only the candidate server. The unique random label value scopes the match to exactly the server this create produced.
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

    async with HetznerClient(cfg.token) as client:
        key_name = get_key_name(key)
        ssh_key_id = await ensure_ssh_key(client, key, key_name)

        # Unique per-create label: POST /servers is not idempotent, so a transport
        # break after the server accepted the create loses the returned id. The
        # same value is used for the server name and the reconcile label, so an
        # already-created server can be matched and deleted without its id.
        label = get_rnd_name(cfg.label)
        try:
            server = await client.create_server(
                name=label,
                server_type=cfg.server_type,
                image=cfg.image_name,
                ssh_keys=[ssh_key_id],
                user_data=user_data,
                location=cfg.location,
                labels={_RECONCILE_LABEL_KEY: label},
            )
        except Exception:
            logger.warning(
                "CREATE_SERVER_FAILED — reconciling by label %s",
                label,
            )
            await _reconcile_orphan_by_label(client, label)
            raise
        server_id = server["id"]
        ip_str = server["public_net"]["ipv4"]["ip"]

        logger.info("CREATED %s", ip_str)
        return CloudCreateNodeDTO(
            external_id=str(server_id),
            hostname=ip_str,
            username=cfg.username,
            jump_host=cfg.jump_host,
            jump_port=cfg.jump_port,
            jump_username=cfg.jump_username or "root",
        )


# endregion FUNC_hetzner_create_node


# region FUNC__reconcile_orphan_by_label
# PURPOSE: Close the non-idempotent-create orphan window by matching and best-effort deleting a server created during a failed/ambiguous POST, using the unique label stamped on the create request.
# ENSURES: Never raises — the original create error propagates regardless. Retries the listing _RECONCILE_ATTEMPTS times with a delay to cover listing-lag (server not yet visible after POST) and transient listing failures; on each tick a label match triggers best-effort delete, exhausting all attempts without a match logs a warning for manual reconciliation.
async def _reconcile_orphan_by_label(
    client: HetznerClient,
    label: str,
) -> None:
    """Best-effort delete of a server created during an ambiguous POST.

    POST /servers is not idempotent: if the transport breaks after the server
    accepted the create, a server exists that we never got an id for. Match it
    by the unique label and delete it. Never raises.
    """
    label_selector = f"{_RECONCILE_LABEL_KEY}={label}"
    for attempt in range(1, _RECONCILE_ATTEMPTS + 1):
        orphan_id: int | None = None
        try:
            async for server in client.get_servers(label_selector=label_selector):
                orphan_id = server["id"]
                break
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
                extra={"label": label, "server_id": orphan_id},
            )
            try:
                await client.delete_server(orphan_id)
            except HetznerError as exc:
                if exc.status == _HTTP_NOT_FOUND:
                    return
                logger.exception(
                    "RECONCILE_DELETE_FAILED — potential orphan billing; manual check needed",
                    extra={"label": label, "server_id": orphan_id},
                )
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


# region FUNC_hetzner_delete_node
# PURPOSE: Tear down a Hetzner server by server ID so billing stops and the node slot is freed for reallocation.
# INVARIANTS:
# - Resolves deletion by numeric server ID via DELETE /servers/{id}.
# - HetznerError with status=404 is logged and returns without error (idempotent no-op).
# - All other errors propagate to the caller.
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

    async with HetznerClient(cfg.token) as client:
        logger.debug("INSTANCE_DELETE", extra={"server_id": server_id})
        try:
            await client.delete_server(server_id)
        except HetznerError as exc:
            if exc.status == _HTTP_NOT_FOUND:
                logger.warning("NODE %s NOT DELETED AS UNKNOWN", server_id)
                return
            raise


# endregion FUNC_hetzner_delete_node
