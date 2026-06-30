# FILE: tests/unit/test_cloud_config_protocol_inheritance.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Assert the 4 ConfigCloud* DTOs explicitly inherit the domain CloudConfig Protocol (D1).
#   SCOPE: MRO + isinstance checks for the 4 DTOs; AzureImageReference negative case.
#   DEPENDS: M-CLOUD-CONFIGS, M-DOMAIN-PORTS
#   LINKS: M-CLOUD-CONFIGS, M-DOMAIN-PORTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_all_four_dtos_inherit_cloud_config                 - MRO check for all 4 DTOs (PEP 544-safe, no issubclass)
#   test_isinstance_returns_true_for_each_dto               - isinstance(dto, CloudConfig) is True for each DTO
#   test_azure_image_reference_does_not_inherit_cloud_config - AzureImageReference.__mro__ excludes CloudConfig
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Drop test_no_issubclass_in_production_code (test-for-test's-sake: enforced PEP 544 discipline already covered by openspec/specs/cloud-config spec and runtime TypeError on any issubclass call; the test shelled out to rg, an undeclared CI dependency).
#   PREVIOUS_CHANGE: v1.0.0 - Assert explicit DTO→CloudConfig Protocol inheritance (resolve-type-bridge-debt / D1); uses __mro__ introspection and isinstance, never issubclass (PEP 544 data-Protocol ban).
# END_CHANGE_SUMMARY

from __future__ import annotations

import pytest

from yascheduler.domain import CloudConfig
from yascheduler.infra.cloud.cloud_configs import (
    AzureImageReference,
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
)

DTO_CLASSES = (
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
)


def test_all_four_dtos_inherit_cloud_config() -> None:
    """Each DTO's __mro__ includes CloudConfig (explicit inheritance, not just structural)."""
    for dto_cls in DTO_CLASSES:
        assert CloudConfig in dto_cls.__mro__, (
            f"{dto_cls.__name__} should explicitly inherit CloudConfig "
            f"(MRO: {[c.__name__ for c in dto_cls.__mro__]})"
        )


def test_isinstance_returns_true_for_each_dto() -> None:
    """isinstance(dto_instance, CloudConfig) is True for each DTO (runtime_checkable Protocol)."""
    for dto_cls in DTO_CLASSES:
        instance = dto_cls()
        assert isinstance(instance, CloudConfig), (
            f"isinstance({dto_cls.__name__}(), CloudConfig) should be True"
        )


def test_azure_image_reference_does_not_inherit_cloud_config() -> None:
    """AzureImageReference does NOT inherit CloudConfig (it lacks the 6 Protocol fields)."""
    assert CloudConfig not in AzureImageReference.__mro__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
