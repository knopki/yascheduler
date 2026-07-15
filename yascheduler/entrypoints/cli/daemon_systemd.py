#!/usr/bin/env python
"""Yascheduler systemd daemon entry point (foreground, logs to stderr → journald)."""
# FILE: yascheduler/entrypoints/cli/daemon_systemd.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Systemd service entry point for the scheduler daemon — runs in the foreground under systemd's supervision (logs to stderr → journald).
#   SCOPE: Systemd foreground daemon launcher — thin sync entry point.
#   DEPENDS: M-DAEMON-COMMON, M-ENTRYPOINTS-CLI-ARGS, M-ENTRYPOINTS-CONFIG-PARSER
#   LINKS: M-DAEMON-SYSTEMD, M-DAEMON-COMMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   main - Thin sync entry point: parse args, configure logger, load Config, asyncio.run(run_daemon(config, logger)); exit 0/1/2
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Reimplemented as a thin entry point: builds its own argparse parser via args.py helpers (--config/--log-level/--log-file default None for journald); delegates to daemon_common.run_daemon; no python-daemon (foreground under systemd); --log-file default None is a BREAKING change from LOG_FILE (journald convention); uniform 0/1/2 exit-code contract.
#   PREVIOUS_CHANGE: v1.8.0 - Relocated into yascheduler/entrypoints/cli/ subpackage; entrypoints/daemon/ liquidated; launcher now sibling of init/show_nodes/submit/manage_node.
# END_CHANGE_SUMMARY

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


# START_CONTRACT: main
#   PURPOSE: Start the daemon under systemd supervision (foreground, stderr → journald); exit 0/1/2.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv }
#   OUTPUTS: { None - runs the event loop until stopped; prints Error: ... to stderr and calls sys.exit(1) on runtime failure }
#   SIDE_EFFECTS: Parses argv, configures the root logger, loads Config, runs the async daemon core via asyncio.run; may call sys.exit(1).
#   LINKS: M-DAEMON-SYSTEMD, M-DAEMON-COMMON
# END_CONTRACT: main
def main(argv: list[str] | None = None) -> None:
    """Start the daemon under systemd supervision (foreground, stderr → journald); exit 0/1/2."""
    # START_BLOCK_PARSE_ARGS
    parser = argparse.ArgumentParser(
        prog="yascheduler",
        description="Start the yascheduler daemon (systemd unit)",
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
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


if __name__ == "__main__":
    main()
