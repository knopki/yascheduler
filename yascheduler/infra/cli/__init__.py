# FILE: yascheduler/infra/cli/__init__.py
# VERSION: 2.2.0
# START_MODULE_CONTRACT
#   PURPOSE: CLI adapter package — re-exports per-command modules.
#   SCOPE: Re-exports 5 CLI command functions from per-command submodules (init moved to entrypoints/cli/).
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit - Re-exported from .submit
#   check_status - Re-exported from .check_status
#   show_nodes - Re-exported from .show_nodes
#   manage_node - Re-exported from .manage_node
#   daemonize - Re-exported from .daemonize
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.2.0 - Drop init re-export; init moved to entrypoints/cli/init.py in relocate-init-command.
#   PREVIOUS_CHANGE: v2.1.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

from .check_status import check_status
from .daemonize import daemonize
from .manage_node import manage_node
from .show_nodes import show_nodes
from .submit import submit

__all__ = [
    "check_status",
    "daemonize",
    "manage_node",
    "show_nodes",
    "submit",
]
