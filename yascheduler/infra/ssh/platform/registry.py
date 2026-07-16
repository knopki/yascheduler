"""Ordered platform adapter registry for platform detection."""
# region MODULE_CONTRACT
# PURPOSE: Ordered platform adapter instances for detection — first match wins.
# SCOPE: ADAPTERS list — ordered by specificity (most specific first, fallback last).
# KEYWORDS: registry, adapters, platform detection, adapter list
# endregion MODULE_CONTRACT

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

__all__ = ["ADAPTERS"]

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
