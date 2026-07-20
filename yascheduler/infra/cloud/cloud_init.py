"""Cloud-init user-data renderer module."""
# region MODULE_CONTRACT
# PURPOSE: Render cloud-init user-data as base64 so cloud VMs boot with correct packages and boot commands without manual setup.
# SCOPE: CloudInitConfig frozen dataclass (bootcmd, package_upgrade, packages, render, render_base64).
# KEYWORDS: cloud-init, user-data, renderer, base64, bootcmd, packages
# endregion MODULE_CONTRACT

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field

__all__ = ["CloudInitConfig"]


# region CLASS_CloudInitConfig
# PURPOSE: Render cloud-init user-data as base64 so cloud VMs boot with correct packages and boot commands without manual setup.
@dataclass(frozen=True)
class CloudInitConfig:
    """Cloud-init user-data renderer (base64 for cloud providers)."""

    bootcmd: tuple[str | list[str], ...] = field(default_factory=tuple)
    package_upgrade: bool = field(default=False)
    packages: list[str] = field(default_factory=list)

    # region METHOD_render
    # PURPOSE: Serialize the config to JSON and strip empty sequences so cloud-init schema validation does not reject the user-data (minItems requirement).
    # INVARIANTS:
    # - Emits a "#cloud-config\n" prefix
    # - Drops empty bootcmd/packages so cloud-config schema minItems: 1 validation does not reject the user-data
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
