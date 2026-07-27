# region MODULE_CONTRACT
# PURPOSE: Assert the 5 ConfigCloud* DTOs explicitly inherit the domain CloudConfig Protocol (D1).
# SCOPE: MRO + isinstance checks for the 5 DTOs; AzureImageReference negative case.
# KEYWORDS: CloudConfig Protocol, MRO, isinstance, DTO inheritance
# endregion MODULE_CONTRACT

from __future__ import annotations

import pytest

from yascheduler.domain import CloudConfig
from yascheduler.infra.cloud.cloud_configs import (
    AzureImageReference,
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
    ConfigCloudVultr,
)
from yascheduler.infra.cloud.protocols import CreateNodeCallable, DeleteNodeCallable

DTO_CLASSES = (
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
    ConfigCloudVultr,
)


def test_all_dtos_inherit_cloud_config() -> None:
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


def test_cloud_config_protocol_has_jump_port() -> None:
    """CloudConfig Protocol declares jump_port: int"""
    assert "jump_port" in CloudConfig.__annotations__
    assert CloudConfig.__annotations__["jump_port"] in (int, "int")


def test_azure_image_reference_does_not_inherit_cloud_config() -> None:
    """AzureImageReference does NOT inherit CloudConfig (it lacks the 6 Protocol fields)."""
    assert CloudConfig not in AzureImageReference.__mro__


def test_create_node_callable_returns_cloud_create_node_dto() -> None:
    """CreateNodeCallable.__call__ return annotation is CloudCreateNodeDTO."""
    ann = CreateNodeCallable.__call__.__annotations__
    assert "return" in ann
    assert "CloudCreateNodeDTO" in ann["return"]


def test_delete_node_callable_accepts_external_id() -> None:
    """DeleteNodeCallable.__call__ has external_id parameter (not host)."""
    ann = DeleteNodeCallable.__call__.__annotations__
    assert "external_id" in ann
    assert "host" not in ann


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
