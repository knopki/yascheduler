# FILE: yascheduler/infra/cloud/cloud_init.py
# VERSION: 1.4.0
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
#   LAST_CHANGE: v1.4.0 - fix-cloud-init-empty-lists: render() omits empty list-valued fields (bootcmd, packages). cloud-init's cloud-config schema enforces minItems: 1 on both, so emitting "bootcmd": [] / "packages": [] failed validation ("... is too short") and made cloud-init exit 2 — which surfaced as SETUP_FAILED + VM deletion on every cloud allocation when no engine platform_packages matched. package_upgrade (bool) is always kept.
#   PREVIOUS_CHANGE: v1.3.0 - Rename file cloud_config.py → cloud_init.py and class CloudConfig → CloudInitConfig; drop PCloudConfig base class (Protocol removed in cloud-init-rename-and-prune / D1+D2); disambiguate from the ConfigCloud* provider-config DTOs in cloud_configs.py and from the domain CloudConfig Protocol in domain/ports.py.
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
        # cloud-init's cloud-config schema enforces minItems: 1 on bootcmd
        # and packages. Emitting "bootcmd": [] / "packages": [] fails schema
        # validation ("... is too short") and marks the run failed (exit=2),
        # which surfaces as SETUP_FAILED + VM deletion. Omit empty sequences
        # so the keys disappear entirely. bootcmd is a tuple and packages is a
        # list; asdict keeps the tuple as-is, but json.dumps serializes an
        # empty tuple as [] — so both empty tuple and empty list must be dropped.
        data = {
            k: v
            for k, v in asdict(self).items()
            if not (isinstance(v, (list, tuple)) and not v)
        }
        return "#cloud-config\n" + json.dumps(data)

    def render_base64(self) -> str:
        """Render to user-data format as base64 string."""
        return base64.b64encode(self.render().encode()).decode()
