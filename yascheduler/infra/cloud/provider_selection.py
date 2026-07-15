"""Pure function for selecting best cloud provider by priority, capacity, and platform support."""
# FILE: yascheduler/infra/cloud/provider_selection.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Pure function for selecting best cloud provider by priority, capacity, and platform support.
#   SCOPE: select_provider_pure function — adapter-internal, called only from CloudProvisionerImpl.select_provider.
#   DEPENDS: M-CLOUD-ADAPTERS-NEW
#   LINKS: M-CLOUD-PROVIDER-SELECTION, M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   select_provider_pure - Pick highest-priority provider with capacity and platform support
#   _adapter_supports_any_platform - True iff adapter supports at least one of the requested platforms
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.3.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...); drop vestigial NONE DEBUG trace (carried no extra fields, not asserted in tests).
#   PREVIOUS_CHANGE: v1.2.0 - remove log parameter from function signatures; bind module-local logger = get_logger("M-CLOUD-PROVIDER-SELECTION") at module top
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters import CloudAdapter
    from .cloud_configs import ConfigCloud

logger = logging.getLogger(__name__)

# START_CONTRACT: select_provider_pure
#   PURPOSE: Pick the highest-priority provider with available capacity and platform support.
#   INPUTS: {
#     adapters: dict[str, CloudAdapter] - provider name -> adapter,
#     configs: dict[str, ConfigCloud] - provider name -> config,
#     platforms: list[str] - required platform identifiers,
#     current_counts: dict[str, int] - provider name -> current node count (from uow.nodes.list_all)
#   }
#   OUTPUTS: { CloudAdapter | None - best matching provider or None }
#   SIDE_EFFECTS: None — pure function (caller owns all I/O and DB).
#   LINKS: M-CLOUD-ADAPTERS-NEW
# END_CONTRACT: select_provider_pure


# START_CONTRACT: _adapter_supports_any_platform
#   PURPOSE: True iff adapter passes at least one supported_platform_check for at least one requested platform.
#   INPUTS: {
#     adapter: CloudAdapter - adapter with supported_platform_checks tuple,
#     platforms: list[str] - requested platform identifiers
#   }
#   OUTPUTS: { bool }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-ADAPTERS-NEW
# END_CONTRACT: _adapter_supports_any_platform
def _adapter_supports_any_platform(adapter: CloudAdapter, platforms: list[str]) -> bool:
    checks = adapter.supported_platform_checks
    for platform in platforms:
        for check in checks:
            if check(platform):
                return True
    return False


def select_provider_pure(
    adapters: dict[str, CloudAdapter],
    configs: dict[str, ConfigCloud],
    platforms: list[str],
    current_counts: dict[str, int],
) -> CloudAdapter | None:
    """Select best provider by priority, capacity, and platform support."""
    # START_BLOCK_FILTER_SUITABLE
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
    # END_BLOCK_FILTER_SUITABLE

    if not suitable:
        return None

    # START_BLOCK_SORT_BY_PRIORITY
    suitable.sort(
        key=lambda a: configs[a.name].priority,
        reverse=True,
    )
    chosen = suitable[0]
    logger.debug(
        "CHOSEN",
        extra={"provider": chosen.name, "priority": configs[chosen.name].priority},
    )
    # END_BLOCK_SORT_BY_PRIORITY
    return chosen
