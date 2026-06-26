# FILE: yascheduler/infra/cloud/provider_selection.py
# VERSION: 1.1.1
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
#   LAST_CHANGE: v1.1.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.1.0 - Extract _adapter_supports_any_platform helper from nested any(any(...)) for readability and early-break short-circuit (review-hardening).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from .adapters import CloudAdapter
    from .cloud_configs import ConfigCloud


# START_CONTRACT: select_provider_pure
#   PURPOSE: Pick the highest-priority provider with available capacity and platform support.
#   INPUTS: {
#     adapters: dict[str, CloudAdapter] - provider name -> adapter,
#     configs: dict[str, ConfigCloud] - provider name -> config,
#     platforms: list[str] - required platform identifiers,
#     current_counts: dict[str, int] - provider name -> current node count (from uow.nodes.list_all),
#     log: logging.Logger
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
    log: logging.Logger,
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
            log.debug(
                "[provider_selection][select_provider_pure][MAXED] %s (%d/%d)",
                name,
                current,
                config.max_nodes,
            )
            continue
        # Inline platform-support check (was _is_platform_supported on CloudProvisionerImpl).
        # Early-break loop is clearer than nested any(any(...)) and short-circuits
        # on the first supported platform.
        if not _adapter_supports_any_platform(adapter, platforms):
            log.debug(
                "[provider_selection][select_provider_pure][NO_PLATFORM] %s for %s",
                name,
                platforms,
            )
            continue
        suitable.append(adapter)
    # END_BLOCK_FILTER_SUITABLE

    if not suitable:
        log.debug(
            "[provider_selection][select_provider_pure][NONE] no suitable providers"
        )
        return None

    # START_BLOCK_SORT_BY_PRIORITY
    suitable.sort(
        key=lambda a: configs[a.name].priority,
        reverse=True,
    )
    chosen = suitable[0]
    log.debug(
        "[provider_selection][select_provider_pure][CHOSEN] %s (priority=%d)",
        chosen.name,
        configs[chosen.name].priority,
    )
    # END_BLOCK_SORT_BY_PRIORITY
    return chosen
