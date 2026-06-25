# FILE: yascheduler/infra/cloud/__init__.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public re-exports from infra/cloud submodules.
#   SCOPE: Re-exports of cloud adapter, protocol, config, and provisioner symbols.
#   DEPENDS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CLOUD-PROVISIONER
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudAdapter - Frozen dataclass wrapping create/delete callables + platform checks
#   CloudCapacity - Cloud capacity dataclass
#   PCloudConfig - Cloud config init protocol
#   CreateNodeCallable - Create node in the cloud protocol
#   DeleteNodeCallable - Delete node in the cloud protocol
#   CloudConfig - Cloud config data class
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
#   LAST_CHANGE: v1.6.0 - Refresh MODULE_MAP wording: CloudAdapter is now a frozen dataclass, not a frozen attrs class (migrate-cloud-from-attrs).
#   PREVIOUS_CHANGE: v1.5.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

"""Cloud adapters module"""

from .adapters import (
    CloudAdapter,
    get_azure_adapter,
    get_hetzner_adapter,
    get_upcloud_adapter,
    resolve_adapter,
)
from .cloud_config import CloudConfig
from .manager import CloudAllocateError, CloudProvisionerImpl, CloudSetupError
from .protocols import (
    CloudCapacity,
    CreateNodeCallable,
    DeleteNodeCallable,
    PCloudConfig,
)
from .ssh_keys import get_key_name, get_or_create_ssh_key
from .utils import get_rnd_name

__all__ = [
    "CloudAdapter",
    "CloudAllocateError",
    "CloudCapacity",
    "CloudConfig",
    "CloudProvisionerImpl",
    "CloudSetupError",
    "CreateNodeCallable",
    "DeleteNodeCallable",
    "PCloudConfig",
    "get_azure_adapter",
    "get_hetzner_adapter",
    "get_key_name",
    "get_or_create_ssh_key",
    "get_rnd_name",
    "get_upcloud_adapter",
    "resolve_adapter",
]
