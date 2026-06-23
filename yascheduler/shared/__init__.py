# FILE: yascheduler/shared/__init__.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Shared kernel for cross-layer utilities (typing shims, async-to-sync bridge, path constants).
#   SCOPE: Facade re-exports only — no business logic, no I/O, no domain types.
#   DEPENDS: none
#   LINKS: M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Self - Self type alias (re-exported from .compat)
#   ParamSpec - ParamSpec type alias (re-exported from .compat)
#   to_sync - Async-to-sync decorator (re-exported from .async_utils)
#   CONFIG_FILE - Default config file path (re-exported from .variables)
#   LOG_FILE - Default log file path (re-exported from .variables)
#   PID_FILE - Default PID file path (re-exported from .variables)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial extraction from top-level compat/variables/client.to_sync.
# END_CHANGE_SUMMARY

from .async_utils import to_sync
from .compat import ParamSpec, Self
from .variables import CONFIG_FILE, LOG_FILE, PID_FILE

__all__ = [
    "CONFIG_FILE",
    "LOG_FILE",
    "PID_FILE",
    "ParamSpec",
    "Self",
    "to_sync",
]
