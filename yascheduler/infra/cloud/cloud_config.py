# FILE: yascheduler/infra/cloud/cloud_config.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CloudConfig class — renders cloud-init user-data format.
#   SCOPE: PCloudConfig implementation for cloud provisioning.
#   DEPENDS: M-CLOUD-PROTOCOLS
#   LINKS: M-CLOUD-CONFIG, M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudConfig - Frozen dataclass implementing PCloudConfig protocol
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Migrate CloudConfig from attrs.define(frozen=True) to dataclasses.dataclass(frozen=True); render() now uses dataclasses.asdict (migrate-cloud-from-attrs).
#   PREVIOUS_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

"""Cloud config module"""

import base64
import json
from dataclasses import asdict, dataclass, field
from typing import Union

from .protocols import PCloudConfig


@dataclass(frozen=True)
class CloudConfig(PCloudConfig):
    """Cloud config init — renders cloud-init user-data (base64 for cloud providers)."""

    bootcmd: tuple[Union[str, list[str]], ...] = field(default_factory=tuple)
    package_upgrade: bool = field(default=False)
    packages: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render to user-data format."""
        return "#cloud-config\n" + json.dumps(asdict(self))

    def render_base64(self) -> str:
        """Render to user-data format as base64 string."""
        return base64.b64encode(self.render().encode()).decode()
