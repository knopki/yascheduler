# FILE: yascheduler/__init__.py
# VERSION: 1.7.0
# START_MODULE_CONTRACT
#   PURPOSE: Package entry point exposing public client and constants.
#   SCOPE: Re-exports Yascheduler, CONFIG_FILE, PID_FILE, LOG_FILE, __version__.
#   DEPENDS: M-CLIENT, M-SHARED
#   LINKS: M-CLIENT, M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Public client class
#   CONFIG_FILE - Default config file path
#   PID_FILE - Default PID file path
#   LOG_FILE - Default log file path
#   __version__ - Package version from metadata
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Import CONFIG_FILE/LOG_FILE/PID_FILE from yascheduler.shared facade.
#   PREVIOUS_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

from importlib.metadata import PackageNotFoundError, version

from yascheduler.shared import CONFIG_FILE, LOG_FILE, PID_FILE

from .client import Yascheduler

try:
    __version__ = version("yascheduler")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = [
    "CONFIG_FILE",
    "LOG_FILE",
    "PID_FILE",
    "Yascheduler",
    "__version__",
]
