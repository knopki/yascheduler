"""Upcloud cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission UpCloud servers so the scheduler can run compute workloads on UpCloud through the generic CloudAdapter contract.
# SCOPE: UpCloud create/delete node functions.
# DEPENDENCIES: USES API: upcloud-api (CloudManager SDK); WRITES: HTTP to UpCloud API (server create/delete/destroy)
# KEYWORDS: upcloud, server, create, delete, api, ssh key, cloud manager
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures.thread import ThreadPoolExecutor
from functools import cache
from typing import TYPE_CHECKING, cast

from upcloud_api import (
    CloudManager,
    Server,
    Storage,
    UpCloudAPIError,
    login_user_block,
)

from yascheduler.infra.cloud import CloudCreateNodeDTO, get_rnd_name

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey

    from yascheduler.infra.cloud import CloudInitConfig, ConfigCloudUpcloud

__all__ = ["upcloud_create_node", "upcloud_delete_node"]
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=5)

# Bounded destroy retry so a persistent UpCloud failure (404, auth, illegal
# state) can never pin the module-global executor thread forever. Mirrors
# hetzner/vultr; SERVER_NOT_FOUND is idempotent success.
_DELETE_ATTEMPTS = 3
_DELETE_INTERVAL = 5
# UpCloud destroy fails if the server has not settled into stopped state,
# so stop() must be followed by a wait before destroy(). Shared by delete
# and by create-failure cleanup.
_STOP_WAIT_SECONDS = 20


# region FUNC_get_client
# PURPOSE: Reuse an authenticated UpCloud client across calls so repeated server operations do not re-authenticate.
@cache
def get_client(cfg: ConfigCloudUpcloud) -> CloudManager:
    """Get Upcloud client."""
    client = CloudManager(cfg.login, cfg.password)
    client.authenticate()
    return client


# endregion FUNC_get_client


# region FUNC_upcloud_create_node_sync
# PURPOSE: Provision an UpCloud server with SSH key and cloud-config so the VM is ready for scheduler use immediately after creation.
# INVARIANTS:
# - external_id = hostname = VM's public IP
# - On any failure once the server exists (no public IP, or any exception during adoption), best-effort destroys the just-created server before re-raising so no billable orphan leaks. The original error propagates unchanged (cloud spec: "a failure after partial cloud resources are created cleans them up").
# - If create_server itself raises (no server object in hand), the pre-create hostname is logged at ERROR for manual review since the synchronous SDK may or may not have provisioned.
def upcloud_create_node_sync(
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create node."""
    client = get_client(cfg)

    login_user = login_user_block(
        username=cfg.username,
        ssh_keys=[key.export_public_key("openssh").decode("utf-8")],
        create_password=False,
    )
    hostname = get_rnd_name(cfg.label)
    server: Server | None = None
    try:
        server = client.create_server(
            Server(
                core_number=8,
                memory_amount=4096,
                hostname=hostname,
                zone="uk-lon1",
                storage_devices=[Storage(os="Debian 10.0", size=40)],
                login_user=login_user,
                user_data=cloud_config.render() if cloud_config else None,
            ),
        )
        ip_addr = cast("str | None", server.get_public_ip())
        if ip_addr is None:
            # The VM exists and bills; without a public IP we cannot return a
            # DTO the orchestrator could tear down, so destroy now and raise.
            msg = f"UpCloud server {hostname} created without a public IP"
            raise RuntimeError(msg)  # noqa: TRY301
    except BaseException:
        if server is not None:
            _destroy_created_server_best_effort(server, hostname)
        else:
            logger.exception(
                "CREATE_SERVER_RAISED — UpCloud VM may exist for hostname %s; "
                "manual check required",
                hostname,
            )
        raise
    logger.info("CREATED %s", ip_addr)
    return CloudCreateNodeDTO(
        external_id=ip_addr,
        hostname=ip_addr,
        username=cfg.username,
        jump_host=cfg.jump_host,
        jump_port=cfg.jump_port,
        jump_username=cfg.jump_username or "root",
    )


# endregion FUNC_upcloud_create_node_sync


