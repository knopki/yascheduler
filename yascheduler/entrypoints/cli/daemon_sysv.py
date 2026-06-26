#!/usr/bin/env python
# FILE: yascheduler/entrypoints/cli/daemon_sysv.py
# VERSION: 2.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: SysV init service entry point for the scheduler daemon — runs detached via python-daemon with PID file management.
#   SCOPE: Thin sync main() that builds an argparse parser (keeping -p/--pid-file and -l/--log-file short flags for yascheduler.sh compatibility), wraps the daemon runtime in a DaemonContext (working_directory="/"), and runs the async daemon core via asyncio.run INSIDE the context.
#   DEPENDS: M-DAEMON-COMMON, M-ENTRYPOINTS-CLI-ARGS, M-ENTRYPOINTS-CONFIG-PARSER, M-ENTRYPOINTS
#   LINKS: M-DAEMON-SYSV, M-DAEMON-COMMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   main - Thin sync entry point: parse args, open DaemonContext, inside it configure logger + load Config + asyncio.run(run_daemon); exit 0/1/2
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.0 - Import LOG_FILE/PID_FILE from yascheduler.entrypoints facade instead of yascheduler.shared (prune-shared-kernel).
#   PREVIOUS_CHANGE: v2.0.0 - Reimplemented as a thin entry point (consolidate-daemon-entrypoints): builds its own argparse parser via args.py helpers (prog=yascheduler, --config/--log-level long-only, -p/--pid-file and -l/--log-file short flags preserved for yascheduler.sh); delegates to daemon_common.run_daemon; DaemonContext working_directory="/" (was os.path.dirname(__file__) — bug D); configure_logger called INSIDE the context so FileHandler opens the daemon's fd; uniform 0/1/2 exit-code contract; fixes the -l short-flag collision (each launcher parses once, no sys.argv re-parse).
#   PREVIOUS_CHANGE: v1.8.0 - Relocated into yascheduler/entrypoints/cli/ subpackage (relocate-daemon-launchers-to-cli); the entrypoints/daemon/ subpackage was liquidated and the launcher is now a sibling of init/show_nodes/submit/manage_node.
# END_CHANGE_SUMMARY
"""Yascheduler SysV init daemon entry point (detached via python-daemon)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import daemon
from daemon import pidfile

from yascheduler.entrypoints import LOG_FILE, PID_FILE
from yascheduler.entrypoints.config_parser import parse_config

from .args import add_config_arg, add_log_level_arg
from .daemon_common import configure_logger, run_daemon


# START_CONTRACT: main
#   PURPOSE: Start the daemon detached via python-daemon with PID file management; exit 0/1/2.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv }
#   OUTPUTS: { None - runs the event loop until stopped; prints Error: ... to stderr and calls sys.exit(1) on runtime failure }
#   SIDE_EFFECTS: Parses argv (preserves -p/--pid-file and -l/--log-file short flags for yascheduler.sh compatibility); opens a DaemonContext (working_directory="/", umask=0o002, pidfile=TimeoutPIDLockFile(args.pid_file)); INSIDE the context configures the root logger, loads Config, and runs the async daemon core via asyncio.run; may call sys.exit(1).
#   LINKS: M-DAEMON-SYSV, M-DAEMON-COMMON
# END_CONTRACT: main
def main(argv: list[str] | None = None) -> None:
    # START_BLOCK_PARSE_ARGS
    parser = argparse.ArgumentParser(
        prog="yascheduler",
        description="Start the yascheduler daemon (SysV init)",
    )
    add_config_arg(parser)
    add_log_level_arg(parser, default="INFO")
    # -l/--log-file short flag preserved for the installed yascheduler.sh init script.
    parser.add_argument(
        "-l",
        "--log-file",
        dest="log_file",
        default=LOG_FILE,
        help="Path to the log file (default: %(default)s)",
    )
    parser.add_argument(
        "-p",
        "--pid-file",
        dest="pid_file",
        default=PID_FILE,
        help="Path to the PID file (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    # END_BLOCK_PARSE_ARGS

    # START_BLOCK_HANDLE_FAILURE
    try:
        # START_BLOCK_DAEMON_CONTEXT
        # working_directory="/" is the python-daemon default and the convention for
        # system daemons; the previous os.path.dirname(__file__) made relative paths
        # resolve against an unreadable CWD (bug D).
        with daemon.DaemonContext(
            working_directory="/",
            umask=0o002,
            pidfile=pidfile.TimeoutPIDLockFile(args.pid_file),
        ):
            # configure_logger is called INSIDE the context so the FileHandler opens
            # the file in the daemon's context (post-double-fork).
            logger = configure_logger(
                args.log_file, logging.getLevelName(args.log_level)
            )
            config = parse_config(args.config)
            asyncio.run(run_daemon(config, logger))
        # END_BLOCK_DAEMON_CONTEXT
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


if __name__ == "__main__":
    main()
