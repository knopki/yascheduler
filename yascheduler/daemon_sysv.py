#!/usr/bin/env python
# FILE: yascheduler/daemon_sysv.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: SysV init service entry point for launching the scheduler daemon.
#   SCOPE: SysV daemon with PID file management.
#   DEPENDS: M-UTILS, M-VARIABLES
#   LINKS: M-UTILS, M-VARIABLES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   start_daemon - launches daemonized process with PID file management
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
"""
SystemV Daemon functions
"""

import argparse
import os

import daemon
from daemon import pidfile

from yascheduler import LOG_FILE, PID_FILE
from yascheduler.utils import daemonize


def start_daemon(pid_file, log_file) -> None:
    """Launch daemon in its context as per
    https://stackoverflow.com/questions/13106221/"""
    with daemon.DaemonContext(
        working_directory=os.path.dirname(__file__),
        umask=0o002,
        pidfile=pidfile.TimeoutPIDLockFile(pid_file),
    ) as _:
        daemonize(log_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Yascheduler daemon")
    parser.add_argument("-p", "--pid-file", default=PID_FILE)
    parser.add_argument("-l", "--log-file", default=LOG_FILE)

    args = parser.parse_args()

    start_daemon(pid_file=args.pid_file, log_file=args.log_file)
