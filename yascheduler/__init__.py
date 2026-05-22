from importlib.metadata import PackageNotFoundError, version

from .client import Yascheduler
from .variables import CONFIG_FILE, LOG_FILE, PID_FILE

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
