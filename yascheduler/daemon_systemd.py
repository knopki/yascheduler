#!/usr/bin/env python
# FILE: yascheduler/daemon_systemd.py
# VERSION: 1.6.2
#
# START_MODULE_CONTRACT
#   PURPOSE: Systemd service entry point for the scheduler daemon.
#   SCOPE: Systemd daemon main function.
#   DEPENDS: M-CLI-COMMANDS, M-SHARED
#   LINKS: M-CLI-COMMANDS, M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   __main__ - launches daemonize with LOG_FILE (systemd entry point)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.2 - Import LOG_FILE from yascheduler.shared facade (shared-kernel-extraction).
#   PREVIOUS_CHANGE: v1.6.1 - Import daemonize from infra.cli.daemonize instead of utils.
# END_CHANGE_SUMMARY
# FIXME: move this module to adapters
"""
Yascheduler systemd daemon
"""

if __name__ == "__main__":
    from .infra.cli import daemonize
    from .shared import LOG_FILE

    daemonize(log_file=LOG_FILE)
