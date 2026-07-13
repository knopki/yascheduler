# FILE: yascheduler/infra/cloud/cloud_configs.py
# VERSION: 1.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Cloud provider config DTOs + ConfigCloud union.
#   SCOPE: ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference, ConfigCloud union.
#   DEPENDS: M-SHARED, M-DOMAIN-PORTS
#   LINKS: M-CLOUD-PROTOCOLS, M-ENTRYPOINTS-CONFIG-PARSER, M-DOMAIN-PORTS, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AzureImageReference  - Azure image URN (publisher, offer, sku, version) with from_urn pure parser
#   ConfigCloudAzure     - Azure cloud configuration frozen dataclass, explicitly inherits CloudConfig Protocol
#   ConfigCloudHetzner   - Hetzner cloud configuration frozen dataclass, explicitly inherits CloudConfig Protocol
#   ConfigCloudUpcloud   - Upcloud cloud configuration frozen dataclass, explicitly inherits CloudConfig Protocol
#   ConfigCloudVastAI    - VastAI cloud configuration frozen dataclass, explicitly inherits CloudConfig Protocol
#   ConfigCloud          - Union[ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI]
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Add jump_port: int = 22 field to all 4 ConfigCloud* DTOs; configurable via {prefix}_jump_port INI key. On the CloudConfig Protocol (8th field) because the cloud allocator stamps it onto Node.jump_port alongside jump_host/jump_username.
#   PREVIOUS_CHANGE: v1.3.0 - Add package_upgrade: bool = True field to all 4 ConfigCloud* DTOs; controls the cloud-init package_upgrade flag on freshly-provisioned VMs and is read by CloudProvisionerImpl._get_cloud_config_data. Default True. Not added to the CloudConfig Protocol (infra-only consumer) nor to AzureImageReference.
# END_CHANGE_SUMMARY
#
"""Cloud provider config DTOs."""

from dataclasses import dataclass, field
from typing import Optional, Union

from yascheduler.domain import CloudConfig
from yascheduler.shared import Self


@dataclass(frozen=True)
class AzureImageReference:
    """Azure image reference (publisher:offer:sku:version URN)."""

    publisher: str = "Debian"
    offer: str = "debian-11-daily"
    sku: str = "11-backports-gen2"
    version: str = "latest"

    # START_CONTRACT: from_urn
    #   PURPOSE: Create AzureImageReference from a URN string in publisher:offer:sku:version format
    #   INPUTS: { urn: str - URN string with colon-separated image reference components }
    #   OUTPUTS: { Self - parsed Azure image reference }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CLOUD-CONFIGS
    # END_CONTRACT: from_urn
    @classmethod
    def from_urn(cls, urn: str) -> Self:
        "Create image reference from urn in format `publisher:offer:sku:version`"
        parts = urn.split(":", maxsplit=4)
        if len(parts) < 4:
            raise ValueError(
                "`Image reference URN should be in format publisher:offer:sku:version"
            )
        return cls(*parts)


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
    jump_username: Optional[str] = None
    jump_host: Optional[str] = None
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
    location: Optional[str] = None
    image_name: str = "debian-13"
    idle_tolerance: int = 120
    connect_grace: int = 60
    package_upgrade: bool = True
    jump_username: Optional[str] = None
    jump_host: Optional[str] = None
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
    jump_username: Optional[str] = None
    jump_host: Optional[str] = None
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
    jump_username: Optional[str] = None
    jump_host: Optional[str] = None
    jump_port: int = 22


ConfigCloud = Union[
    ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI
]
