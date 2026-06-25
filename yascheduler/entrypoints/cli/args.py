# FILE: yascheduler/entrypoints/cli/args.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Shared argparse helpers for CLI entry points — validators and flag adders consumed by all six CLI commands and the three daemon launchers.
#   SCOPE: argparse type validator (existing_path) and three flag adders (add_config_arg, add_log_level_arg, add_log_file_arg) plus LOG_LEVEL_CHOICES constant.
#   DEPENDS: M-ENTRYPOINTS
#   LINKS: M-ENTRYPOINTS-CLI-ARGS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   LOG_LEVEL_CHOICES - Explicit list of accepted log-level names (no logging._levelToName private API)
#   existing_path - argparse type validator: Path(s) if s is an existing file else ArgumentTypeError
#   add_config_arg - Add --config PATH (type=existing_path, default=CONFIG_FILE)
#   add_log_level_arg - Add --log-level (choices=LOG_LEVEL_CHOICES, default="WARNING")
#   add_log_file_arg - Add --log-file PATH (default=None unless caller overrides)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Import CONFIG_FILE from yascheduler.entrypoints facade instead of yascheduler.shared (prune-shared-kernel).
#   PREVIOUS_CHANGE: v1.0.0 - Initial module (consolidate-daemon-entrypoints): shared argparse helpers extracted from submit.py + daemonize.py; --log-level uses explicit choices resolved via logging.getLevelName (no private logging API); --config uses existing_path so missing files exit 2 with a clear message.
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
from pathlib import Path

from yascheduler.entrypoints import CONFIG_FILE

LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


# START_CONTRACT: existing_path
#   PURPOSE: argparse type validator — return Path(s) if s points to an existing file, else raise ArgumentTypeError (argparse converts to exit 2).
#   INPUTS: { s: str - path string from argparse }
#   OUTPUTS: { Path - resolved path if it points to an existing file }
#   SIDE_EFFECTS: None — raises argparse.ArgumentTypeError on missing/non-file path; argparse surfaces this as exit 2.
#   LINKS: M-ENTRYPOINTS-CLI-ARGS
# END_CONTRACT: existing_path
def existing_path(s: str) -> Path:
    p = Path(s)
    if not p.is_file():
        raise argparse.ArgumentTypeError(f"not a file: {s}")
    return p


# START_CONTRACT: add_config_arg
#   PURPOSE: Add a --config PATH argument with type=existing_path so a missing config file exits 2 with a clear message.
#   INPUTS: { parser: argparse.ArgumentParser - parser to mutate, default: str - default config path (CONFIG_FILE), dest: str - argparse dest ("config") }
#   OUTPUTS: { None - mutates parser in place }
#   SIDE_EFFECTS: Registers --config on the parser; argparse may exit 2 at parse time via the existing_path type validator.
#   LINKS: M-ENTRYPOINTS-CLI-ARGS
# END_CONTRACT: add_config_arg
def add_config_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = CONFIG_FILE,
    dest: str = "config",
) -> None:
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


# START_CONTRACT: add_log_level_arg
#   PURPOSE: Add a --log-level argument with an explicit choices list resolved via logging.getLevelName (no private logging._levelToName API).
#   INPUTS: { parser: argparse.ArgumentParser - parser to mutate, default: str - default level name (WARNING) }
#   OUTPUTS: { None - mutates parser in place }
#   SIDE_EFFECTS: Registers --log-level on the parser; argparse exits 2 on an invalid choice (e.g. WARN is rejected — only WARNING is accepted).
#   LINKS: M-ENTRYPOINTS-CLI-ARGS
# END_CONTRACT: add_log_level_arg
def add_log_level_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = "WARNING",
) -> None:
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=LOG_LEVEL_CHOICES,
        default=default,
        help="Root logger level (default: %(default)s); resolved via logging.getLevelName",
    )


# START_CONTRACT: add_log_file_arg
#   PURPOSE: Add a --log-file PATH argument (path string, no existence check) used by the three daemon entry points.
#   INPUTS: { parser: argparse.ArgumentParser - parser to mutate, default: str | None - default log file path (None → stderr / journald) }
#   OUTPUTS: { None - mutates parser in place }
#   SIDE_EFFECTS: Registers --log-file on the parser; FileHandler creation happens in daemon_common.configure_logger and will fail loudly on an unwritable path.
#   LINKS: M-ENTRYPOINTS-CLI-ARGS
# END_CONTRACT: add_log_file_arg
def add_log_file_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str | None = None,
) -> None:
    parser.add_argument(
        "--log-file",
        dest="log_file",
        default=default,
        help="Path to the log file (default: stderr; a FileHandler is created only when set)",
    )
