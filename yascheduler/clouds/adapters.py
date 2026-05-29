# FILE: yascheduler/clouds/adapters.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Mapping of cloud config types to create/delete callables.
#   SCOPE: Adapter registry mapping provider config classes to their operations.
#   DEPENDS: M-CLOUD-PROTOCOLS, M-CLOUD-AZ, M-CLOUD-HETZNER, M-CLOUD-UPCLOUD
#   LINKS: M-CLOUD-API, M-CLOUD-AZ, M-CLOUD-HETZNER, M-CLOUD-UPCLOUD
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudAdapter                # Generic[TConfigCloud_co] - Frozen attrs class wrapping create/delete callables + platform checks
#   can_debian_buster           # (platform: str) -> bool
#   can_debian_bullseye         # (platform: str) -> bool
#   can_win10                   # (platform: str) -> bool
#   can_win11                   # (platform: str) -> bool
#   get_azure_adapter           # (name: str) -> CloudAdapter
#   get_hetzner_adapter         # (name: str) -> CloudAdapter
#   get_upcloud_adapter         # (name: str) -> CloudAdapter
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Cloud adapters"""

import asyncio
from functools import cache
from typing import Generic

from attrs import define, field

from .protocols import (
    CreateNodeCallable,
    DeleteNodeCallable,
    SupportedPlatformChecker,
    TConfigCloud_co,
)


def can_debian_buster(platform: str) -> bool:
    "Platform is compatible with Debian Buster"
    return platform in ["debian-10", "debian", "debian-like", "linux"]


def can_debian_bullseye(platform: str) -> bool:
    "Platform is compatible with Debian Bullseye"
    return platform in ["debian-11", "debian", "debian-like", "linux"]


def can_win10(platform: str) -> bool:
    "Platform is compatible with Windows 10"
    return platform in ["windows-10", "windows"]


def can_win11(platform: str) -> bool:
    "Platform is compatible with Windows 11"
    return platform in ["windows-11", "windows"]


# START_CONTRACT: CloudAdapter.__init__
#   PURPOSE: Initialize cloud adapter with provider ops, platform checks, and concurrency limits
#   INPUTS: { name: str - provider name, supported_platform_checks: tuple[SupportedPlatformChecker, ...] - platform check functions, create_node: CreateNodeCallable - create function, delete_node: DeleteNodeCallable - delete function, op_limit: int - concurrent operation limit (default 1), create_node_conn_timeout: int - SSH connect timeout in s (default 10), create_node_timeout: int - total node creation timeout in s (default 300) }
#   OUTPUTS: { CloudAdapter - frozen adapter instance }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-ADAPTERS
# END_CONTRACT: CloudAdapter.__init__
@define(frozen=True)
class CloudAdapter(Generic[TConfigCloud_co]):
    """Cloud adapter"""

    name: str = field()
    supported_platform_checks: tuple[SupportedPlatformChecker, ...] = field()
    create_node: CreateNodeCallable[TConfigCloud_co] = field()
    delete_node: DeleteNodeCallable[TConfigCloud_co] = field()
    op_limit: int = field(default=1)
    create_node_conn_timeout: int = field(default=10)
    create_node_timeout: int = field(default=300)

    @cache
    def get_op_semaphore(self):
        """
        Cached semaphore getter.
        It's because you cannot create async semaphore outside the loop.
        "attached to a different loop" error.
        """
        return asyncio.Semaphore(self.op_limit)


# START_CONTRACT: get_azure_adapter
#   PURPOSE: Create CloudAdapter for Azure with Bullseye/Windows 11 platform support
#   INPUTS: { name: str - cloud provider name }
#   OUTPUTS: { CloudAdapter - configured Azure cloud adapter }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-AZ
# END_CONTRACT: get_azure_adapter
def get_azure_adapter(name: str):
    from .az import az_create_node, az_delete_node

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_bullseye, can_win11),
        create_node=az_create_node,
        delete_node=az_delete_node,
        op_limit=5,
    )


# START_CONTRACT: get_hetzner_adapter
#   PURPOSE: Create CloudAdapter for Hetzner with Buster platform support
#   INPUTS: { name: str - cloud provider name }
#   OUTPUTS: { CloudAdapter - configured Hetzner cloud adapter }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-HETZNER
# END_CONTRACT: get_hetzner_adapter
def get_hetzner_adapter(name: str):
    from .hetzner import hetzner_create_node, hetzner_delete_node

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_buster,),
        create_node=hetzner_create_node,
        delete_node=hetzner_delete_node,
        op_limit=5,
    )


# START_CONTRACT: get_upcloud_adapter
#   PURPOSE: Create CloudAdapter for UpCloud with Buster platform support, single op limit
#   INPUTS: { name: str - cloud provider name }
#   OUTPUTS: { CloudAdapter - configured UpCloud cloud adapter }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-UPCLOUD
# END_CONTRACT: get_upcloud_adapter
def get_upcloud_adapter(name: str):
    from .upcloud import upcload_delete_node, upcloud_create_node

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_buster,),
        create_node=upcloud_create_node,
        delete_node=upcload_delete_node,
        op_limit=1,
    )
