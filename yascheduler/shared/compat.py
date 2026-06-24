# FILE: yascheduler/shared/compat.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Type compatibility shims: Self, ParamSpec, and Unpack for older Python versions.
#   SCOPE: Self, ParamSpec, and Unpack type re-exports.
#   DEPENDS: none
#   LINKS: M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Self - Self type alias for older Python versions
#   ParamSpec - ParamSpec type alias for older Python versions
#   Unpack - Unpack type re-exported from typing_extensions for older Python versions
# END_MODULE_MAP

# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Re-export Unpack (PEP 692) with version branch (task-context-replace).
#   PREVIOUS_CHANGE: v1.6.0 - Moved from yascheduler/compat.py to yascheduler/shared/compat.py.
# END_CHANGE_SUMMARY

import sys

if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec
else:
    from typing import ParamSpec

if sys.version_info < (3, 11):
    from typing_extensions import Self, Unpack
else:
    from typing import Self, Unpack


__all__ = ["Self", "ParamSpec", "Unpack"]
