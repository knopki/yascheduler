"""Cloud adapters."""
# region MODULE_CONTRACT
# PURPOSE: Bind provider-specific create/delete operations to their config types so the allocator can resolve the right adapter at runtime without knowing provider internals.
# SCOPE: Adapter registry mapping provider config classes to their operations.
# DEPENDENCIES: LOADS: provider modules (az, hetzner, upcloud, vastai) lazily via inline import inside getter functions
# KEYWORDS: cloud adapter, registry, create, delete, platform check, azure, hetzner, upcloud, vastai
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, Generic

if TYPE_CHECKING:
    from .cloud_configs import ConfigCloud

from .protocols import (
    CreateNodeCallable,
    DeleteNodeCallable,
    SupportedPlatformChecker,
    TConfigCloud_co,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CLOUD_ADAPTER_GETTERS",
    "CloudAdapter",
    "get_azure_adapter",
    "get_hetzner_adapter",
    "get_upcloud_adapter",
    "get_vastai_adapter",
    "get_vultr_adapter",
    "resolve_adapter",
]


def can_debian_buster(platform: str) -> bool:
    """Platform is compatible with Debian Buster."""
    return platform in ["debian-10", "debian", "debian-like", "linux"]


def can_debian_bullseye(platform: str) -> bool:
    """Platform is compatible with Debian Bullseye."""
    return platform in ["debian-11", "debian", "debian-like", "linux"]


def can_debian_bookworm(platform: str) -> bool:
    """Platform is compatible with Debian Bookworm."""
    return platform in ["debian-12", "debian", "debian-like", "linux"]


def can_debian_trixie(platform: str) -> bool:
    """Platform is compatible with Debian Trixie."""
    return platform in ["debian-13", "debian", "debian-like", "linux"]


def can_debian_forky(platform: str) -> bool:
    """Platform is compatible with Debian Forky."""
    return platform in ["debian-14", "debian", "debian-like", "linux"]


def can_debian_duke(platform: str) -> bool:
    """Platform is compatible with Debian Duke."""
    return platform in ["debian-13", "debian", "debian-like", "linux"]


def can_win10(platform: str) -> bool:
    """Platform is compatible with Windows 10."""
    return platform in ["windows-10", "windows"]


def can_win11(platform: str) -> bool:
    """Platform is compatible with Windows 11."""
    return platform in ["windows-11", "windows"]


# region CLASS_CloudAdapter
# PURPOSE: Wrap a provider's identity (name, platform checks, create/delete callables, concurrency limit) so the provisioner can drive every provider through one uniform interface.
@dataclass(frozen=True)
class CloudAdapter(Generic[TConfigCloud_co]):
    """Cloud adapter."""

    name: str
    supported_platform_checks: tuple[SupportedPlatformChecker, ...]
    create_node: CreateNodeCallable[TConfigCloud_co]
    delete_node: DeleteNodeCallable[TConfigCloud_co]
    op_limit: int = field(default=1)
    create_node_conn_timeout: int = field(default=10)
    create_node_timeout: int = field(default=300)
    needs_cloud_init: bool = False

    @cache  # noqa: B019
    def get_op_semaphore(self) -> asyncio.Semaphore:
        """Get the cached semaphore.

        It's because you cannot create async semaphore outside the loop.
        "attached to a different loop" error.
        """
        return asyncio.Semaphore(self.op_limit)


# endregion CLASS_CloudAdapter


# region FUNC_get_azure_adapter
# PURPOSE: Wire Azure SDK create/delete to a CloudAdapter so the provisioner can launch and terminate Azure VMs through the generic adapter interface.
def get_azure_adapter(name: str) -> CloudAdapter:
    """Create CloudAdapter for Azure with Bullseye/Windows 11 platform support."""
    from .providers.az import az_create_node, az_delete_node  # noqa: PLC0415

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_bullseye, can_win11),
        create_node=az_create_node,
        delete_node=az_delete_node,
        op_limit=5,
        needs_cloud_init=True,
    )


# endregion FUNC_get_azure_adapter


