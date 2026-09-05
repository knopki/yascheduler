"""Cloud-init user-data renderer module."""
# region MODULE_CONTRACT
# PURPOSE: Render cloud-init user-data as base64 so cloud VMs boot with correct packages, boot/run commands, and SSH users without manual setup.
# SCOPE: CloudInitConfig frozen dataclass (bootcmd, runcmd, package_upgrade, packages, users, render, render_base64) + build_users helper.
# KEYWORDS: cloud-init, user-data, renderer, base64, bootcmd, runcmd, packages, users
# endregion MODULE_CONTRACT

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["CloudInitConfig", "build_cloud_init_users"]


# region FUNC_build_cloud_init_users
# PURPOSE: Build the cloud-init `users` list from an SSH username and public key so every provider that needs a non-root login user (or an explicit root entry) constructs it identically.
# ENSURES: Always returns root with the key; appends a passwordless-sudo non-root entry when username != "root" — setup_node runs `sudo apt-get ...` and would fail without sudo.
def build_cloud_init_users(
    username: str, pub_key: str
) -> tuple[Mapping[str, object], ...]:
    """Build cloud-init users: root always, plus a passwordless-sudo non-root user when username != root."""
    users: list[Mapping[str, object]] = [
        {"name": "root", "ssh_authorized_keys": [pub_key]}
    ]
    if username != "root":
        users.append(
            {
                "name": username,
                "ssh_authorized_keys": [pub_key],
                "groups": "sudo",
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
            }
        )
    return tuple(users)


# endregion FUNC_build_cloud_init_users


# region CLASS_CloudInitConfig
# PURPOSE: Render cloud-init user-data as base64 so cloud VMs boot with correct packages, boot/run commands, and SSH users without manual setup.
@dataclass(frozen=True)
class CloudInitConfig:
    """Cloud-init user-data renderer (base64 for cloud providers)."""

    bootcmd: tuple[str | list[str], ...] = field(default_factory=tuple)
    runcmd: tuple[str, ...] = field(default_factory=tuple)
    package_upgrade: bool = field(default=False)
    packages: list[str] = field(default_factory=list)
    users: tuple[Mapping[str, object], ...] = field(default_factory=tuple)

    # region METHOD_render
    # PURPOSE: Serialize the config to JSON and strip empty sequences so cloud-init schema validation does not reject the user-data (minItems requirement).
    # INVARIANTS:
    # - Emits a "#cloud-config\n" prefix
    # - Drops empty bootcmd/runcmd/packages/users so cloud-config schema minItems: 1 validation does not reject the user-data
    def render(self) -> str:
        """Render to user-data format."""
        data = {
            k: v
            for k, v in asdict(self).items()
            if not (isinstance(v, (list, tuple)) and not v)
        }
        return "#cloud-config\n" + json.dumps(data)

    # endregion METHOD_render

    # region METHOD_render_base64
    # PURPOSE: Encode user-data as base64 so it satisfies cloud provider APIs (Azure, Hetzner) that require base64-encoded custom data at VM creation.
    def render_base64(self) -> str:
        """Render to user-data format as base64 string."""
        return base64.b64encode(self.render().encode()).decode()

    # endregion METHOD_render_base64


# endregion CLASS_CloudInitConfig
