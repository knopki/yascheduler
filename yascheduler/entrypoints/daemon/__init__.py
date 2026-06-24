# FILE: yascheduler/entrypoints/daemon/__init__.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Subpackage facade for the daemon launchers.
#   SCOPE: no re-exports — the launchers are invoked by path from service templates, not imported.
#   DEPENDS: none
#   LINKS: M-ENTRYPOINTS-DAEMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   none
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial subpackage facade for the relocated daemon launchers; the flat residents daemon_systemd.py and daemon_sysv.py moved here from the package root in relocate-daemon-launchers.
# END_CHANGE_SUMMARY

"""Daemon launcher subpackage facade."""