# region FUNC_get_hetzner_adapter
# PURPOSE: Wire Hetzner SDK create/delete to a CloudAdapter so the provisioner can launch and terminate Hetzner servers through the generic adapter interface.
def get_hetzner_adapter(name: str) -> CloudAdapter:
    """Create CloudAdapter for Hetzner with Trixie platform support."""
    from .providers.hetzner import (  # noqa: PLC0415
        hetzner_create_node,
        hetzner_delete_node,
    )

    return CloudAdapter(
        name=name,
        supported_platform_checks=(
            can_debian_duke,
            can_debian_forky,
            can_debian_trixie,
            can_debian_buster,
        ),
        create_node=hetzner_create_node,
        delete_node=hetzner_delete_node,
        op_limit=5,
        needs_cloud_init=True,
    )


# endregion FUNC_get_hetzner_adapter


# region FUNC_get_upcloud_adapter
# PURPOSE: Wire UpCloud SDK create/delete to a CloudAdapter so the provisioner can launch and terminate UpCloud servers through the generic adapter interface.
def get_upcloud_adapter(name: str) -> CloudAdapter:
    """Create CloudAdapter for UpCloud with Buster platform support, single op limit."""
    from .providers.upcloud import (  # noqa: PLC0415
        upcloud_create_node,
        upcloud_delete_node,
    )

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_buster,),
        create_node=upcloud_create_node,
        delete_node=upcloud_delete_node,
        op_limit=1,
        needs_cloud_init=True,
    )


# endregion FUNC_get_upcloud_adapter


# region FUNC_get_vastai_adapter
# PURPOSE: Wire create/delete to a CloudAdapter so the provisioner can launch and terminate VastAI instances through the generic adapter interface.
def get_vastai_adapter(name: str) -> CloudAdapter:
    """Create CloudAdapter for VastAI with Bullseye platform support, single op limit."""
    from .providers.vastai import (  # noqa: PLC0415
        vastai_create_node,
        vastai_delete_node,
    )

    return CloudAdapter(
        name=name,
        supported_platform_checks=(
            can_debian_duke,
            can_debian_forky,
            can_debian_trixie,
            can_debian_buster,
        ),
        create_node=vastai_create_node,
        delete_node=vastai_delete_node,
        op_limit=1,
    )


# endregion FUNC_get_vastai_adapter


# region FUNC_get_vultr_adapter
# PURPOSE: Wire Vultr REST API create/delete to a CloudAdapter so the provisioner can launch and terminate Vultr bare-metal instances through the generic adapter interface.
# RATIONALE:
# - Q: Why op_limit=2 and create_node_timeout=1200?
#   A: Bare metal provisions slowly (up to ~20 min); op_limit=2 allows one in-flight create + one queued request; 1200 s timeout accommodates the longest observed boot+cloud-init cycles.
def get_vultr_adapter(name: str) -> CloudAdapter:
    """Create CloudAdapter for Vultr with Bullseye platform support, slow bare-metal timeouts."""
    from .providers.vultr import (  # noqa: PLC0415
        vultr_create_node,
        vultr_delete_node,
    )

    return CloudAdapter(
        name=name,
        supported_platform_checks=(can_debian_bullseye,),
        create_node=vultr_create_node,
        delete_node=vultr_delete_node,
        op_limit=2,
        create_node_timeout=1200,
        needs_cloud_init=True,
    )


# endregion FUNC_get_vultr_adapter


CLOUD_ADAPTER_GETTERS = {
    "az": get_azure_adapter,
    "hetzner": get_hetzner_adapter,
    "upcloud": get_upcloud_adapter,
    "vastai": get_vastai_adapter,
    "vultr": get_vultr_adapter,
}


# region FUNC_resolve_adapter
# PURPOSE: Map a config's provider prefix to the matching CloudAdapter getter so the allocator resolves the right adapter at runtime without a hard-coded switch.
# ENSURES: Returns None if prefix unknown or deps not installed (logs on ImportError).
def resolve_adapter(cfg: ConfigCloud) -> CloudAdapter | None:
    """Look up cloud adapter by prefix from the CLOUD_ADAPTER_GETTERS registry."""
    try:
        getter = CLOUD_ADAPTER_GETTERS[cfg.prefix]
        return getter(cfg.prefix)
    except KeyError:
        return None
    except ImportError:
        logger.exception(
            "The cloud %s is skipped because the dependencies are not installed",
            cfg.prefix,
        )
        return None


# endregion FUNC_resolve_adapter
