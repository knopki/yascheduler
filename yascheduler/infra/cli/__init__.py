# FILE: yascheduler/infra/cli/__init__.py
# VERSION: 2.5.0
# START_MODULE_CONTRACT
#   PURPOSE: CLI adapter package — re-exports per-command modules.
#   SCOPE: Re-exports 2 CLI command functions from per-command submodules (init, show_nodes, submit, and manage_node moved to entrypoints/cli/).
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   check_status - Re-exported from .check_status
#   daemonize - Re-exported from .daemonize
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.5.0 - Drop manage_node re-export; manage_node moved to entrypoints/cli/manage_node.py in relocate-manage-node-command.
#   PREVIOUS_CHANGE: v2.4.0 - Drop submit re-export; submit moved to entrypoints/cli/submit.py in relocate-submit-command.
# END_CHANGE_SUMMARY

from .check_status import check_status
from .daemonize import daemonize

__all__ = [
    "check_status",
    "daemonize",
]
