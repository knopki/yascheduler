"""Entrypoints layer facade."""
# FILE: yascheduler/entrypoints/__init__.py
# VERSION: 2.5.0
# START_MODULE_CONTRACT
#   PURPOSE: Layer facade for the entrypoints layer (outermost hexagonal layer: driving adapters + composition root).
#   SCOPE: Layer facade: Yascheduler, daemon factory, CLI deps factory, and Config aggregate.
#   DEPENDS: M-ENTRYPOINTS-CLIENT, M-DI, M-ENTRYPOINTS-PATHS, M-ENTRYPOINTS-CONFIG
#   LINKS: M-ENTRYPOINTS-CLIENT, M-DI, M-ENTRYPOINTS-PATHS, M-ENTRYPOINTS-CONFIG
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Public client class (re-exported from .client)
#   make_daemon - Async Orchestrator factory (re-exported from .di)
#   make_cli_deps - Sync CLIDeps factory (re-exported from .di)
#   CLIDeps - Lightweight CLI dependency container (re-exported from .di)
#   Config - Composition-root config aggregate (re-exported from .config)
#   CONFIG_FILE - Default config file path (re-exported from .paths)
#   LOG_FILE - Default log file path (re-exported from .paths)
#   PID_FILE - Default PID file path (re-exported from .paths)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.5.0 - Re-export Config from .config (composition-root aggregate lives in entrypoints).
#   PREVIOUS_CHANGE: v2.4.0 - Re-export CONFIG_FILE/LOG_FILE/PID_FILE from .paths.
# END_CHANGE_SUMMARY

from .client import Yascheduler
from .config import Config
from .di import CLIDeps, make_cli_deps, make_daemon
from .paths import CONFIG_FILE, LOG_FILE, PID_FILE

__all__ = [
    "CONFIG_FILE",
    "LOG_FILE",
    "PID_FILE",
    "CLIDeps",
    "Config",
    "Yascheduler",
    "make_cli_deps",
    "make_daemon",
]
