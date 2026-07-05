"""Vultr cloud methods (bare metal via REST API v2)"""

import asyncio
import base64
import hashlib
import json
import logging
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures.thread import ThreadPoolExecutor
from functools import cache
from typing import Optional, cast

from asyncssh.public_key import SSHKey as ASSHKey

from ..config import ConfigCloudVultr
from .protocols import PCloudConfig
from .utils import get_key_name, get_rnd_name

API_BASE = "https://api.vultr.com/v2"
POLL_INTERVAL = 20
POLL_TIMEOUT = 1200

executor = ThreadPoolExecutor(max_workers=5)


class VultrClient:
    """Thin Vultr REST API client"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = API_BASE + path
        data = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}
                return cast(dict, json.loads(raw))
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            raise APIError(f"HTTP {err.code}: {raw}") from err


class APIError(Exception):
    """Vultr API error"""


@cache
def get_client(cfg: ConfigCloudVultr) -> VultrClient:
    """Get Vultr client (cached per api key)"""
    return VultrClient(cfg.api_key)


def ssh_key_fingerprint_md5(pubkey: str) -> str:
    """Compute MD5 fingerprint of an OpenSSH public key string"""
    parts = pubkey.split()
    if len(parts) < 2:
        return ""
    key_bytes = base64.b64decode(parts[1])
    md5_hex = hashlib.md5(key_bytes).hexdigest()
    return ":".join(md5_hex[i : i + 2] for i in range(0, len(md5_hex), 2))


def get_ssh_key_id(client: VultrClient, key: ASSHKey) -> str:
    """Upload or reuse SSH key on Vultr, return its id"""
    key_name = get_key_name(key)
    pub_key = key.export_public_key("openssh").decode("utf-8")
    fingerprint = ssh_key_fingerprint_md5(pub_key)

    data = client.request("GET", "/ssh-keys?per_page=500")
    for existing in data.get("ssh_keys", []):
        existing_fp = existing.get("fingerprint", "")
        if existing_fp and existing_fp.lower() == fingerprint.lower():
            return cast(str, existing["id"])

    data = client.request("POST", "/ssh-keys", {"name": key_name, "ssh_key": pub_key})
    ssh_key = data.get("ssh_key", {})
    if "id" not in ssh_key:
        raise APIError(f"Cannot create SSH key: {data}")
    return cast(str, ssh_key["id"])


def build_baremetal_user_data(
    cloud_config: Optional[PCloudConfig],
    need_raid: bool = True,
) -> str:
    """Build cloud-config user-data for bare metal setup.

    When need_raid is True (default, for vbm-24c-256gb-amd):
      RAID0 NVMe, /data mount, /dev/shm 200G, ulimit, apt packages,
      ScaLAPACK symlink. Merges with engine packages from cloud_config.

    When need_raid is False (for vbm-8c-132gb and similar where NVMe
      is already the main disk):
      mkdir /data on root disk, ulimit, apt packages, ScaLAPACK symlink.
      No RAID0, no /dev/shm resize.
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

    engine_packages: list[str] = []
    package_upgrade = False
    if cloud_config:
        engine_packages = list(cloud_config.packages)
        package_upgrade = cloud_config.package_upgrade

    packages = list(dict.fromkeys(base_packages + engine_packages))

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
        "ln -sf /usr/lib/x86_64-linux-gnu/libscalapack-openmpi.so.2.1 "
        "/usr/lib/x86_64-linux-gnu/libscalapack-openmpi.so.2.2",
    ]

    config = {
        "package_upgrade": package_upgrade,
        "packages": packages,
        "runcmd": runcmd,
    }
    return "#cloud-config\n" + json.dumps(config)


