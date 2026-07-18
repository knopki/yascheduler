#!/usr/bin/env python
"""Yascheduler systemd daemon entry point (foreground, logs to stderr → journald)."""
# region MODULE_CONTRACT
# PURPOSE: Serve as the systemd service unit's ExecStart target, running the scheduler in the foreground so systemd manages its lifecycle via stderr → journald logging.
# SCOPE: Systemd foreground daemon launcher — thin sync entry point.
# INVARIANTS: Executable file with shebang.
# KEYWORDS: systemd, daemon, entrypoint, foreground, journald
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from yascheduler.entrypoints.config_parser import parse_config

from .args import (
    add_config_arg,
    add_log_file_arg,
    add_log_level_arg,
)
from .daemon_common import configure_logger, run_daemon


# region FUNC_main
# PURPOSE: Start the daemon under systemd supervision (foreground, stderr → journald); exit 0/1/2.
# INVARIANTS:
# - Entry point does NOT register SIGTERM/SIGINT handlers — run_daemon does that.
# - try/except Exception prints Error: <exception> and exits 1; SystemExit(2) propagates.
def main(argv: list[str] | None = None) -> None:
    """Start the daemon under systemd supervision (foreground, stderr → journald); exit 0/1/2."""
    # region BLOCK_parse_args
    parser = argparse.ArgumentParser(
        prog="yascheduler",
        description="Start the yascheduler daemon (systemd unit)",
    )
    add_config_arg(parser)
    add_log_level_arg(parser, default="INFO")
    add_log_file_arg(parser, default=None)
    args = parser.parse_args(argv)
    # endregion BLOCK_parse_args

    # region BLOCK_handle_failure
    try:
        # region BLOCK_configure
        logger = configure_logger(args.log_file, logging.getLevelName(args.log_level))
        config = parse_config(args.config)
        # endregion BLOCK_configure
        asyncio.run(run_daemon(config, logger))
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    # endregion BLOCK_handle_failure


# endregion FUNC_main

if __name__ == "__main__":
    main()
