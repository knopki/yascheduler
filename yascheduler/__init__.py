"""Package entry point exposing public client and constants."""
# region MODULE_CONTRACT
# PURPOSE: Expose the public client facade, version string, and canonical path constants at the package root so external consumers can ``from yascheduler import Yascheduler``.
# SCOPE: Public package surface: Yascheduler facade, __version__, and runtime path constants (CONFIG_FILE, LOG_FILE, PID_FILE).
# KEYWORDS: package, entrypoint, version, paths, constants
# endregion MODULE_CONTRACT

from importlib.metadata import PackageNotFoundError, version

from yascheduler.entrypoints import CONFIG_FILE, LOG_FILE, PID_FILE

from .entrypoints import Yascheduler

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
