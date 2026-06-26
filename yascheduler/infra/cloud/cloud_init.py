# FILE: yascheduler/infra/cloud/cloud_init.py
# VERSION: 1.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CloudInitConfig — concrete cloud-init user-data renderer.
#   SCOPE: CloudInitConfig frozen dataclass (bootcmd, package_upgrade, packages, render, render_base64).
#   DEPENDS: none
#   LINKS: M-CLOUD-INIT, M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudInitConfig - Frozen dataclass; concrete cloud-init user-data renderer
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Rename file cloud_config.py → cloud_init.py and class CloudConfig → CloudInitConfig; drop PCloudConfig base class (Protocol removed in cloud-init-rename-and-prune / D1+D2); disambiguate from the ConfigCloud* provider-config DTOs in cloud_configs.py and from the domain CloudConfig Protocol in domain/ports.py.
#   PREVIOUS_CHANGE: v1.2.0 - attrs is no longer a direct dependency of yascheduler (drop-attrs-dependency).
# END_CHANGE_SUMMARY

"""Cloud-init user-data renderer module"""

import base64
import json
from dataclasses import asdict, dataclass, field
from typing import Union


@dataclass(frozen=True)
class CloudInitConfig:
    """Cloud-init user-data renderer (base64 for cloud providers)."""

    bootcmd: tuple[Union[str, list[str]], ...] = field(default_factory=tuple)
    package_upgrade: bool = field(default=False)
    packages: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render to user-data format."""
        return "#cloud-config\n" + json.dumps(asdict(self))

    def render_base64(self) -> str:
        """Render to user-data format as base64 string."""
        return base64.b64encode(self.render().encode()).decode()
