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
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    windows_adapter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .adapters import RemoteMachineAdapter

__all__ = ["ADAPTERS"]

ADAPTERS: Sequence[RemoteMachineAdapter] = [
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    darwin_adapter,
    windows_adapter,
]
