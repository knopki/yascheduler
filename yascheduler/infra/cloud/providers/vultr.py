"""Vultr cloud provider (bare metal via REST API v2)."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission Vultr servers so the scheduler can run compute workloads on Vultr through the generic CloudAdapter contract.
# SCOPE: cloud-side lifecycle only, NOT DB/UoW/SSH-setup/allocator.
# DEPENDENCIES: USES API: api.vultr.com/v2 (aiohttp).
# KEYWORDS: vultr, provider, bare metal, create, delete, ssh key, raid, cloud-init
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from functools import cache
from typing import TYPE_CHECKING, cast

import aiohttp

from yascheduler.infra.cloud import (
    CloudCreateNodeDTO,
    CloudInitConfig,
    build_cloud_init_users,
    get_key_name,
    get_rnd_name,
)

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey as ASSHKey

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr

__all__ = ["vultr_create_node", "vultr_delete_node"]
logger = logging.getLogger(__name__)


API_BASE = "https://api.vultr.com/v2"
POLL_INTERVAL = 20
POLL_TIMEOUT = 1200
# DELETE retries on transient (5xx) failures; the DELETE call itself.
CLEANUP_DELETE_ATTEMPTS = 3
CLEANUP_DELETE_INTERVAL = 5
# After a 2xx DELETE, poll GET until the instance is confirmed gone (404).
# Vultr bare-metal deletion is asynchronous: a 2xx means "accepted", not "gone".
CLEANUP_VERIFY_TIMEOUT = 180
CLEANUP_VERIFY_INTERVAL = 10
_HTTP_BAD_REQUEST_CODE = 400
_HTTP_INTERNAL_ERROR_CODE = 500
_HTTP_NOT_FOUND_CODE = 404
_HTTP_TOO_MANY_REQUESTS = 429


class APIError(Exception):
    """Vultr API error.

    `status` is the HTTP status when the error originated from an HTTP
    response, or None for transport-level failures.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def transient(self) -> bool:
        """True for 429/5xx responses and transport failures — worth retrying."""
        return (
            self.status is None
            or self.status == _HTTP_TOO_MANY_REQUESTS
            or self.status >= _HTTP_INTERNAL_ERROR_CODE
        )


# region CLASS_VultrClient
# PURPOSE: Wrap a single aiohttp session authenticated to the Vultr API so repeated create/poll/delete calls reuse one connection pool instead of re-handshaking per request.
class VultrClient:
    """Async Vultr REST API client (aiohttp-based)."""

    def __init__(
        self, api_key: str, session: aiohttp.ClientSession | None = None
    ) -> None:
        self.api_key = api_key
        self._session: aiohttp.ClientSession | None = session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=60),
            )
        return self._session

    async def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
    ) -> dict:
        """Send an async HTTP request to the Vultr API v2 and return parsed JSON."""
        url = API_BASE + path
        session = await self._get_session()
        data = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            async with session.request(method, url, data=data) as resp:
                raw = await resp.text()
                if resp.status >= _HTTP_BAD_REQUEST_CODE:
                    msg = f"HTTP {resp.status}: {raw}"
                    raise APIError(msg, status=resp.status)
                if not raw:
                    return {}
                return cast("dict", json.loads(raw))
        except aiohttp.ClientError as err:
            msg = f"HTTP request failed: {err}"
            raise APIError(msg) from err

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


# endregion CLASS_VultrClient


@cache
def get_client(cfg: ConfigCloudVultr) -> VultrClient:
    """Get Vultr client."""
    return VultrClient(cfg.api_key)


# region FUNC_ssh_key_fingerprint_md5
# PURPOSE: Compute the MD5 fingerprint of an OpenSSH public key so we can match already-uploaded keys on Vultr by fingerprint (avoiding duplicate uploads across allocations).
def ssh_key_fingerprint_md5(pubkey: str) -> str:
    """Compute MD5 fingerprint of an OpenSSH public key string."""
    parts = pubkey.split()
    if len(parts) <= 1:
        return ""
    key_bytes = base64.b64decode(parts[1])
    md5_hex = hashlib.md5(key_bytes).hexdigest()  # noqa: S324
    return ":".join(md5_hex[i : i + 2] for i in range(0, len(md5_hex), 2))


