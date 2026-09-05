#!/usr/bin/env python
"""Yascheduler SysV init daemon entry point (detached via python-daemon)."""
# region MODULE_CONTRACT
# PURPOSE: Support SysV-init-based systems by detaching the scheduler into a background daemon with PID file management via python-daemon.
# SCOPE: SysV daemon launcher with DaemonContext and PID file management.
# INVARIANTS: Executable file with shebang.
# KEYWORDS: sysv, daemon, entrypoint, detached, pidfile
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import daemon
from daemon import pidfile

from yascheduler.entrypoints import LOG_FILE, PID_FILE
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.entrypoints.logger import configure_logger

from .args import add_config_arg, add_log_level_arg
from .daemon_common import run_daemon

__all__ = ["main"]


# region FUNC_main
# PURPOSE: Start the daemon detached via python-daemon with PID file management; exit 0/1/2.
def main(argv: list[str] | None = None) -> None:
    """Start the daemon detached via python-daemon with PID file management; exit 0/1/2."""
    # region BLOCK_parse_args
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
    # endregion BLOCK_parse_args

    # region BLOCK_handle_failure
    try:
        # region BLOCK_daemon_context
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
                args.log_file,
                logging.getLevelName(args.log_level),
                timestamp=True,
            )
            config = parse_config(args.config)
            asyncio.run(run_daemon(config, logger))
        # endregion BLOCK_daemon_context
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    # endregion BLOCK_handle_failure


# endregion FUNC_main

if __name__ == "__main__":
    main()
