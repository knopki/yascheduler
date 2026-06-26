# FILE: tests/unit/test_connect_grace.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for the connect_grace defaults on the 4 ConfigCloud* DTOs.
#   SCOPE: Hetzner/Upcloud default to 60, Azure/VastAI default to 120; all 4 satisfy CloudConfig via isinstance.
#   DEPENDS: M-CLOUD-CONFIGS, M-DOMAIN-PORTS
#   LINKS: M-CLOUD-CONFIGS, M-DOMAIN-PORTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_connect_grace_defaults_on_all_four_dtos - DTO default + CloudConfig isinstance parity
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial test for connect_grace DTO defaults (fix-never-connected-node-leak).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY
"""Tests for the connect_grace DTO defaults on the 4 ConfigCloud* DTOs.

The cloud-config-protocol spec scenario "connect_grace defaults on all four
DTOs" requires:

- ConfigCloudHetzner.connect_grace == 60
- ConfigCloudUpcloud.connect_grace == 60
- ConfigCloudAzure.connect_grace == 120
- ConfigCloudVastAI.connect_grace == 120

and that each DTO still satisfies CloudConfig via isinstance (the Protocol
surface widened from 6 to 7 fields but the explicit inheritance means the
DTOs declare the field).
"""

from __future__ import annotations

from yascheduler.domain import CloudConfig
from yascheduler.infra.cloud.cloud_configs import (
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
)


def test_connect_grace_defaults_on_all_four_dtos() -> None:
    """Constructing each ConfigCloud* without connect_grace yields the per-provider default.

    Also asserts isinstance(dto, CloudConfig) is True for all four so the
    Protocol-surface widening (6 → 7 fields) keeps the explicit inheritance
    parity intact.
    """
    hetzner = ConfigCloudHetzner()
    upcloud = ConfigCloudUpcloud()
    azure = ConfigCloudAzure()
    vastai = ConfigCloudVastAI()

    assert hetzner.connect_grace == 60, "Hetzner default should be 60s"
    assert upcloud.connect_grace == 60, "Upcloud default should be 60s"
    assert azure.connect_grace == 120, "Azure default should be 120s"
    assert vastai.connect_grace == 120, "VastAI default should be 120s"

    for dto in (hetzner, upcloud, azure, vastai):
        assert isinstance(dto, CloudConfig), (
            f"{type(dto).__name__} must satisfy CloudConfig via isinstance "
            "(Protocol is runtime_checkable; explicit inheritance preserved)"
        )
