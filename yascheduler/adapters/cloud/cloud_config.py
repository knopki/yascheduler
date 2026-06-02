# FILE: yascheduler/adapters/cloud/cloud_config.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CloudConfig class — renders cloud-init user-data format.
#   SCOPE: PCloudConfig implementation for cloud provisioning.
#   DEPENDS: M-CLOUD-PROTOCOLS
#   LINKS: M-CLOUD-CONFIG, M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudConfig - Frozen attrs class implementing PCloudConfig protocol
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from yascheduler/clouds/cloud_api.py.
# END_CHANGE_SUMMARY

"""Cloud config module"""

import base64
import json
from typing import Union

from attrs import asdict, define, field

from .protocols import PCloudConfig


@define(frozen=True)
class CloudConfig(PCloudConfig):
    """Cloud config init — renders cloud-init user-data (base64 for cloud providers)."""

    bootcmd: tuple[Union[str, list[str]], ...] = field(factory=tuple)
    package_upgrade: bool = field(default=False)
    packages: list[str] = field(factory=list)

    def render(self) -> str:
        """Render to user-data format."""
        return "#cloud-config\n" + json.dumps(asdict(self))  # type: ignore[arg-type]

    def render_base64(self) -> str:
        """Render to user-data format as base64 string."""
        return base64.b64encode(self.render().encode()).decode()