# endregion FUNC_ssh_key_fingerprint_md5


# region FUNC_get_ssh_key_id
# PURPOSE: Upload (or reuse) an SSH key on Vultr and return its id so bare-metal instances can be launched with authorized_keys preinstalled.
# ENSURES: Returns the Vultr ssh-key id; fingerprint match against existing keys avoids duplicate uploads.
async def get_ssh_key_id(client: VultrClient, key: ASSHKey) -> str:
    """Upload or reuse SSH key on Vultr, return its id."""
    key_name = get_key_name(key)
    pub_key = key.export_public_key("openssh").decode("utf-8")
    fingerprint = ssh_key_fingerprint_md5(pub_key)

    data = await client.request("GET", "/ssh-keys?per_page=500")
    for existing in data.get("ssh_keys", []):
        existing_fp = existing.get("fingerprint", "")
        if existing_fp and existing_fp.lower() == fingerprint.lower():
            return cast("str", existing["id"])

    data = await client.request(
        "POST",
        "/ssh-keys",
        {"name": key_name, "ssh_key": pub_key},
    )
    ssh_key = data.get("ssh_key", {})
    if "id" not in ssh_key:
        msg = f"Cannot create SSH key: {data}"
        raise APIError(msg)
    return cast("str", ssh_key["id"])


# endregion FUNC_get_ssh_key_id


