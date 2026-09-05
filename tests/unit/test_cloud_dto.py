"""Tests for CloudCreateNodeDTO."""

from __future__ import annotations

import dataclasses

import pytest

from yascheduler.infra.cloud import CloudCreateNodeDTO as FacadeCloudCreateNodeDTO
from yascheduler.infra.cloud.dto import CloudCreateNodeDTO


def test_dto_constructs_with_all_fields() -> None:
    """DTO accepts and stores all required and optional fields."""
    dto = CloudCreateNodeDTO(
        external_id="az-vm-001",
        hostname="10.0.0.1",
        username="admin",
        port=2222,
        jump_host="bastion.example.com",
        jump_port=2223,
        jump_username="jump_admin",
    )
    assert dto.external_id == "az-vm-001"
    assert dto.hostname == "10.0.0.1"
    assert dto.username == "admin"
    assert dto.port == 2222
    assert dto.jump_host == "bastion.example.com"
    assert dto.jump_port == 2223
    assert dto.jump_username == "jump_admin"


def test_dto_is_frozen() -> None:
    """Cannot mutate a DTO instance after creation."""
    dto = CloudCreateNodeDTO(external_id="id-1", hostname="1.2.3.4")
    with pytest.raises(dataclasses.FrozenInstanceError):
        dto.hostname = "changed"  # type: ignore[misc]


def test_dto_default_values() -> None:
    """Optional fields have correct default values."""
    dto = CloudCreateNodeDTO(external_id="id-1", hostname="1.2.3.4")
    assert dto.username == "root"
    assert dto.port == 22
    assert dto.jump_host is None
    assert dto.jump_port == 22
    assert dto.jump_username == "root"


def test_dto_importable_from_facade() -> None:
    """CloudCreateNodeDTO is importable via the cloud subpackage facade."""
    assert FacadeCloudCreateNodeDTO is CloudCreateNodeDTO
