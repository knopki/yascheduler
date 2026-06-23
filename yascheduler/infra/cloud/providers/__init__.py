# FILE: yascheduler/infra/cloud/providers/__init__.py
# VERSION: 1.0.1
#
# START_MODULE_CONTRACT
#   PURPOSE: Public re-exports from cloud provider submodules.
#   SCOPE: Re-exports of provider create/delete entry points.
#   DEPENDS: M-CLOUD-AZ, M-CLOUD-HETZNER, M-CLOUD-UPCLOUD, M-CLOUD-VASTAI
#   LINKS: M-CLOUD-PROVIDERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   az_create_node - Create Azure VM (public entry point)
#   az_delete_node - Delete Azure VM and NIC (public entry point)
#   hetzner_create_node - Create Hetzner server (public entry point)
#   hetzner_delete_node - Delete Hetzner server (public entry point)
#   upcloud_create_node - Create UpCloud server (public entry point)
#   upcload_delete_node - Delete UpCloud server (public entry point)
#   vastai_create_node - Create VastAI instance (public entry point)
#   vastai_delete_node - Delete VastAI instance (public entry point)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.7.0 - Added VastAI re-exports.
# END_CHANGE_SUMMARY

"""Cloud providers module"""

from .az import az_create_node, az_delete_node
from .hetzner import hetzner_create_node, hetzner_delete_node
from .upcloud import upcload_delete_node, upcloud_create_node
from .vastai import vastai_create_node, vastai_delete_node

__all__ = [
    "az_create_node",
    "az_delete_node",
    "hetzner_create_node",
    "hetzner_delete_node",
    "upcloud_create_node",
    "upcload_delete_node",
    "vastai_create_node",
    "vastai_delete_node",
]
