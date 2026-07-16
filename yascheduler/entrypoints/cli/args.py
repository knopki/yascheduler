"""Shared argparse helpers for CLI entry points — validators and flag adders consumed by all six CLI commands and the three daemon launchers."""
# region MODULE_CONTRACT
# PURPOSE: Provide shared argparse helpers — validators and flag adders — consumed by all six CLI commands and the three daemon launchers.
# SCOPE: Argparse helpers for all CLI commands — path validation, config/log-level/log-file flag registration.
# KEYWORDS: argparse, cli, validators, config, log-level, log-file
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
from pathlib import Path

from yascheduler.entrypoints import CONFIG_FILE

LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


# region FUNC_existing_path
# PURPOSE: argparse type validator — return Path(s) if s points to an existing file, else raise ArgumentTypeError (argparse converts to exit 2).
def existing_path(s: str) -> Path:
    """Argparse type validator — return Path(s) if s points to an existing file, else raise ArgumentTypeError (argparse converts to exit 2)."""
    p = Path(s)
    if not p.is_file():
        msg = f"not a file: {s}"
        raise argparse.ArgumentTypeError(msg)
    return p


# endregion FUNC_existing_path


# region FUNC_add_config_arg
# PURPOSE: Add a --config PATH argument with type=existing_path so a missing config file exits 2 with a clear message.
def add_config_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = CONFIG_FILE,
    dest: str = "config",
) -> None:
    """Add a --config PATH argument with type=existing_path so a missing config file exits 2 with a clear message."""
    # The default is wrapped in Path so argparse does NOT run `type=existing_path` on it
    # (Python 3.13+ applies `type` to string defaults; the default CONFIG_FILE may not
    # exist on a dev machine, and existence is deferred to Config.from_config_parser).
    # Explicit `--config VALUE` values are still validated by existing_path → exit 2.
    parser.add_argument(
        "--config",
        dest=dest,
        type=existing_path,
        default=Path(default),
        help="Path to the yascheduler config file (default: %(default)s)",
    )


# endregion FUNC_add_config_arg


# region FUNC_add_log_level_arg
# PURPOSE: Add a --log-level argument with an explicit choices list resolved via logging.getLevelName (no private logging._levelToName API); optionally register a short flag alias.
def add_log_level_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = "WARNING",
    short: str | None = None,
) -> None:
    """Add a --log-level argument with an explicit choices list resolved via logging."""
    # `short` (when given) is listed before --log-level so argparse renders the
    # short flag first in the usage line and help, matching the pre-refactor
    # `yascheduler -l DEBUG` convention. daemon_sysv MUST NOT pass short="-l"
    # (it already registers -l for --log-file); that collision avoidance is the
    # caller's responsibility, not enforced here.
    option_strings = [short, "--log-level"] if short is not None else ["--log-level"]
    parser.add_argument(
        *option_strings,
        dest="log_level",
        choices=LOG_LEVEL_CHOICES,
        default=default,
        help="Root logger level (default: %(default)s); resolved via logging.getLevelName",
    )


# endregion FUNC_add_log_level_arg


# region FUNC_add_log_file_arg
# PURPOSE: Add a --log-file PATH argument (path string, no existence check) used by the three daemon entry points.
def add_log_file_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str | None = None,
) -> None:
    """Add a --log-file PATH argument (path string, no existence check) used by the three daemon entry points."""
    parser.add_argument(
        "--log-file",
        dest="log_file",
        default=default,
        help="Path to the log file (default: stderr; a FileHandler is created only when set)",
    )


# endregion FUNC_add_log_file_arg
