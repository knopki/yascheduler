# FILE: yascheduler/infra/cli/__init__.py
# VERSION: 2.4.0
# START_MODULE_CONTRACT
#   PURPOSE: CLI adapter package — re-exports per-command modules.
#   SCOPE: Re-exports 3 CLI command functions from per-command submodules (init, show_nodes, and submit moved to entrypoints/cli/).
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   check_status - Re-exported from .check_status
#   manage_node - Re-exported from .manage_node
#   daemonize - Re-exported from .daemonize
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.4.0 - Drop submit re-export; submit moved to entrypoints/cli/submit.py in relocate-submit-command.
#   PREVIOUS_CHANGE: v2.3.0 - Drop show_nodes re-export; show_nodes moved to entrypoints/cli/show_nodes.py in relocate-show-nodes-command.
# END_CHANGE_SUMMARY

from .check_status import check_status
from .daemonize import daemonize
from .manage_node import manage_node

__all__ = [
    "check_status",
    "daemonize",
    "manage_node",
]
