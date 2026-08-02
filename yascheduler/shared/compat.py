"""Type compatibility shims for older Python versions."""
# region MODULE_CONTRACT
# PURPOSE: Maintain forward-compatible type annotations across Python 3.9+ without import branching at every call site.
# SCOPE: Python version compat shims for type annotations.
# KEYWORDS: typing compat, Self, Unpack, StrEnum, python version compat
# endregion MODULE_CONTRACT

import sys
from enum import Enum

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

if sys.version_info >= (3, 11):
    from enum import StrEnum
    from typing import NotRequired, ParamSpec, Required, Self, TypeGuard, Unpack
else:
    from typing_extensions import (
        NotRequired,
        ParamSpec,
        Required,
        Self,
        TypeGuard,
        Unpack,
    )

    class StrEnum(str, Enum):
        """Backport of enum.StrEnum for Python < 3.11."""


if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing_extensions import TypeIs


__all__ = [
    "NotRequired",
    "ParamSpec",
    "Required",
    "Self",
    "StrEnum",
    "TypeAlias",
    "TypeGuard",
    "TypeIs",
    "Unpack",
]
