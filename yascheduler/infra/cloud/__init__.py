"""Cloud adapters module."""
# region MODULE_CONTRACT
# PURPOSE: Expose the cloud subpackage's public surface through one import point so consumers never depend on internal module layout.
# SCOPE: Cloud subpackage facade: provisioner, adapter Protocol, config DTOs, cloud-init renderer, SSH key helpers.
# KEYWORDS: cloud facade, public api, re-export, adapters, configs, cloud-init, ssh keys
# endregion MODULE_CONTRACT

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
