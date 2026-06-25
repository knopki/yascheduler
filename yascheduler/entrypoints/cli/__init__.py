# FILE: yascheduler/entrypoints/cli/__init__.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Subpackage facade for the init, show_nodes, submit, manage_node, check_status CLI entry points and the daemonize/daemon_systemd/daemon_sysv daemon launchers.
#   SCOPE: no re-exports — init, show_nodes, submit, manage_node, check_status, and daemonize are invoked by console_script; daemon_systemd and daemon_sysv are invoked by path from service templates (via %YASCHEDULER_DAEMON_FILE% substitution produced by yainit). None are imported across layers.
#   DEPENDS: none
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-ENTRYPOINTS-CLI-SHOW-NODES, M-ENTRYPOINTS-CLI-SUBMIT, M-ENTRYPOINTS-CLI-MANAGE-NODE, M-ENTRYPOINTS-CLI-CHECK-STATUS, M-DAEMON-SYSTEMD, M-DAEMON-SYSV, M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   none
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - consolidate-daemon-entrypoints: daemonize is now a sibling resident (moved from infra/cli/daemonize.py); yascheduler/infra/cli/ is liquidated; no re-exports added.
#   PREVIOUS_CHANGE: v1.5.0 - daemon_systemd.py and daemon_sysv.py now sibling residents (moved from entrypoints/daemon/ in relocate-daemon-launchers-to-cli); the entrypoints/daemon/ subpackage was liquidated; no re-exports added.
# END_CHANGE_SUMMARY

"""Init, show_nodes, submit, manage_node, check_status CLI entry points and daemonize/daemon_systemd/daemon_sysv daemon launcher subpackage facade."""