# region FUNC_destroy_created_server_best_effort
# PURPOSE: Tear down an UpCloud server whose create succeeded but whose adoption into the scheduler failed (e.g. no public IP), so no billable orphan leaks when create_node cannot return a DTO.
# ENSURES: Never raises — the original create failure propagates regardless. Best-effort stop+wait+destroy+storage cleanup; SERVER_NOT_FOUND is treated as idempotent success. Any failure is logged at ERROR for manual recovery since no DB row exists to retry against.
def _destroy_created_server_best_effort(server: Server, hostname: str) -> None:
    """Best-effort destroy of a created-but-not-adopted server. Never raises.

    No retry — best-effort, not guaranteed; this runs on the failure path and
    the original exception must propagate. A single stop+wait+destroy attempt
    matches the delete flow's first attempt.
    """
    try:
        server.stop()
        time.sleep(_STOP_WAIT_SECONDS)
        try:
            server.destroy()
        except UpCloudAPIError as exc:
            if exc.error_code != "SERVER_NOT_FOUND":
                raise
            logger.info("ORPHAN_SERVER_ALREADY_GONE %s", hostname)
        else:
            for storage in server.storage_devices:  # type: ignore[attr-defined]
                storage.destroy()
        logger.warning(
            "ORPHAN_SERVER_DESTROYED — server %s destroyed after failed adoption",
            hostname,
        )
    except BaseException:
        logger.exception(
            "ORPHAN_SERVER_DESTROY_FAILED — UpCloud VM %s may still bill; "
            "manual deletion required via UpCloud console",
            hostname,
        )


# endregion FUNC_destroy_created_server_best_effort


# region FUNC_upcloud_create_node
# PURPOSE: Offload synchronous UpCloud server creation to a thread so the async caller does not block the event loop.
# INVARIANTS:
# - external_id = hostname = VM's public IP
async def upcloud_create_node(
    cfg: ConfigCloudUpcloud,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create node."""
    return await asyncio.get_running_loop().run_in_executor(
        executor,
        upcloud_create_node_sync,
        cfg,
        key,
        cloud_config,
    )


# endregion FUNC_upcloud_create_node


# region FUNC_upcloud_delete_node_sync
# PURPOSE: Tear down an UpCloud server by IP (stop, destroy server, clean up storage) so billing stops and no orphaned storage accrues costs.
# INVARIANTS:
# - Iterates client.get_servers() and matches by public IP
# - destroy() retried up to _DELETE_ATTEMPTS; SERVER_NOT_FOUND = idempotent success
# - On persistent failure raises the last UpCloudAPIError so the orchestrator retries next cycle instead of hanging the executor thread
def upcloud_delete_node_sync(
    cfg: ConfigCloudUpcloud,
    external_id: str,
) -> None:
    """Delete node."""
    client = get_client(cfg)
    for server in client.get_servers():
        if server.get_public_ip() == external_id:
            server.stop()
            logger.info("WAITING FOR STOP...")
            time.sleep(_STOP_WAIT_SECONDS)
            err: UpCloudAPIError | None = None
            server_gone = False
            for attempt in range(1, _DELETE_ATTEMPTS + 1):
                try:
                    server.destroy()
                except UpCloudAPIError as exc:  # noqa: PERF203
                    if exc.error_code == "SERVER_NOT_FOUND":
                        logger.info("SERVER %s ALREADY GONE", external_id)
                        server_gone = True
                        break
                    err = exc
                    logger.warning(
                        "DESTROY ATTEMPT FAILED",
                        extra={
                            "external_id": external_id,
                            "attempt": attempt,
                            "attempts": _DELETE_ATTEMPTS,
                            "error_code": exc.error_code,
                            "error_message": exc.error_message,
                        },
                    )
                    if attempt < _DELETE_ATTEMPTS:
                        time.sleep(_DELETE_INTERVAL)
                else:
                    err = None
                    break
            if err is not None:
                raise err
            if not server_gone:
                for storage in server.storage_devices:  # type: ignore[attr-defined]
                    storage.destroy()
            logger.info("DELETED %s", external_id)
            break
    else:
        logger.info("NODE %s NOT DELETED AS UNKNOWN", external_id)


# endregion FUNC_upcloud_delete_node_sync


# region FUNC_upcloud_delete_node
# PURPOSE: Offload synchronous UpCloud server deletion to a thread so the async caller does not block the event loop.
# INVARIANTS:
# - Iterates client.get_servers() and matches by public IP
async def upcloud_delete_node(
    cfg: ConfigCloudUpcloud,
    external_id: str,
) -> None:
    """Delete node."""
    return await asyncio.get_running_loop().run_in_executor(
        executor,
        upcloud_delete_node_sync,
        cfg,
        external_id,
    )


# endregion FUNC_upcloud_delete_node
