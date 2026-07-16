"""yascheduler CLI command — start the daemon (foreground, intended for manual/debug/container use) via the shared daemon core."""
# region MODULE_CONTRACT
# PURPOSE: yascheduler CLI command — start the daemon in the foreground (manual/debug/container use) via the shared daemon core.
# SCOPE: daemonize command — thin sync entry point delegating to daemon_common.
# KEYWORDS: daemon, foreground, cli, entrypoint, debug
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from yascheduler.entrypoints.cli.args import (
    add_config_arg,
    add_log_file_arg,
    add_log_level_arg,
)
from yascheduler.entrypoints.cli.daemon_common import configure_logger, run_daemon
from yascheduler.entrypoints.config_parser import parse_config


# region FUNC_daemonize
# PURPOSE: Start the yascheduler daemon in the foreground via the shared daemon core; exit 0 on clean shutdown, 1 on runtime error, 2 on argparse error.
def daemonize(argv: list[str] | None = None) -> None:
    """Start the yascheduler daemon in the foreground via the shared daemon core; exit 0 on clean shutdown, 1 on runtime error, 2 on argparse error."""
    # region BLOCK_parse_args
    parser = argparse.ArgumentParser(
        prog="yascheduler",
        description="Start the yascheduler daemon",
    )
    add_config_arg(parser)
    # -l/--log-level short flag restored for backward compatibility with the
    # preserves `yascheduler -l DEBUG` behavior. -l
    # is free here because --log-file is long-only via add_log_file_arg; this is
    # independent of daemon_sysv's -l/--log-file (each launcher parses once).
    add_log_level_arg(parser, default="INFO", short="-l")
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


# endregion FUNC_daemonize

if __name__ == "__main__":
    daemonize()
