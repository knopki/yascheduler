#!/usr/bin/env python
# FILE: yascheduler/daemon_systemd.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Systemd service entry point for the scheduler daemon.
#   SCOPE: Systemd daemon main function.
#   DEPENDS: M-UTILS, M-VARIABLES
#   LINKS: M-UTILS, M-VARIABLES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   __main__ - launches daemonize with LOG_FILE (systemd entry point)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
"""
Yascheduler systemd daemon
"""

if __name__ == "__main__":
    from yascheduler import LOG_FILE
    from yascheduler.utils import daemonize

    daemonize(log_file=LOG_FILE)
