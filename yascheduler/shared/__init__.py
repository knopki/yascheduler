"""Shared kernel for cross-layer typing shims."""
# region MODULE_CONTRACT
# PURPOSE: Provide a single-package import surface for shared kernel symbols consumed across architectural layers.
# SCOPE: Re-exports from shared sub-modules. No module-level logic.
# KEYWORDS: shared kernel, re-export, typing shims, cross-layer, compat, log
# endregion MODULE_CONTRACT

from .compat import (
    NotRequired,
    ParamSpec,
    Required,
    Self,
    StrEnum,
    TypeGuard,
    TypeIs,
    Unpack,
)
from .log import LogFormatter
from .retry import retry
from .validators import MAX_PORT, validate_interval

__all__ = [
    "MAX_PORT",
    "LogFormatter",
    "NotRequired",
    "ParamSpec",
    "Required",
    "Self",
    "StrEnum",
    "TypeGuard",
    "TypeIs",
    "Unpack",
    "retry",
    "validate_interval",
]