# region FUNC_build_baremetal_user_data
# PURPOSE: Build a cloud-init user-data string for bare-metal provisioning so a freshly launched Vultr instance has /data, ulimit, apt packages, RAID0 NVMe (when need_raid), the ScaLAPACK symlinks, and authorized_keys for root (and a non-root SSH user when configured) ready before the scheduler connects.
# RATIONALE:
# - Q: Why is /data a fixed absolute path and not ~/data?
#   A: On bare metal /data is either a RAID0 NVMe mount (need_raid=True) or the root disk (need_raid=False); engines and tasks require a dedicated mount point (/data/engines, /data/tasks), and cloud-init must guarantee /data exists before the scheduler connects.
# - Q: Why emit a `users` section when sshkey_id already injects the key for root?
#   A: Vultr's sshkey_id only injects into /root/.ssh/authorized_keys. For non-root username, cloud-init must create the user and install the key itself; root is also listed for determinism. The created user has no sudo.
def build_baremetal_user_data(
    username: str,
    pub_key: str,
    cloud_config: CloudInitConfig | None,
    need_raid: bool = True,
) -> str:
    """Build a cloud-init user-data string for bare metal provisioning.

    Always creates /data, sets ulimit, installs apt packages, and adds the
    ScaLAPACK symlinks. When need_raid is True, also sets up RAID0 over NVMe
    drives and resizes /dev/shm — needed for vbm-24c-256gb-amd where NVMe
    disks ship unformatted. For plans where NVMe is already the main disk
    (e.g. vbm-8c-132gb), pass need_raid=False to skip RAID and /dev/shm.

    Engine packages and package_upgrade are sourced from cloud_config when
    provided; bare-metal base packages are always merged in (deduped).
    Always emits a `users` section (root, and a no-sudo non-root user when
    username != root) so cloud-init installs authorized_keys before the
    scheduler polls SSH auth as cfg.username.
    """
    base_packages = [
        "openmpi-bin",
        "openmpi-common",
        "libopenmpi-dev",
        "libscalapack-openmpi-dev",
        "libxml2-dev",
        "libblas-dev",
        "liblapack-dev",
        "build-essential",
        "gfortran",
        "cmake",
        "git",
    ]
    if need_raid:
        base_packages.append("mdadm")

    engine_packages = []
    package_upgrade = False
    engine_bootcmd = ()
    if cloud_config:
        engine_packages = list(cloud_config.packages)
        package_upgrade = cloud_config.package_upgrade
        engine_bootcmd = cloud_config.bootcmd

    packages = list(dict.fromkeys(base_packages + engine_packages))

    # /data is an absolute path: on bare metal it is either a RAID0 NVMe
    # mount (need_raid=True) or the root disk (need_raid=False). This is not
    # ~/data (the default remote.data_dir), because bare-metal instances
    # require a dedicated mount point for engines (/data/engines) and tasks
    # (/data/tasks). cloud-init guarantees /data exists before the scheduler
    # connects.
    runcmd = ["mkdir -p /data"]

    if need_raid:
        runcmd += [
            "mdadm --create /dev/md0 --level=0 --raid-devices=2 /dev/nvme0n1 /dev/nvme1n1 --force",
            "mkfs.ext4 -b 4096 -E stride=128,stripe-width=256 /dev/md0",
            "UUID=$(blkid -s UUID -o value /dev/md0) && "
            'echo "UUID=$UUID /data ext4 defaults 0 2" >> /etc/fstab && mount /data',
            "mdadm --detail --scan >> /etc/mdadm/mdadm.conf",
            "update-initramfs -u",
            "echo 'tmpfs /dev/shm tmpfs defaults,size=200G 0 0' >> /etc/fstab",
            "mount -o remount /dev/shm",
        ]

    runcmd += [
        "printf '* soft nofile 65536\\n* hard nofile 65536\\n"
        "root soft nofile 65536\\nroot hard nofile 65536\\n' "
        ">> /etc/security/limits.conf",
        "ln -sf /usr/lib/x86_64-linux-gnu/libscalapack-openmpi.so.2.2.1 "
        "/usr/lib/x86_64-linux-gnu/libscalapack-openmpi.so.2.1",
        "ln -sf /usr/lib/x86_64-linux-gnu/libscalapack-openmpi.so.2.2.1 "
        "/usr/lib/x86_64-linux-gnu/libscalapack-openmpi.so.2.2",
    ]

    return CloudInitConfig(
        bootcmd=engine_bootcmd,
        runcmd=tuple(runcmd),
        package_upgrade=package_upgrade,
        packages=packages,
        users=build_cloud_init_users(username, pub_key),
    ).render()


# endregion FUNC_build_baremetal_user_data


