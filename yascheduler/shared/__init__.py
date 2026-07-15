"""Shared kernel for cross-layer typing shims."""
# FILE: yascheduler/shared/__init__.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Shared kernel for cross-layer typing shims.
#   SCOPE: Typing shims consumed by >=2 architectural layers; a module whose consumers are in a single layer belongs to that layer, not to shared. No SSH/DB/HTTP/cloud I/O.
#   DEPENDS: none
#   LINKS: M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Self - Self type alias (re-exported from .compat)
#   Unpack - Unpack type alias (re-exported from .compat)
#   StrEnum - StrEnum type (re-exported from .compat)
#   LogFormatter - Formatter with extra-diff trace discriminator (re-exported from .log)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Remove YaLogger/get_logger re-exports (retired abstractions); retain LogFormatter, Self, Unpack, StrEnum.
#   PREVIOUS_CHANGE: v1.9.0 - Re-export get_logger from .log for cross-layer consumers.
# END_CHANGE_SUMMARY

from .compat import Self, StrEnum, Unpack
from .log import LogFormatter

__all__ = ["LogFormatter", "Self", "StrEnum", "Unpack"]
