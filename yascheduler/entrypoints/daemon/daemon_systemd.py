#!/usr/bin/env python
# FILE: yascheduler/entrypoints/daemon/daemon_systemd.py
# VERSION: 1.7.0
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
#   LAST_CHANGE: v1.7.0 - Relocated into yascheduler/entrypoints/daemon/ subpackage (relocate-daemon-launchers); converted relative imports (.infra.cli/.shared) to absolute facade paths (yascheduler.infra.cli/yascheduler.shared) to match entrypoints convention.
#   PREVIOUS_CHANGE: v1.6.2 - Import LOG_FILE from yascheduler.shared facade (shared-kernel-extraction).
# END_CHANGE_SUMMARY
"""
Yascheduler systemd daemon
"""

if __name__ == "__main__":
    from yascheduler.infra.cli import daemonize
    from yascheduler.shared import LOG_FILE

    daemonize(log_file=LOG_FILE)