# region FUNC_vultr_create_node
# PURPOSE: Provision a Vultr bare-metal instance via the CloudAdapter interface so the generic provisioner can launch Vultr compute nodes.
# ENSURES: Returns CloudCreateNodeDTO with external_id = hostname = instance public IP once the instance is active and has a public IP. On any failure AFTER the instance is created (POST ambiguity included), the instance is best-effort reconciled/deleted before re-raising (no billable orphan).
# INVARIANTS:
# - external_id = hostname = instance public IP (delete_node looks up by IP via find_baremetal)
# - create_node returns as soon as the instance status is "active" with a non-zero public IP
# - Post-instance-create failures (poll timeout) trigger best-effort DELETE of the instance id before the exception propagates.
# - POST /bare-metals is NOT idempotent: a transport timeout/break AFTER the server accepted the create leaves an instance we have no id for. The label (generated pre-POST) is used to reconcile such orphans (see _reconcile_orphan_by_label) so no billable resource leaks when the POST call itself fails.
async def vultr_create_node(
    cfg: ConfigCloudVultr, key: ASSHKey, cloud_config: CloudInitConfig | None = None
) -> CloudCreateNodeDTO:
    """Provision a bare-metal instance and return its IP once active.

    Creates the instance via Vultr API and polls until it becomes active
    with a public IP, then returns the IP.

    If any step after instance creation fails, the instance is best-effort
    deleted before re-raising so no billable orphan leaks.
    """
    client = get_client(cfg)
    ssh_key_id = await get_ssh_key_id(client, key)

    label = get_rnd_name("yascheduler")
    pub_key = key.export_public_key("openssh").decode("utf-8")
    user_data = build_baremetal_user_data(
        cfg.username, pub_key, cloud_config, cfg.need_raid
    )
    user_data_b64 = base64.b64encode(user_data.encode()).decode()

    body = {
        "region": cfg.location,
        "plan": cfg.server_type,
        "os_id": cfg.image_name,
        "label": label,
        "hostname": label,
        "sshkey_id": [ssh_key_id],
        "user_data": user_data_b64,
        "enable_ipv6": True,
    }

    # POST /bare-metals is not idempotent: if the transport breaks after the
    # server accepted the create, an instance exists that we have no id for.
    # Reconcile by the label generated above before re-raising the POST error
    # so a created instance is deleted, not orphaned.
    try:
        data = await client.request("POST", "/bare-metals", body)
    except Exception as err:
        logger.warning(
            "POST bare-metal failed (%s) — reconciling by label %s",
            err,
            label,
        )
        await _reconcile_orphan_by_label(client, label)
        raise
    bm = data.get("bare_metal", data)
    instance_id = bm.get("id")
    if not instance_id:
        # 2xx received but no id: the instance was likely created but the
        # body is unusable. Reconcile by label before failing.
        logger.warning(
            "POST bare-metal 2xx without instance id — reconciling by label %s: %s",
            label,
            data,
        )
        await _reconcile_orphan_by_label(client, label)
        msg = f"No instance id in response: {data}"
        raise APIError(msg)

    logger.info("CREATING bare-metal %s (id=%s)", label, instance_id)

    # The instance now exists and bills. Any failure below MUST best-effort
    # delete it so create_node never leaks a billable orphan.
    try:
        deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT
        last_status: str | None = None
        ip_addr: str | None = None
        while asyncio.get_running_loop().time() < deadline:
            # Vultr API occasionally flaps with 5xx on an instance that actually
            # exists and is progressing. Treat transient errors as "no data this
            # tick" and keep polling; a permanent error (4xx) or a transport
            # failure that persists until deadline will surface as APIError below.
            try:
                data = await client.request("GET", f"/bare-metals/{instance_id}")
            except APIError as err:
                if err.transient:
                    logger.debug(
                        "POLL_TRANSIENT_RETRY",
                        extra={
                            "instance_id": instance_id,
                            "error": str(err),
                        },
                    )
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                raise
            bm = data.get("bare_metal", data)
            status = bm.get("status", "")
            ip_addr = bm.get("main_ip", "")
            if status != last_status:
                logger.debug(
                    "POLL_STATUS",
                    extra={
                        "instance_id": instance_id,
                        "status": status,
                        "ip": ip_addr,
                    },
                )
                last_status = status
            if status == "active" and ip_addr and ip_addr != "0.0.0.0":  # noqa: S104
                break
            await asyncio.sleep(POLL_INTERVAL)
        else:
            msg = f"Bare-metal {instance_id} did not become active in {POLL_TIMEOUT}s"
            raise APIError(msg)  # noqa: TRY301

        assert ip_addr is not None
        logger.info("CREATED %s", ip_addr)
        return CloudCreateNodeDTO(
            external_id=ip_addr,
            hostname=ip_addr,
            username=cfg.username,
            jump_host=cfg.jump_host,
            jump_port=cfg.jump_port,
            jump_username=cfg.jump_username or "root",
        )
    except Exception:
        logger.exception(
            "Bare-metal %s create_node failed before returning", instance_id
        )
        await _delete_and_verify(client, instance_id)
        raise


# endregion FUNC_vultr_create_node


