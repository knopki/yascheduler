"""Cloud provider config DTOs."""
# region MODULE_CONTRACT
# PURPOSE: Define per-provider configuration contracts so the provisioner can read VM parameters (image, size, credentials, limits) without knowing provider-specific DTO internals.
# SCOPE: ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference, ConfigCloud union.
# KEYWORDS: config, dto, azure, hetzner, upcloud, vastai, cloud config, image reference
# endregion MODULE_CONTRACT

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Union

from yascheduler.domain import CloudConfig

if TYPE_CHECKING:
    from yascheduler.shared import Self

__all__ = [
    "AzureImageReference",
    "ConfigCloud",
    "ConfigCloudAzure",
    "ConfigCloudHetzner",
    "ConfigCloudUpcloud",
    "ConfigCloudVastAI",
]


@dataclass(frozen=True)
class AzureImageReference:
    """Azure image reference (publisher:offer:sku:version URN)."""

    publisher: str = "Debian"
    offer: str = "debian-11-daily"
    sku: str = "11-backports-gen2"
    version: str = "latest"

    # region METHOD_from_urn
    # PURPOSE: Parse a publisher:offer:sku:version URN into structured fields so Azure image config is human-friendly at the INI level.
    @classmethod
    def from_urn(cls, urn: str) -> Self:
        """Create image reference from urn in format `publisher:offer:sku:version`."""
        min_parts = 4
        parts = urn.split(":", maxsplit=min_parts)
        if len(parts) < min_parts:
            msg = "`Image reference URN should be in format publisher:offer:sku:version"
            raise ValueError(
                msg,
            )
        return cls(*parts)

    # endregion METHOD_from_urn


@dataclass(frozen=True)
class ConfigCloudAzure(CloudConfig):
    """Azure cloud configuration."""

    # Class attr — not a dataclass field; identifies the provider prefix in INI keys.
    prefix = "az"

    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    subscription_id: str = ""
    resource_group: str = "yascheduler-rg"
    location: str = "westeurope"
    vnet: str = "yascheduler-vnet"
    subnet: str = "yascheduler-subnet"
    nsg: str = "yascheduler-nsg"
    vm_image: AzureImageReference = field(default_factory=AzureImageReference)
    vm_size: str = "Standard_B1s"
    max_nodes: int = 10
    username: str = "yascheduler"
    priority: int = 0
    idle_tolerance: int = 300
    connect_grace: int = 120
    package_upgrade: bool = True
    jump_username: str | None = None
    jump_host: str | None = None
    jump_port: int = 22


@dataclass(frozen=True)
class ConfigCloudHetzner(CloudConfig):
    """Hetzner cloud configuration."""

    prefix = "hetzner"

    token: str = ""
    max_nodes: int = 10
    username: str = "root"
    priority: int = 0
    server_type: str = "cx52"
    location: str | None = None
    image_name: str = "debian-13"
    idle_tolerance: int = 120
    connect_grace: int = 60
    package_upgrade: bool = True
    jump_username: str | None = None
    jump_host: str | None = None
    jump_port: int = 22


@dataclass(frozen=True)
class ConfigCloudUpcloud(CloudConfig):
    """Upcloud cloud configuration."""

    prefix = "upcloud"

    login: str = ""
    password: str = ""
    max_nodes: int = 10
    username: str = "root"
    priority: int = 0
    idle_tolerance: int = 120
    connect_grace: int = 60
    package_upgrade: bool = True
    jump_username: str | None = None
    jump_host: str | None = None
    jump_port: int = 22


@dataclass(frozen=True)
class ConfigCloudVastAI(CloudConfig):
    """VastAI cloud configuration."""

    prefix = "vastai"

    api_key: str = ""
    image: str = "pytorch/pytorch:2.2.2-cuda12.1-cudnn8-devel"
    disk_gb: int = 80
    min_vram_mb: int = 80 * 1024
    num_gpus: int = 1
    max_price_per_hr: float = 1.50
    max_nodes: int = 10
    username: str = "root"
    priority: int = 0
    idle_tolerance: int = 300
    connect_grace: int = 120
    package_upgrade: bool = True
    onstart_script: str = ""
    docker_options: str = ""
    env: dict = field(default_factory=dict)
    jump_username: str | None = None
    jump_host: str | None = None
    jump_port: int = 22


ConfigCloud = Union[
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
]
