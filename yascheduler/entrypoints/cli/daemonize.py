# FILE: yascheduler/entrypoints/cli/daemonize.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: yascheduler CLI command — start the daemon (foreground, intended for manual/debug/container use) via the shared daemon core.
#   SCOPE: daemonize command — thin sync entry point that builds an argparse parser, configures the root logger, loads Config, and runs the async daemon core via asyncio.run.
#   DEPENDS: M-DAEMON-COMMON, M-ENTRYPOINTS-CLI-ARGS, M-ENTRYPOINTS-CONFIG-PARSER, M-SHARED
#   LINKS: M-CLI-COMMANDS, M-DAEMON-COMMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   daemonize - Thin sync entry point: parse args, configure logger, load Config, asyncio.run(run_daemon(config, logger)); exit 0/1/2
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Reimplemented as a thin entry point (consolidate-daemon-entrypoints): relocated from yascheduler/infra/cli/daemonize.py; builds its own argparse parser via args.py helpers (prog=yascheduler, --config/--log-level/--log-file); delegates logging to daemon_common.configure_logger and the async runtime + signal handling to daemon_common.run_daemon; @to_sync replaced by asyncio.run; --log-level uses explicit choices (no logging._levelToName private API); --log-file default None (stderr); uniform 0/1/2 exit-code contract with Error: on stderr.
#   PREVIOUS_CHANGE: v1.1.2 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

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


# START_CONTRACT: daemonize
#   PURPOSE: Start the yascheduler daemon in the foreground via the shared daemon core; exit 0 on clean shutdown, 1 on runtime error, 2 on argparse error.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - runs the event loop until stopped; prints Error: ... to stderr and calls sys.exit(1) on runtime failure }
#   SIDE_EFFECTS: Parses argv (may exit 2 on argparse error / missing --config), configures the root logger, loads Config, runs the async daemon core via asyncio.run; may call sys.exit(1).
#   LINKS: M-CLI-COMMANDS, M-DAEMON-COMMON, M-ENTRYPOINTS-CLI-ARGS
# END_CONTRACT: daemonize
def daemonize(argv: list[str] | None = None) -> None:
    # START_BLOCK_PARSE_ARGS
    parser = argparse.ArgumentParser(
        prog="yascheduler",
        description="Start the yascheduler daemon",
    )
    add_config_arg(parser)
    add_log_level_arg(parser, default="INFO")
    add_log_file_arg(parser, default=None)
    args = parser.parse_args(argv)
    # END_BLOCK_PARSE_ARGS

    # START_BLOCK_HANDLE_FAILURE
    try:
        # START_BLOCK_CONFIGURE
        logger = configure_logger(args.log_file, logging.getLevelName(args.log_level))
        config = parse_config(args.config)
        # END_BLOCK_CONFIGURE
        asyncio.run(run_daemon(config, logger))
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


if __name__ == "__main__":
    daemonize()
