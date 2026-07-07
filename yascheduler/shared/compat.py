# FILE: yascheduler/shared/compat.py
# VERSION: 1.8.0
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
# END_MODULE_MAP

# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.8.0 - Remove ParamSpec (consumed only by to_sync; moved with it into entrypoints.client). Keep Self and Unpack.
#   PREVIOUS_CHANGE: v1.7.0 - Re-export Unpack (PEP 692) with version branch.
# END_CHANGE_SUMMARY

import sys

if sys.version_info < (3, 11):
    from typing_extensions import Self, Unpack
else:
    from typing import Self, Unpack


__all__ = ["Self", "Unpack"]
