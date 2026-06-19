# FILE: yascheduler/adapters/cli/__init__.py
# VERSION: 2.1.0
# START_MODULE_CONTRACT
#   PURPOSE: CLI adapter package — re-exports per-command modules.
#   SCOPE: Re-exports all 6 CLI command functions from per-command submodules.
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit - Re-exported from adapters.cli.submit
#   check_status - Re-exported from adapters.cli.check_status
#   init - Re-exported from adapters.cli.init
#   show_nodes - Re-exported from adapters.cli.show_nodes
#   manage_node - Re-exported from adapters.cli.manage_node
#   daemonize - Re-exported from adapters.cli.daemonize
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.0 - Switched to relative imports (R1) for submodules (clean-architecture-imports).
#   PREVIOUS_CHANGE: v2.0.0 - Re-export from per-command submodules instead of monolithic commands.py.
# END_CHANGE_SUMMARY

from .check_status import check_status
from .daemonize import daemonize
from .init import init
from .manage_node import manage_node
from .show_nodes import show_nodes
from .submit import submit

__all__ = [
    "check_status",
    "daemonize",
    "init",
    "manage_node",
    "show_nodes",
    "submit",
]
