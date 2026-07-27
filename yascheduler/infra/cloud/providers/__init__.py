"""Cloud providers module."""
# region MODULE_CONTRACT
# PURPOSE: Expose all cloud provider create/delete functions through one import point so adapters.py can reference them without importing each provider submodule individually.
# SCOPE: Re-exports of provider create/delete entry points.
# KEYWORDS: cloud providers, re-export, azure, hetzner, upcloud, vastai, vultr
# endregion MODULE_CONTRACT

from .az import az_create_node, az_delete_node
from .hetzner import hetzner_create_node, hetzner_delete_node
from .upcloud import upcloud_create_node, upcloud_delete_node
from .vastai import vastai_create_node, vastai_delete_node
from .vultr import vultr_create_node, vultr_delete_node

__all__ = [
    "az_create_node",
    "az_delete_node",
    "hetzner_create_node",
    "hetzner_delete_node",
    "upcloud_create_node",
    "upcloud_delete_node",
    "vastai_create_node",
    "vastai_delete_node",
    "vultr_create_node",
    "vultr_delete_node",
]
