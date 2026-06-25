# FILE: yascheduler/entrypoints/__init__.py
# VERSION: 2.4.0
# START_MODULE_CONTRACT
#   PURPOSE: Layer facade for the entrypoints layer (outermost hexagonal layer: driving adapters + composition root).
#   SCOPE: Re-exports public symbols from entrypoints residents: Yascheduler, make_daemon, make_cli_deps, CLIDeps, CONFIG_FILE, LOG_FILE, PID_FILE.
#   DEPENDS: M-ENTRYPOINTS-CLIENT, M-DI, M-ENTRYPOINTS-PATHS
#   LINKS: M-ENTRYPOINTS-CLIENT, M-DI, M-ENTRYPOINTS-PATHS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Public client class (re-exported from .client)
#   make_daemon - Async Orchestrator factory (re-exported from .di)
#   make_cli_deps - Sync CLIDeps factory (re-exported from .di)
#   CLIDeps - Lightweight CLI dependency container (re-exported from .di)
#   CONFIG_FILE - Default config file path (re-exported from .paths)
#   LOG_FILE - Default log file path (re-exported from .paths)
#   PID_FILE - Default PID file path (re-exported from .paths)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.4.0 - Re-export CONFIG_FILE/LOG_FILE/PID_FILE from .paths (prune-shared-kernel).
#   PREVIOUS_CHANGE: v2.3.0 - relocate-di-to-entrypoints: di.py moved into entrypoints; facade now re-exports make_daemon, make_cli_deps, CLIDeps alongside Yascheduler. The "only di.py remains deferred" caveat in the previous entry is superseded.
#   PREVIOUS_CHANGE: v2.2.0 - consolidate-daemon-entrypoints: daemonize is now a resident of entrypoints/cli/ (moved from infra/cli/); yascheduler/infra/cli/ is liquidated; no deferred infra/cli migration remains.
# END_CHANGE_SUMMARY

"""Entrypoints layer facade."""

from .client import Yascheduler
from .di import CLIDeps, make_cli_deps, make_daemon
from .paths import CONFIG_FILE, LOG_FILE, PID_FILE

__all__ = [
    "CLIDeps",
    "CONFIG_FILE",
    "LOG_FILE",
    "PID_FILE",
    "Yascheduler",
    "make_cli_deps",
    "make_daemon",
]
