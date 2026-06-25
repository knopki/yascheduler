# FILE: yascheduler/infra/cli/__init__.py
# VERSION: 2.6.0
# START_MODULE_CONTRACT
#   PURPOSE: CLI adapter package — re-exports per-command modules.
#   SCOPE: Re-exports 1 CLI command function from per-command submodules (init, show_nodes, submit, manage_node, and check_status moved to entrypoints/cli/).
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   daemonize - Re-exported from .daemonize
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.6.0 - Drop check_status re-export; check_status moved to entrypoints/cli/check_status.py in relocate-check-status-command.
#   PREVIOUS_CHANGE: v2.5.0 - Drop manage_node re-export; manage_node moved to entrypoints/cli/manage_node.py in relocate-manage-node-change.
# END_CHANGE_SUMMARY

from .daemonize import daemonize

__all__ = [
    "daemonize",
]
