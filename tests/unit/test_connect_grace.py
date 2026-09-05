"""Tests for the connect_grace DTO defaults on the 5 ConfigCloud* DTOs.

The cloud-config-protocol spec scenario "connect_grace defaults on all five
DTOs" requires:

- ConfigCloudHetzner.connect_grace == 60
- ConfigCloudUpcloud.connect_grace == 60
- ConfigCloudAzure.connect_grace == 120
- ConfigCloudVastAI.connect_grace == 300
- ConfigCloudVultr.connect_grace == 300

and that each DTO still satisfies CloudConfig via isinstance (the Protocol
surface widened from 6 to 7 fields but the explicit inheritance means the
DTOs declare the field).
"""
# region MODULE_CONTRACT
# PURPOSE: Unit tests for the connect_grace defaults on the 5 ConfigCloud* DTOs.
# SCOPE: Hetzner/Upcloud default to 60, Azure default to 120, VastAI/Vultr default to 300; all 5 satisfy CloudConfig via isinstance.
# KEYWORDS: connect_grace, ConfigCloud DTOs, CloudConfig Protocol
# endregion MODULE_CONTRACT

from __future__ import annotations

from yascheduler.domain import CloudConfig
from yascheduler.infra.cloud.cloud_configs import (
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
    ConfigCloudVultr,
)


def test_connect_grace_defaults_on_all_dtos() -> None:
    """Constructing each ConfigCloud* without connect_grace yields the per-provider default.

    Also asserts isinstance(dto, CloudConfig) is True for all five so the
    Protocol-surface widening (6 → 7 fields) keeps the explicit inheritance
    parity intact.
    """
    hetzner = ConfigCloudHetzner(token="test-token")
    upcloud = ConfigCloudUpcloud(login="test", password="test")
    azure = ConfigCloudAzure(
        tenant_id="test-tid",
        client_id="test-cid",
        client_secret="test-secret",
        subscription_id="test-sub",
    )
    vastai = ConfigCloudVastAI(api_key="test-key")
    vultr = ConfigCloudVultr(api_key="test-key")

    assert hetzner.connect_grace == 60, "Hetzner default should be 60s"
    assert upcloud.connect_grace == 60, "Upcloud default should be 60s"
    assert azure.connect_grace == 120, "Azure default should be 120s"
    assert vastai.connect_grace == 300, "VastAI default should be 300s"
    assert vultr.connect_grace == 300, "Vultr default should be 300s"

    for dto in (hetzner, upcloud, azure, vastai, vultr):
        assert isinstance(dto, CloudConfig), (
            f"{type(dto).__name__} must satisfy CloudConfig via isinstance "
            "(Protocol is runtime_checkable; explicit inheritance preserved)"
        )
