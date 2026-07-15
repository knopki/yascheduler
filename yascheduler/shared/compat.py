"""Type compatibility shims: Self and Unpack for older Python versions."""
# FILE: yascheduler/shared/compat.py
# VERSION: 1.9.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Type compatibility shims: Self and Unpack for older Python versions.
#   SCOPE: Python version compat re-exports: Self and Unpack type aliases for older Python versions.
#   DEPENDS: none
#   LINKS: M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Self - Self type alias for older Python versions
#   Unpack - Unpack type re-exported from typing_extensions for older Python versions
#   StrEnum - StrEnum re-export: enum.StrEnum on 3.11+, typing_extensions.StrEnum below
# END_MODULE_MAP

# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - Add StrEnum re-export (enum.StrEnum on 3.11+, typing_extensions.StrEnum below; in __all__). Node-rename-and-fields change.
#   PREVIOUS_CHANGE: v1.8.0 - Remove ParamSpec (consumed only by to_sync; moved with it into entrypoints.client). Keep Self and Unpack.
# END_CHANGE_SUMMARY

import sys

if sys.version_info < (3, 11):
    from typing_extensions import Self, StrEnum, Unpack
else:
    from enum import StrEnum
    from typing import Self, Unpack


__all__ = ["Self", "StrEnum", "Unpack"]
