"""Pure function for selecting best cloud provider by priority, capacity, and platform support."""
# region MODULE_CONTRACT
# PURPOSE: Select the most suitable cloud provider (highest priority with available capacity and compatible platform) so the allocator can decide without I/O, DB access, or provider-specific knowledge.
# SCOPE: select_provider_pure function — adapter-internal, called only from CloudProvisionerImpl.select_provider.
# KEYWORDS: provider selection, priority, capacity, platform, pure function
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters import CloudAdapter
    from .cloud_configs import ConfigCloud

logger = logging.getLogger(__name__)

__all__ = ["select_provider_pure"]


# region FUNC_select_provider_pure
# PURPOSE: Return the highest-priority provider with available capacity and platform support so the allocator picks cost-effectively without blocking on I/O.
# REQUIRES: adapters and configs dicts are non-empty; platforms is a list of required platform identifiers.
# ENSURES: Returns None when no suitable provider found; caller owns all I/O and DB.
def select_provider_pure(
    adapters: dict[str, CloudAdapter],
    configs: dict[str, ConfigCloud],
    platforms: list[str],
    current_counts: dict[str, int],
) -> CloudAdapter | None:
    """Select best provider by priority, capacity, and platform support."""
    # region BLOCK_filter_suitable
    suitable: list[CloudAdapter] = []
    for name, adapter in adapters.items():
        config = configs.get(name)
        if config is None:
            continue
        current = current_counts.get(name, 0)
        if current >= config.max_nodes:
            logger.debug(
                "MAXED",
                extra={
                    "provider": name,
                    "current": current,
                    "max_nodes": config.max_nodes,
                },
            )
            continue
        # Inline platform-support check (was _is_platform_supported on CloudProvisionerImpl).
        # Early-break loop is clearer than nested any(any(...)) and short-circuits
        # on the first supported platform.
        if not _adapter_supports_any_platform(adapter, platforms):
            logger.debug(
                "NO_PLATFORM",
                extra={"provider": name, "platforms": platforms},
            )
            continue
        suitable.append(adapter)
    # endregion BLOCK_filter_suitable

    if not suitable:
        return None

    # region BLOCK_sort_by_priority
    suitable.sort(
        key=lambda a: configs[a.name].priority,
        reverse=True,
    )
    chosen = suitable[0]
    logger.debug(
        "CHOSEN",
        extra={"provider": chosen.name, "priority": configs[chosen.name].priority},
    )
    # endregion BLOCK_sort_by_priority
    return chosen


# endregion FUNC_select_provider_pure


# region FUNC__adapter_supports_any_platform
# PURPOSE: Check whether a given adapter supports at least one of the requested platforms so the allocator can skip incompatible providers.
def _adapter_supports_any_platform(adapter: CloudAdapter, platforms: list[str]) -> bool:
    checks = adapter.supported_platform_checks
    for platform in platforms:
        for check in checks:
            if check(platform):
                return True
    return False


# endregion FUNC__adapter_supports_any_platform
