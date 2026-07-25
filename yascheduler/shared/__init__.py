"""Shared kernel for cross-layer typing shims."""
# region MODULE_CONTRACT
# PURPOSE: Provide a single-package import surface for shared kernel symbols consumed across architectural layers.
# SCOPE: Re-exports from shared sub-modules. No module-level logic.
# KEYWORDS: shared kernel, re-export, typing shims, cross-layer, compat, log
# endregion MODULE_CONTRACT

from .compat import Self, StrEnum, TypeGuard, Unpack
from .log import LogFormatter
from .retry import retry

__all__ = ["LogFormatter", "Self", "StrEnum", "TypeGuard", "Unpack", "retry"]
