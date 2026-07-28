"""Process-wide logger setup for daemon and non-daemon CLI entry points."""
# region MODULE_CONTRACT
# PURPOSE: Centralize ROOT-logger configuration for every entry point.
# SCOPE: Only logger configuration
# INVARIANTS:
# - configure_logger always adds StreamHandler(sys.stderr); adds FileHandler(log_file) only when log_file is not None
# - configure_logger wires ONE shared LogFormatter instance onto both handlers (the timestamp flag is identical on both)
# - configure_cli_logger adds StreamHandler(sys.stderr) ONLY when no handler is already present on the ROOT logger (pytest caplog coexistence)
# - both helpers call logging.captureWarnings(True)
# - neither helper calls logging.basicConfig
# KEYWORDS: logger, configure, daemon, cli, entrypoints, timestamp, formatter, handlers
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from yascheduler.shared import LogFormatter

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["configure_cli_logger", "configure_logger"]


# region FUNC_configure_logger
# PURPOSE: Configure the ROOT logger for the daemon launchers.
# INVARIANTS:
# - Always adds StreamHandler(sys.stderr).
# - Adds FileHandler(log_file) only when log_file is not None.
# - Both handlers share a single LogFormatter instance (with timestamping enabled iff timestamp=True).
# - timestamp=True prepends an ISO 8601 local-time prefix to every rendered line; needed for file logging and foreground stderr where no journald stamps records.
def configure_logger(
    log_file: str | Path | None,
    level: int,
    *,
    timestamp: bool = False,
) -> logging.Logger:
    """Configure the ROOT logger so warnings from aiohttp/pg8000/asyncio reach the log file (not just yascheduler + 2 third-party loggers)."""
    root = logging.getLogger()
    root.setLevel(level)
    # Always log to stderr; systemd captures it into journald, sysv uses the file below.
    formatter = LogFormatter(timestamp=timestamp)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    root.addHandler(sh)
    if log_file is not None:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # asyncssh key-exchange chatter is noisy below ERROR; let it
    # propagate to the root handlers but suppress its DEBUG/INFO/WARNING output.
    logging.getLogger("asyncssh").setLevel(logging.ERROR)

    logging.captureWarnings(True)

    return root


# endregion FUNC_configure_logger


# region FUNC_configure_cli_logger
# PURPOSE: Configure the ROOT logger for the non-daemon CLI launchers.
# INVARIANTS:
# - Sets ROOT logger level.
# - Adds StreamHandler(sys.stderr) with LogFormatter(timestamp=False) ONLY when no handler is already present (so a pre-attached test harness stays authoritative).
# - Calls logging.captureWarnings(True) so warnings.warn routes through logging.
def configure_cli_logger(level: int) -> logging.Logger:
    """Configure the ROOT logger for a non-daemon CLI command (formatter on stderr only, no file, no asyncssh suppression)."""
    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(LogFormatter(timestamp=False))
        root.addHandler(sh)

    logging.captureWarnings(True)

    return root


# endregion FUNC_configure_cli_logger
