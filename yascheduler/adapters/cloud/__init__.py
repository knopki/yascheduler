# FILE: yascheduler/adapters/cloud/__init__.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public re-exports from adapters/cloud submodules.
#   SCOPE: Re-exports of cloud adapter, protocol, config, and provisioner symbols.
#   DEPENDS: M-CLOUD-ADAPTERS, M-CLOUD-PROTOCOLS, M-CLOUD-PROVISIONER
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-PROTOCOLS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudAdapter - Frozen attrs class wrapping create/delete callables + platform checks
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
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Add CloudProvisionerImpl, CloudAllocateError, CloudSetupError exports.
#   PREVIOUS_CHANGE: v1.0.0 - Extracted from yascheduler/clouds/ package.
# END_CHANGE_SUMMARY

"""Cloud adapters module"""

from .adapters import (
    CloudAdapter,
    get_azure_adapter,
    get_hetzner_adapter,
    get_upcloud_adapter,
)
from .cloud_config import CloudConfig
from .manager import CloudAllocateError, CloudProvisionerImpl, CloudSetupError
from .protocols import (
    CloudCapacity,
    CreateNodeCallable,
    DeleteNodeCallable,
    PCloudConfig,
)

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
    "get_upcloud_adapter",
]
