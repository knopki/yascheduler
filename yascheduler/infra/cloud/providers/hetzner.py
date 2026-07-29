"""Hetzner cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission Hetzner Cloud servers so the scheduler can run compute workloads on Hetzner through the generic CloudAdapter contract.
# SCOPE: Hetzner create/delete node functions with orphan-prevention and transient-error retry.
# DEPENDENCIES: USES API: hcloud (Hetzner Cloud SDK); WRITES: HTTP to Hetzner API (server/SSH key create/delete)
# KEYWORDS: hetzner, cloud, server, create, delete, api, ssh key, retry, orphan
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures.thread import ThreadPoolExecutor
from dataclasses import replace
from functools import cache, partial
from typing import TYPE_CHECKING, cast

import requests.exceptions
from hcloud import APIException
from hcloud import Client as HClient
from hcloud.images.domain import Image
from hcloud.locations.domain import Location
from hcloud.server_types.domain import ServerType
from hcloud.servers.domain import Server as DomainServer
from hcloud.ssh_keys.domain import SSHKey as HSSHKey

from yascheduler.infra.cloud import (
    CloudCreateNodeDTO,
    CloudInitConfig,
    build_cloud_init_users,
    get_key_name,
    get_rnd_name,
)

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey as ASSHKey

    from yascheduler.infra.cloud import ConfigCloudHetzner

__all__ = ["hetzner_create_node", "hetzner_delete_node"]
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=5)

# After an accepted DELETE, poll GET until the server returns not_found
# (Hetzner DELETE is synchronous, but a transient 5xx right after the
# 202-class would otherwise leave state unverified).
DELETE_VERIFY_TIMEOUT = 60
DELETE_VERIFY_INTERVAL = 2
DELETE_RETRY_ATTEMPTS = 3
DELETE_RETRY_INTERVAL = 2


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


# region FUNC__is_transient
# PURPOSE: Classify hcloud/requests failures worth retrying so delete is resilient to transient network or 5xx flaps while permanent errors surface immediately.
def _is_transient(err: Exception) -> bool:
    """Return True for transient hcloud/requests errors worth retrying.

    - requests transport errors (ConnectionError, Timeout): network-level.
    - APIException with int code 500/502/503/504 or str code
      rate_limit_exceeded/timeout/conflict: server-side or rate-limited.
    Note: hcloud already retries 502/504 + rate_limit_exceeded/conflict/timeout
    up to 5 times internally; this is a second line for the cases hcloud gives
    up on (exhausted internal retries) or doesn't classify (500, 503, transport).
    """
    if isinstance(err, requests.exceptions.Timeout):
        return True
    if isinstance(err, requests.exceptions.ConnectionError):
        return True
    if isinstance(err, APIException):
        if isinstance(err.code, int):
            return err.code in (500, 502, 503, 504)
        if isinstance(err.code, str):
            return err.code in ("rate_limit_exceeded", "timeout", "conflict")
    return False


# endregion FUNC__is_transient


# region FUNC__safe_delete_server
# PURPOSE: Best-effort delete a Hetzner server by ID, swallowing all errors so it can be used in failure-cleanup paths where the original error must propagate.
def _safe_delete_server(client: HClient, server_id: int) -> None:
    """Best-effort delete; never raises. Used by create_node cleanup.

    Builds a domain Server directly to avoid an extra GET (fewer failure
    points). The SDK ServersClient.delete uses only server.id.
    """
    try:
        client.servers.delete(DomainServer(id=server_id))
    except Exception as err:  # best-effort cleanup, never raise
        logger.warning(
            "CLEANUP_DELETE_FAILED",
            extra={"server_id": server_id, "error": str(err)},
        )


# endregion FUNC__safe_delete_server


# region FUNC__delete_server_with_retry
# PURPOSE: Delete a Hetzner server with transient-error retry and post-delete verification so neither create_node cleanup nor deallocate leaks a billable orphan when Hetzner flaps or returns 5xx.
# ENSURES:
# - APIException(code="not_found") is logged and returns without error (idempotent no-op).
# - Transient errors are retried up to DELETE_RETRY_ATTEMPTS; permanent errors raise immediately.
# - After an accepted DELETE, polls get_by_id until not_found (confirmed gone) or DELETE_VERIFY_TIMEOUT.
# - Never claims success without a not_found confirmation; on verify timeout logs ERROR for manual intervention.
# MODEL: Hetzner DELETE /servers/{id} is synchronous (the resource is gone by the time the 2xx returns), but a transient transport/5xx error on the DELETE response leaves "accepted-but-unconfirmed". The verify loop confirms the deletion against the actual state.
def _delete_server_with_retry(client: HClient, server_id: int) -> None:
    """Delete a Hetzner server with retry + verification; never silently leak."""
    # region BLOCK_delete
    delete_accepted = False
    for attempt in range(1, DELETE_RETRY_ATTEMPTS + 1):
        try:
            client.servers.delete(DomainServer(id=server_id))
            delete_accepted = True
            break
        except APIException as err:
            if err.code == "not_found":
                # region BLOCK_not_found_noop
                logger.warning(
                    "NODE %s NOT DELETED AS UNKNOWN",
                    server_id,
                )
                return
                # endregion BLOCK_not_found_noop
            if _is_transient(err) and attempt < DELETE_RETRY_ATTEMPTS:
                logger.debug(
                    "DELETE_TRANSIENT_RETRY",
                    extra={
                        "server_id": server_id,
                        "attempt": attempt,
                        "attempts": DELETE_RETRY_ATTEMPTS,
                        "error": str(err),
                    },
                )
                time.sleep(DELETE_RETRY_INTERVAL)
                continue
            raise
        except requests.exceptions.Timeout as err:
            # Ambiguous: server may or may not have been deleted before the
            # timeout. We must verify instead of assuming failure — otherwise
            # an already-deleted server would cause a re-raise and orphan
            # accounting downstream. Fall through to verify.
            logger.debug(
                "DELETE_TIMEOUT",
                extra={"server_id": server_id, "error": str(err)},
            )
            delete_accepted = True  # treat as "maybe deleted, verify"
            break
        except requests.exceptions.ConnectionError as err:
            # Ambiguous transport failure: same as Timeout — verify.
            logger.debug(
                "DELETE_CONN_ERROR",
                extra={"server_id": server_id, "error": str(err)},
            )
            delete_accepted = True
            break
    # endregion BLOCK_delete

    if not delete_accepted:
        # Loop exhausted without break — should not happen given the above,
        # but defensive: nothing more to do here; last transient raised already.
        return

    # region BLOCK_verify
    deadline = _monotonic() + DELETE_VERIFY_TIMEOUT
    while _monotonic() < deadline:
        try:
            client.servers.get_by_id(server_id)
            # Server still present after accepted DELETE — keep polling.
        except APIException as err:
            if err.code == "not_found":
                logger.info("DELETED %s", server_id)
                return
            # Transient verify error — keep polling.
            logger.debug(
                "VERIFY_GET_RETRY",
                extra={"server_id": server_id, "error": str(err)},
            )
        except Exception as err:  # best-effort: keep polling on any error
            logger.debug(
                "VERIFY_GET_RETRY",
                extra={"server_id": server_id, "error": str(err)},
            )
        time.sleep(DELETE_VERIFY_INTERVAL)
    # endregion BLOCK_verify

    logger.error(
        "SERVER %s STILL PRESENT %ss after accepted DELETE — "
        "manual deletion required via Hetzner console",
        server_id,
        DELETE_VERIFY_TIMEOUT,
    )


def _monotonic() -> float:
    """Clock seam for the verify-loop deadline. Tests patch this."""
    return time.monotonic()


# endregion FUNC__delete_server_with_retry


# region FUNC_hetzner_create_node
# PURPOSE: Provision a Hetzner server via the CloudAdapter interface so the generic provisioner can launch Hetzner compute nodes.
# ENSURES:
# - On success returns CloudCreateNodeDTO with external_id = str(server.id), hostname = IPv4.
# - On ANY failure AFTER servers.create() returns a server.id, the server is best-effort deleted via _safe_delete_server so no billable orphan leaks.
# RATIONALE:
# - Q: Why inject `users` into cloud-init when ssh_keys already passes the key?
#   A: Hetzner's ssh_keys only inject into root; a non-root cfg.username must be created by cloud-init. root is listed too for determinism. Mirrors vultr's build_users.
async def hetzner_create_node(
    cfg: ConfigCloudHetzner,
    key: ASSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create node."""
    loop = asyncio.get_running_loop()
    client = await loop.run_in_executor(executor, get_client, cfg)
    ssh_key_id = await loop.run_in_executor(executor, get_ssh_key_id, client, key)

    pub_key = key.export_public_key("openssh").decode("utf-8")
    user_data = replace(
        cloud_config or CloudInitConfig(),
        users=build_cloud_init_users(cfg.username, pub_key),
    ).render()

    create_server = partial(
        client.servers.create,
        name=get_rnd_name("node"),
        server_type=ServerType(name=cfg.server_type),
        image=Image(name=cfg.image_name),
        location=Location(name=cfg.location) if cfg.location else None,
        ssh_keys=[HSSHKey(id=ssh_key_id, name=get_key_name(key))],
        user_data=user_data,
    )

    # region BLOCK_create_call
    # servers.create returns synchronously with the server.id once Hetzner
    # accepts the request — the server is now billable. Any failure below
    # (missing IPv4, attribute error, transport drop) MUST best-effort delete
    # it so create_node never leaks an orphan.
    response = await loop.run_in_executor(executor, create_server)
    server = response.server
    # endregion BLOCK_create_call

    # region BLOCK_extract_and_cleanup
    try:
        # region BLOCK_extract_ip
        ipv4 = (
            server.public_net and server.public_net.ipv4 and server.public_net.ipv4.ip
        )
        if not ipv4:
            # Hetzner normally returns the IPv4 synchronously in the create
            # response. A missing IP here is an anomaly (API hiccup or race)
            # — surface as a deterministic error and clean up.
            msg = (
                f"Hetzner server {server.id} created without a public IPv4 "
                f"address — cannot proceed without a routable host"
            )
            raise RuntimeError(msg)  # noqa: TRY301
        ip_str = str(ipv4)
        # endregion BLOCK_extract_ip
    except Exception:
        # region BLOCK_cleanup_on_failure
        logger.exception(
            "CREATE_FAILED_CLEANUP",
            extra={"server_id": getattr(server, "id", None)},
        )
        server_id = getattr(server, "id", None)
        if server_id is not None:
            await loop.run_in_executor(
                executor,
                _safe_delete_server,
                client,
                server_id,
            )
        raise
        # endregion BLOCK_cleanup_on_failure

    logger.info("CREATED %s", ip_str)
    return CloudCreateNodeDTO(
        external_id=str(server.id),
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
# - Resolves deletion by numeric server ID via direct DELETE on DomainServer(id=int(external_id)) (no pre-GET — fewer failure points).
# - APIException(code="not_found") is logged and returns without error.
# - Transient errors retried up to DELETE_RETRY_ATTEMPTS; permanent errors raise.
# - After accepted DELETE, polls get_by_id until not_found.
async def hetzner_delete_node(
    cfg: ConfigCloudHetzner,
    external_id: str,
) -> None:
    """Delete node."""
    loop = asyncio.get_running_loop()
    client = await loop.run_in_executor(executor, get_client, cfg)

    try:
        server_id = int(external_id)
    except (TypeError, ValueError) as err:
        msg = f"Invalid Hetzner server id {external_id!r}: {err}"
        raise RuntimeError(msg) from err

    await loop.run_in_executor(
        executor,
        _delete_server_with_retry,
        client,
        server_id,
    )


# endregion FUNC_hetzner_delete_node
