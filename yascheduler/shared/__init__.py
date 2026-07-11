# FILE: yascheduler/shared/__init__.py
# VERSION: 1.8.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Shared kernel for cross-layer typing shims.
#   SCOPE: Typing shims consumed by ≥2 architectural layers; a module whose consumers are in a single layer belongs to that layer, not to shared. No SSH/DB/HTTP/cloud I/O.
#   DEPENDS: none
#   LINKS: M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Self - Self type alias (re-exported from .compat)
#   Unpack - Unpack type alias (re-exported from .compat)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.8.0 - Prune to honest shared kernel: drop re-exports of to_sync/asleep_until/CONFIG_FILE/LOG_FILE/PID_FILE/ParamSpec (relocated or inlined); keep Self/Unpack.
#   PREVIOUS_CHANGE: v1.7.0 - Re-export Unpack from .compat.
# END_CHANGE_SUMMARY

from .compat import Self, StrEnum, Unpack

__all__ = ["Self", "Unpack", "StrEnum"]