# region FUNC__reconcile_orphan_by_label
# PURPOSE: Close the POST-ambiguity orphan window by matching and best-effort deleting an instance created during a failed/ambiguous POST, using the label generated pre-POST.
# ENSURES: Never raises — the original POST error propagates regardless. On lookup failure logs ERROR for manual reconciliation. Match is by exact label equality against the listed bare-metals.
async def _reconcile_orphan_by_label(client: VultrClient, label: str) -> None:
    """Best-effort delete of an instance created during an ambiguous POST.

    Vultr POST /bare-metals is not idempotent: if we time out or the transport
    breaks after the server accepted the create, an instance exists that we
    never got an id for. Match it by the label generated pre-POST and delete
    it. Never raises.
    """
    try:
        data = await client.request("GET", "/bare-metals?per_page=500")
    except Exception:
        logger.exception(
            "RECONCILE_LOOKUP_FAILED — potential orphan billing; manual check needed",
            extra={"label": label},
        )
        return
    orphan_id: str | None = None
    for bm in data.get("bare_metals", []):
        if bm.get("label") == label and bm.get("id"):
            orphan_id = cast("str", bm["id"])
            break
    if orphan_id is None:
        logger.debug("RECONCILE_NO_ORPHAN", extra={"label": label})
        return
    logger.warning(
        "RECONCILE_DELETE_ORPHAN",
        extra={"label": label, "instance_id": orphan_id},
    )
    await _delete_and_verify(client, orphan_id)


# endregion FUNC__reconcile_orphan_by_label


# region FUNC__delete_and_verify
# PURPOSE: Delete a Vultr bare-metal instance with transient retry and async-deletion verification so neither create_node cleanup nor deallocate leaks a billable orphan when Vultr flaps or returns 2xx without immediately removing the instance.
# ENSURES: Returns True iff the instance is confirmed gone (DELETE 404 or verify GET 404). Returns False if DELETE permanently fails, retries exhaust, or verify times out. Never raises. Timeout-verified still-present instances are escalated to ERROR for manual intervention. The log NEVER claims success without a 404 confirmation.
# MODEL: Vultr bare-metal DELETE is asynchronous — 2xx means "accepted", not "gone". A 404 on DELETE means already gone. A 5xx is transient and retried. A 4xx (non-404) is permanent. After an accepted DELETE, poll GET until 404 or CLEANUP_VERIFY_TIMEOUT.
async def _delete_and_verify(
    client: VultrClient,
    instance_id: str,
) -> bool:
    """Delete a bare-metal instance with retry + async-deletion verification.

    Returns True iff confirmed gone (404). Never raises.
    """
    # region BLOCK_delete
    delete_accepted = False
    for attempt in range(1, CLEANUP_DELETE_ATTEMPTS + 1):
        try:
            await client.request("DELETE", f"/bare-metals/{instance_id}")
        except APIError as err:
            if err.status == _HTTP_NOT_FOUND_CODE:
                # Already gone — nothing to verify.
                logger.warning("Bare-metal %s already gone (DELETE 404)", instance_id)
                return True
            if err.transient and attempt < CLEANUP_DELETE_ATTEMPTS:
                logger.debug(
                    "DELETE_TRANSIENT_RETRY",
                    extra={
                        "instance_id": instance_id,
                        "attempt": attempt,
                        "attempts": CLEANUP_DELETE_ATTEMPTS,
                        "error": str(err),
                    },
                )
                await asyncio.sleep(CLEANUP_DELETE_INTERVAL)
                continue
            logger.warning(
                "Bare-metal %s delete failed after %s attempts: %s",
                instance_id,
                attempt,
                err,
                exc_info=True,
            )
            return False
        except Exception as err:
            logger.warning(
                "Bare-metal %s delete failed: %s", instance_id, err, exc_info=True
            )
            return False
        delete_accepted = True
        break
    # endregion BLOCK_delete

    if not delete_accepted:
        return False

    # region BLOCK_verify
    return await _verify_instance_gone(client, instance_id)
    # endregion BLOCK_verify


# endregion FUNC__delete_and_verify


