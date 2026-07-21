"""Type compatibility shims: Self and Unpack for older Python versions."""
# region MODULE_CONTRACT
# PURPOSE: Maintain forward-compatible type annotations across Python 3.9+ without import branching at every call site.
# SCOPE: Python version compat shims for type annotations.
# KEYWORDS: typing compat, Self, Unpack, StrEnum, python version compat
# endregion MODULE_CONTRACT

import sys

if sys.version_info < (3, 11):
    from typing_extensions import Self, StrEnum, Unpack
else:
    from enum import StrEnum
    from typing import Self, Unpack


__all__ = ["Self", "StrEnum", "Unpack"]
