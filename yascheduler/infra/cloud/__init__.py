# FILE: yascheduler/infra/cloud/__init__.py
# VERSION: 1.8.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public re-exports from infra/cloud submodules.
#   SCOPE: Re-exports of cloud adapter, protocol, config DTOs, provisioner, cloud-init renderer, and SSH key symbols.
#   DEPENDS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CLOUD-PROVISIONER, M-CLOUD-CONFIGS, M-CLOUD-INIT
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CLOUD-CONFIGS, M-CLOUD-INIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AzureImageReference - Azure VM image URN reference (re-exported from .cloud_configs)
#   CloudAdapter - Frozen dataclass wrapping create/delete callables + platform checks
#   CreateNodeCallable - Create node in the cloud protocol
#   DeleteNodeCallable - Delete node in the cloud protocol
#   ConfigCloud - Union of ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI (re-exported from .cloud_configs)
#   ConfigCloudAzure - Azure cloud config DTO (re-exported from .cloud_configs)
#   ConfigCloudHetzner - Hetzner cloud config DTO (re-exported from .cloud_configs)
#   ConfigCloudUpcloud - Upcloud cloud config DTO (re-exported from .cloud_configs)
#   ConfigCloudVastAI - VastAI cloud config DTO (re-exported from .cloud_configs)
#   CloudInitConfig - Cloud-init user-data renderer dataclass (re-exported from .cloud_init)
#   CloudProvisionerImpl - CloudProvisioner port implementation
#   CloudAllocateError - Cloud node allocation error
#   CloudSetupError - Cloud node setup error
#   get_azure_adapter - Create CloudAdapter for Azure
#   get_hetzner_adapter - Create CloudAdapter for Hetzner
#   get_upcloud_adapter - Create CloudAdapter for UpCloud
#   get_or_create_ssh_key - Load existing SSH key or generate new one
#   get_key_name - Get SSHKey's name
#   resolve_adapter - Look up cloud adapter by prefix from registry (composition-root use)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.8.0 - Re-export CloudInitConfig from .cloud_init (renamed from CloudConfig in cloud_config.py; cloud-init-rename-and-prune / D1); drop PCloudConfig and CloudCapacity re-exports (Protocol collapsed into CloudInitConfig / dead dataclass deleted; D2+D3).
#   PREVIOUS_CHANGE: v1.7.0 - Re-export AzureImageReference, ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI from .cloud_configs (cloud-configs-to-infra-registry); the DTOs relocated from yascheduler.config.cloud (deleted) and the cloud subpackage facade is now the canonical import path for the DTOs.
# END_CHANGE_SUMMARY

"""Cloud adapters module"""

from .adapters import (
    CloudAdapter,
    get_azure_adapter,
    get_hetzner_adapter,
    get_upcloud_adapter,
    resolve_adapter,
)
from .cloud_configs import (
    AzureImageReference,
    ConfigCloud,
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
)
from .cloud_init import CloudInitConfig
from .manager import CloudAllocateError, CloudProvisionerImpl, CloudSetupError
from .protocols import (
    CreateNodeCallable,
    DeleteNodeCallable,
)
from .ssh_keys import get_key_name, get_or_create_ssh_key
from .utils import get_rnd_name

__all__ = [
    "AzureImageReference",
    "CloudAdapter",
    "CloudAllocateError",
    "CloudInitConfig",
    "CloudProvisionerImpl",
    "CloudSetupError",
    "ConfigCloud",
    "ConfigCloudAzure",
    "ConfigCloudHetzner",
    "ConfigCloudUpcloud",
    "ConfigCloudVastAI",
    "CreateNodeCallable",
    "DeleteNodeCallable",
    "get_azure_adapter",
    "get_hetzner_adapter",
    "get_key_name",
    "get_or_create_ssh_key",
    "get_rnd_name",
    "get_upcloud_adapter",
    "resolve_adapter",
]