def vultr_create_node_sync(
    log: logging.Logger,
    cfg: ConfigCloudVultr,
    key: ASSHKey,
    cloud_config: Optional[PCloudConfig] = None,
) -> str:
    """Create bare-metal node, wait for active, return IP"""
    client = get_client(cfg)
    ssh_key_id = get_ssh_key_id(client, key)

    label = get_rnd_name("node")
    user_data = build_baremetal_user_data(cloud_config, cfg.need_raid)
    user_data_b64 = base64.b64encode(user_data.encode()).decode()

    body = {
        "region": cfg.region,
        "plan": cfg.plan,
        "os_id": cfg.os_id,
        "label": label,
        "hostname": label,
        "sshkey_id": [ssh_key_id],
        "user_data": user_data_b64,
        "enable_ipv6": True,
    }
    data = client.request("POST", "/bare-metals", body)
    bm = data.get("bare_metal", data)
    instance_id = bm.get("id")
    if not instance_id:
        raise APIError(f"No instance id in response: {data}")

    log.info("CREATING bare-metal %s (id=%s)", label, instance_id)

    deadline = time.time() + POLL_TIMEOUT
    last_status: Optional[str] = None
    ip_addr: Optional[str] = None
    while time.time() < deadline:
        data = client.request("GET", f"/bare-metals/{instance_id}")
        bm = data.get("bare_metal", data)
        status = bm.get("status", "")
        ip_addr = bm.get("main_ip", "")
        if status != last_status:
            log.info("bare-metal %s status=%s ip=%s", instance_id, status, ip_addr)
            last_status = status
        if status == "active" and ip_addr and ip_addr != "0.0.0.0":
            break
        time.sleep(POLL_INTERVAL)
    else:
        raise APIError(
            f"Bare-metal {instance_id} did not become active in {POLL_TIMEOUT}s"
        )

    assert ip_addr is not None
    log.info("Bare-metal %s active, waiting for SSH on %s", instance_id, ip_addr)
    ssh_ready = False
    while time.time() < deadline:
        try:
            with socket.create_connection((ip_addr, 22), timeout=10):
                ssh_ready = True
                break
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(10)
    if not ssh_ready:
        raise APIError(f"Bare-metal {instance_id} SSH not ready on {ip_addr} in time")

    # Bare metal boots slowly: SSH port may open before cloud-init has
    # installed authorized_keys, causing Permission denied on first try.
    # Actively poll SSH authentication with the configured key until it
    # succeeds, so create_node does not fail and the scheduler does not
    # spin up redundant instances.
    log.info(
        "Bare-metal %s SSH port open, waiting for cloud-init to install keys",
        instance_id,
    )
    import os
    import tempfile

    import paramiko

    key_pem = key.export_private_key("openssh")
    with tempfile.NamedTemporaryFile(suffix=".key", delete=False) as tf:
        tf.write(key_pem)
        tf.flush()
        os.chmod(tf.name, 0o600)
        key_path = tf.name
    try:
        ssh_ok = False
        attempts = 12
        for attempt in range(1, attempts + 1):
            if time.time() >= deadline:
                break
            try:
                transport = paramiko.Transport((ip_addr, 22))
                transport.set_log_channel("paramiko.vultr")
                transport.use_compression(True)
                transport.connect(
                    username=cfg.username,
                    pkey=paramiko.RSAKey.from_private_key_file(key_path),
                )
                transport.close()
                ssh_ok = True
                log.info(
                    "Bare-metal %s SSH auth OK on attempt %s/%s",
                    instance_id,
                    attempt,
                    attempts,
                )
                break
            except Exception as exc:
                log.debug(
                    "Bare-metal %s SSH auth attempt %s/%s failed: %s",
                    instance_id,
                    attempt,
                    attempts,
                    exc,
                )
                time.sleep(15)
        if not ssh_ok:
            raise APIError(
                f"Bare-metal {instance_id} SSH auth failed on {ip_addr} "
                f"after {attempts} attempts"
            )
    finally:
        os.unlink(key_path)

    log.info("CREATED %s", ip_addr)
    return cast(str, ip_addr)


async def vultr_create_node(
    log: logging.Logger,
    cfg: ConfigCloudVultr,
    key: ASSHKey,
    cloud_config: Optional[PCloudConfig] = None,
) -> str:
    """Create node (async wrapper)"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor, vultr_create_node_sync, log, cfg, key, cloud_config
    )


def find_baremetal(client: VultrClient, host: str) -> Optional[str]:
    """Find bare-metal id by IP addr"""
    data = client.request("GET", "/bare-metals?per_page=500")
    for bm in data.get("bare_metals", []):
        if bm.get("main_ip") == host and bm.get("id"):
            return cast(str, bm["id"])
    return None


def vultr_delete_node_sync(
    log: logging.Logger,
    cfg: ConfigCloudVultr,
    host: str,
) -> None:
    """Delete bare-metal node by IP"""
    client = get_client(cfg)
    instance_id = find_baremetal(client, host)
    if instance_id:
        client.request("DELETE", f"/bare-metals/{instance_id}")
        log.info("DELETED %s", host)
    else:
        log.info("NODE %s NOT DELETED AS UNKNOWN", host)


async def vultr_delete_node(
    log: logging.Logger,
    cfg: ConfigCloudVultr,
    host: str,
) -> None:
    """Delete node (async wrapper)"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, vultr_delete_node_sync, log, cfg, host)
