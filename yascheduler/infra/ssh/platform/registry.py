# FILE: yascheduler/infra/ssh/platform/registry.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Ordered platform adapter registry for platform detection.
#   SCOPE: ADAPTERS — ordered list of RemoteMachineAdapter instances.
#   DEPENDS: M-PLATFORM-ADAPTERS
#   LINKS: M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ADAPTERS - Ordered platform adapter instances (debian, linux, darwin, windows variants)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from infra/ssh/helpers.py; ADAPTERS moved verbatim, no behavioral change.
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters import (
    darwin_adapter,
    debian_10_adapter,
    debian_11_adapter,
    debian_12_adapter,
    debian_13_adapter,
    debian_14_adapter,
    debian_15_adapter,
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    windows7_adapter,
    windows8_adapter,
    windows10_adapter,
    windows11_adapter,
    windows12_adapter,
    windows_adapter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .adapters import RemoteMachineAdapter

ADAPTERS: Sequence[RemoteMachineAdapter] = [
    debian_10_adapter,
    debian_11_adapter,
    debian_12_adapter,
    debian_13_adapter,
    debian_14_adapter,
    debian_15_adapter,
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    darwin_adapter,
    windows10_adapter,
    windows11_adapter,
    windows12_adapter,
    windows7_adapter,
    windows8_adapter,
    windows_adapter,
]
