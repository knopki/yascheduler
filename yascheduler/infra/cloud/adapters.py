# FILE: yascheduler/infra/cloud/adapters.py
# VERSION: 1.1.1
# START_MODULE_CONTRACT
#   PURPOSE: Mapping of cloud config types to create/delete callables.
#   SCOPE: Adapter registry mapping provider config classes to their operations.
#   DEPENDS: M-CLOUD-PROTOCOLS, M-CLOUD-PROVIDERS
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROVIDERS
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
#   get_vastai_adapter          # (name: str) -> CloudAdapter
#   CLOUD_ADAPTER_GETTERS       # Registry mapping cloud prefix to adapter factory
#   resolve_adapter             # Look up cloud adapter by prefix from registry (public; consumed by composition root)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.1.0 - Rename _resolve_adapter → resolve_adapter (public) so the composition root (di.py) doesn't reach into a private symbol (review-hardening).
# END_CHANGE_SUMMARY
# FIXME: migrate from attrs to dataclasses
"""Cloud adapters"""

from __future__ import annotations

import asyncio
from functools import cache
from typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    import logging

    from yascheduler.config import ConfigCloud

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
    def get_op_semaphore(self) -> asyncio.Semaphore:
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
def get_azure_adapter(name: str) -> CloudAdapter:
    from .providers.az import az_create_node, az_delete_node

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
def get_hetzner_adapter(name: str) -> CloudAdapter:
    from .providers.hetzner import hetzner_create_node, hetzner_delete_node

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
def get_upcloud_adapter(name: str) -> CloudAdapter:
    from .providers.upcloud import upcload_delete_node, upcloud_create_node

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_buster,),
        create_node=upcloud_create_node,
        delete_node=upcload_delete_node,
        op_limit=1,
    )


# START_CONTRACT: get_vastai_adapter
#   PURPOSE: Create CloudAdapter for VastAI with Bullseye platform support, single op limit
#   INPUTS: { name: str - cloud provider name }
#   OUTPUTS: { CloudAdapter - configured VastAI cloud adapter }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-ADAPTERS, M-CLOUD-VASTAI
# END_CONTRACT: get_vastai_adapter
def get_vastai_adapter(name: str) -> CloudAdapter:
    from .providers.vastai import vastai_create_node, vastai_delete_node

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_bullseye,),
        create_node=vastai_create_node,
        delete_node=vastai_delete_node,
        op_limit=1,
    )


CLOUD_ADAPTER_GETTERS = {
    "az": get_azure_adapter,
    "hetzner": get_hetzner_adapter,
    "upcloud": get_upcloud_adapter,
    "vastai": get_vastai_adapter,
}


# START_CONTRACT: resolve_adapter
#   PURPOSE: Look up cloud adapter by prefix from the CLOUD_ADAPTER_GETTERS registry
#   INPUTS: { cfg: ConfigCloud - cloud provider config with prefix, log: logging.Logger - logger instance }
#   OUTPUTS: { Optional[CloudAdapter] - resolved adapter or None if prefix unknown or deps missing }
#   SIDE_EFFECTS: Logs error on ImportError
#   LINKS: M-CLOUD-ADAPTERS
# END_CONTRACT: resolve_adapter
def resolve_adapter(cfg: ConfigCloud, log: logging.Logger) -> CloudAdapter | None:
    try:
        getter = CLOUD_ADAPTER_GETTERS[cfg.prefix]
        return getter(cfg.prefix)
    except KeyError:
        return None
    except ImportError:
        log.error(
            "The cloud %s is skipped because the dependencies are not installed",
            cfg.prefix,
        )
        return None
