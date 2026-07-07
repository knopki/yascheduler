# FILE: yascheduler/entrypoints/cli/__init__.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Subpackage facade for CLI entry points and daemon launchers.
#   SCOPE: Subpackage facade — no re-exports; all entry points invoked by console_script or service template path substitution.
#   DEPENDS: none
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-ENTRYPOINTS-CLI-SHOW-NODES, M-ENTRYPOINTS-CLI-SUBMIT, M-ENTRYPOINTS-CLI-MANAGE-NODE, M-ENTRYPOINTS-CLI-CHECK-STATUS, M-DAEMON-SYSTEMD, M-DAEMON-SYSV, M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   none
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - daemonize moved from infra/cli/daemonize.py to sibling resident; yascheduler/infra/cli/ liquidated; no re-exports added.
#   PREVIOUS_CHANGE: v1.5.0 - daemon_systemd.py and daemon_sysv.py moved from entrypoints/daemon/ to sibling residents; entrypoints/daemon/ liquidated; no re-exports added.
# END_CHANGE_SUMMARY

"""Init, show_nodes, submit, manage_node, check_status CLI entry points and daemonize/daemon_systemd/daemon_sysv daemon launcher subpackage facade."""