# region FUNC__verify_instance_gone
# PURPOSE: Poll GET /bare-metals/{id} until 404 (confirmed gone) so delete never claims success on a still-billing orphan after an async Vultr deletion.
# ENSURES: Returns True on 404 (logs success), False on CLEANUP_VERIFY_TIMEOUT expiry (logs ERROR for manual intervention). Never raises. Transient GET errors during polling are treated as "uncertain, keep polling".
async def _verify_instance_gone(client: VultrClient, instance_id: str) -> bool:
    """Poll GET until the instance returns 404 or CLEANUP_VERIFY_TIMEOUT expires.

    Returns True iff confirmed gone. Never raises.
    """
    deadline = asyncio.get_running_loop().time() + CLEANUP_VERIFY_TIMEOUT
    while asyncio.get_running_loop().time() < deadline:
        try:
            await client.request("GET", f"/bare-metals/{instance_id}")
        except APIError as err:
            if err.status == _HTTP_NOT_FOUND_CODE:
                logger.warning("Bare-metal %s delete confirmed gone", instance_id)
                return True
            # Transient GET error or unexpected status — uncertain, keep polling.
            logger.debug(
                "VERIFY_GET_RETRY",
                extra={"instance_id": instance_id, "error": str(err)},
            )
        except Exception as err:
            logger.debug(
                "VERIFY_GET_RETRY",
                extra={"instance_id": instance_id, "error": str(err)},
            )
        await asyncio.sleep(CLEANUP_VERIFY_INTERVAL)
    # Timeout: instance still present after accepted DELETE + full verify window.
    logger.error(
        "Bare-metal %s STILL PRESENT %ss after accepted DELETE — "
        "manual deletion required via Vultr console",
        instance_id,
        CLEANUP_VERIFY_TIMEOUT,
    )
    return False


# endregion FUNC__verify_instance_gone


# region FUNC_find_baremetal
# PURPOSE: Resolve a Vultr bare-metal instance id from its public IP so delete_node can target the right instance even though nodes are keyed in DB by IP.
async def find_baremetal(client: VultrClient, host: str) -> str | None:
    """Find a bare-metal instance id by its IP address."""
    data = await client.request("GET", "/bare-metals?per_page=500")
    for bm in data.get("bare_metals", []):
        if bm.get("main_ip") == host and bm.get("id"):
            return cast("str", bm["id"])
    return None


# endregion FUNC_find_baremetal


# region FUNC_vultr_delete_node
# PURPOSE: Tear down a Vultr bare-metal instance by its IP-derived external_id so billing stops and the node slot is freed for reallocation.
# INVARIANTS:
# - external_id = instance public IP (matches CloudCreateNodeDTO.external_id from vultr_create_node)
# - Idempotent: unknown IP returns without raising (nothing to clean).
# - Resolves IP→instance_id via find_baremetal, then delegates to _delete_and_verify (retry + async-deletion verify) so the public delete path inherits the same orphan-prevention guarantees as create_node cleanup.
# - On _delete_and_verify returning False (permanent failure / exhausted retries / verify timeout) RAISES APIError so the caller's failure handling kicks in. In the orchestrator path, deallocate_node re-raises, the row stays disabled, and the next cycle's deallocate_nodes (which collects list_disabled()) retries — no permanent orphan from a swallowed False.
async def vultr_delete_node(
    cfg: ConfigCloudVultr,
    external_id: str,
) -> None:
    """Delete a bare-metal instance by its IP address (stored as external_id).

    Raises APIError when deletion cannot be confirmed gone, so the caller can
    leave the DB row intact for cross-cycle retry. Unknown IPs are a no-op.
    """
    client = get_client(cfg)
    instance_id = await find_baremetal(client, external_id)
    if not instance_id:
        logger.info("NODE %s NOT DELETED AS UNKNOWN", external_id)
        return
    if await _delete_and_verify(client, instance_id):
        logger.info("DELETED %s", external_id)
        return
    msg = (
        f"Bare-metal {instance_id} ({external_id}) delete not confirmed gone "
        "— cloud VM may still bill; orchestrator will retry next cycle"
    )
    raise APIError(msg)


# endregion FUNC_vultr_delete_node
