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
#   YaLogger - Logger subclass with trace() (re-exported from .log)
#   get_logger - Factory returning YaLogger with yascheduler. namespace prefix (re-exported from .log)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - Re-export get_logger from .log for cross-layer consumers.
#   PREVIOUS_CHANGE: v1.8.0 - Prune to honest shared kernel: drop re-exports of to_sync/asleep_until/CONFIG_FILE/LOG_FILE/PID_FILE/ParamSpec (relocated or inlined); keep Self/Unpack.
# END_CHANGE_SUMMARY

from .compat import Self, StrEnum, Unpack
from .log import LogFormatter, YaLogger, get_logger

__all__ = ["Self", "Unpack", "StrEnum", "YaLogger", "get_logger", "LogFormatter"]
