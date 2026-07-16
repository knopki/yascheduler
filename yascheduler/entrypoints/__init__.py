"""Entrypoints layer facade."""
# region MODULE_CONTRACT
# PURPOSE: Expose the entrypoints layer's public surface (outermost hexagonal layer: driving adapters + composition root) from one import path.
# SCOPE: Layer facade: Yascheduler, make_daemon, make_cli_deps, CLIDeps, Config, plus path constants (CONFIG_FILE, LOG_FILE, PID_FILE).
# KEYWORDS: entrypoints, facade, public api, re-export
# endregion MODULE_CONTRACT

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
