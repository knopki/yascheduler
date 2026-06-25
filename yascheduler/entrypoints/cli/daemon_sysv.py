#!/usr/bin/env python
# FILE: yascheduler/entrypoints/cli/daemon_sysv.py
# VERSION: 1.8.0
#
# START_MODULE_CONTRACT
#   PURPOSE: SysV init service entry point for launching the scheduler daemon.
#   SCOPE: SysV daemon with PID file management.
#   DEPENDS: M-CLI-COMMANDS, M-SHARED
#   LINKS: M-CLI-COMMANDS, M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   start_daemon - launches daemonized process with PID file management
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.8.0 - Relocated into yascheduler/entrypoints/cli/ subpackage (relocate-daemon-launchers-to-cli); the entrypoints/daemon/ subpackage was liquidated and the launcher is now a sibling of init/show_nodes/submit/manage_node.
#   PREVIOUS_CHANGE: v1.7.0 - Relocated into yascheduler/entrypoints/daemon/ subpackage (relocate-daemon-launchers); converted relative imports (.infra.cli/.shared) to absolute facade paths (yascheduler.infra.cli/yascheduler.shared) to match entrypoints convention.
# END_CHANGE_SUMMARY
"""
SystemV Daemon functions
"""

import argparse
import os

import daemon
from daemon import pidfile

from yascheduler.infra.cli import daemonize
from yascheduler.shared import LOG_FILE, PID_FILE


def start_daemon(pid_file: str, log_file: str) -> None:
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
